"""
memory_graph.py — Prometheus's long-term memory as a typed, linked knowledge graph.

The old memory was a flat list of strings. This keeps the same facts but gives
them structure, so they can be linked, ranked, aged and visualised:

  * ENTITIES  - people, projects, tools, topics... (unique by name; aliases supported)
  * FACTS     - one statement each, linked to the entities it mentions, with
                provenance (where it was learned), confidence, importance and a
                status (active / superseded / archived)
  * RELATIONS - typed edges between entities ("Robotic Arm" --uses--> "Arduino Uno")

Design points:
  * Facts are deduplicated (exact and near-duplicate), never silently lost:
    superseded or low-value facts are ARCHIVED, not deleted.
  * Importance decays with time since last recall (half-life), and every recall
    reinforces it - what Prometheus keeps using stays sharp; the rest fades.
  * Entities are extracted by simple rules by default (no LLM call, no cost);
    callers that already know the entities (the model, when it calls the memory
    tool) can pass them explicitly.
  * Persistence uses state_io's atomic writes under one re-entrant lock; a
    corrupt file is quarantined, and an UNREADABLE file is never overwritten.
  * Facts from untrusted sources (web pages, imported notes) are flagged so the
    prompt can mark them as unverified data rather than instructions.

Pure Python, standard library only; fully unit-tested.
"""

import contextlib
import copy
import datetime
import difflib
import hashlib
import json
import logging
import math
import os
import re
import threading
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from state_io import atomic_write_json, read_json_state

logger = logging.getLogger("PrometheusMemoryGraph")

SCHEMA_VERSION = 1
ENTITY_TYPES = ("person", "project", "tool", "topic", "concept", "org", "place", "event", "skill", "other")
FACT_KINDS = ("fact", "lesson", "preference", "decision")
FACT_STATUSES = ("active", "superseded", "archived")
HALF_LIFE_DAYS = 45.0
MAX_FACT_CHARS = 2000
MAX_NAME_CHARS = 80
MAX_ENTITIES_PER_FACT = 8
NEAR_DUPLICATE_RATIO = 0.92
UNTRUSTED_SOURCE_PREFIXES = ("web:", "obsidian-inbox:", "tool:")

# Words that start sentences or fill phrases but are not entities.
_STOPWORDS = frozenset("""
a an and are as at be been but by can could did do does for from had has have he her his how i if in into is it its
just like may me more most my no not of on one only or our out over she should so some than that the their them then
there these they this those to too up us very was we were what when where which who why will with would you your
also about after again all always am any because before being between both each few first get got going here
however into let make many much must new now off once other own same see still such take tell use used using way
yes yeah okay ok hi hello hey thanks thank please sure maybe today tomorrow yesterday
""".split())
_COMMON_CAPITALISED = frozenset("""
The A An I We My It This That These Those He She They You Your Our His Her Its There Here What When Where Which Who
Why How If But And Or So Also However Then Now Today Tomorrow Yesterday Yes No Ok Okay Hi Hello Hey Thanks Please
Remember Note Notes Fact Facts Task Todo Always Never Maybe Because Since While After Before Once Still Just
Monday Tuesday Wednesday Thursday Friday Saturday Sunday January February March April May June July August
September October November December
""".split())

_CAP_WORD = r"[A-Z][A-Za-z0-9]*"
_CAP_PHRASE_RE = re.compile(rf"\b{_CAP_WORD}(?:[ \t]+{_CAP_WORD})*\b")
_WIKILINK_RE = re.compile(r"\[\[([^\[\]|#^\n]{1,80})(?:[|#][^\[\]\n]*)?\]\]")
_TAG_RE = re.compile(r"(?<![\w&])#([A-Za-z][\w/-]{1,40})")
_SENTENCE_START_RE = re.compile(r"(?:^|[.!?]\s+|\n\s*[-*]?\s*)$")


# ------------------------------------------------------------------------------
# small pure helpers
# ------------------------------------------------------------------------------
def _clean_name(name: Any) -> str:
    s = re.sub(r"\[\[|\]\]", "", str(name or ""))
    s = re.sub(r"[\x00-\x1f\x7f]", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" \t.,;:!?\"'()")
    return s[:MAX_NAME_CHARS].strip()


def _norm_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.casefold()).strip()


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text.lower())).strip()


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    return slug or "e-" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]


def _clean_text(text: Any) -> str:
    s = str(text if text is not None else "")
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s[:MAX_FACT_CHARS]


def _tokens(text: str) -> List[str]:
    out = []
    for tok in re.findall(r"[a-z0-9]+", text.lower()):
        if len(tok) <= 2 or tok in _STOPWORDS:
            continue
        if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
            tok = tok[:-1]  # crude plural folding: "servos" ~ "servo"
        out.append(tok)
    return out


_NEGATION_RE = re.compile(r"\b(?:not|no|never|cannot|without|none)\b|n't\b")
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")


def _fold(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word


def _same_statement(a: str, b: str) -> bool:
    """Two texts that LOOK alike are only duplicates if they say the same thing:
    identical numbers, identical negations, and at most inflection/typo-level
    differences between words. ("The arm has 4 joints" vs "...has 5 joints", or
    "is" vs "is not", must stay separate facts - merging them would lose information.)"""
    if sorted(_NUMBER_RE.findall(a)) != sorted(_NUMBER_RE.findall(b)):
        return False
    if len(_NEGATION_RE.findall(a.lower())) != len(_NEGATION_RE.findall(b.lower())):
        return False
    wa = {_fold(w) for w in _norm_text(a).split()}
    wb = {_fold(w) for w in _norm_text(b).split()}
    only_a, only_b = wa - wb, wb - wa

    def covered(words, others):
        return all(any(difflib.SequenceMatcher(None, w, o).ratio() >= 0.8 for o in others) for w in words)
    return covered(only_a, only_b) and covered(only_b, only_a)


def is_untrusted_source(source: str) -> bool:
    return str(source or "").startswith(UNTRUSTED_SOURCE_PREFIXES)


def extract_entities(text: str, known_names: Iterable[str] = ()) -> List[Tuple[str, str]]:
    """Rule-based entity extraction (no LLM). Returns [(name, type_guess)].
    Finds [[wikilinks]], #tags, already-known entity names, and Capitalised
    phrases that are not just sentence-initial common words."""
    found: Dict[str, Tuple[str, str]] = {}

    def add(name: str, etype: str):
        name = _clean_name(name)
        if len(name) < 2:
            return
        found.setdefault(_norm_name(name), (name, etype))

    for m in _WIKILINK_RE.finditer(text):
        add(m.group(1), "other")
    for m in _TAG_RE.finditer(text):
        add(m.group(1).replace("-", " ").replace("_", " "), "topic")

    known_names = list(known_names)
    known_norm = {_norm_name(n) for n in known_names}
    lowered = " " + _norm_text(text) + " "
    for name in known_names:
        key = _norm_text(name)
        if key and f" {key} " in lowered:
            add(name, "other")

    for m in _CAP_PHRASE_RE.finditer(text):
        words = m.group(0).split()
        sentence_start = bool(_SENTENCE_START_RE.search(text[:m.start()]))
        while words and (words[0] in _COMMON_CAPITALISED or words[0].casefold() in _STOPWORDS):
            words.pop(0)
            sentence_start = False
        while words and (words[-1] in _COMMON_CAPITALISED or words[-1].casefold() in _STOPWORDS):
            words.pop()
        if not words:
            continue
        phrase = " ".join(words)
        if len(words) == 1:
            w = words[0]
            if len(w) < 3 and not w.isupper():
                continue
            # A lone capitalised word that merely STARTS a sentence ("Lesson: ...",
            # "Remember ...") is far more likely an ordinary word than a name. Accept it
            # only if it looks like a name on its own (acronym, CamelCase, has a digit)
            # or is already known; callers that know the entity pass it explicitly.
            if sentence_start and not (len(w) >= 3 and w.isupper() or re.search(r"[a-z][A-Z]|\d", w)
                                       or _norm_name(w) in known_norm):
                continue
        add(phrase, "other")
    return list(found.values())


# ------------------------------------------------------------------------------
# the graph
# ------------------------------------------------------------------------------
class MemoryGraph:
    def __init__(self, path: str, half_life_days: float = HALF_LIFE_DAYS,
                 now: Optional[Callable[[], datetime.datetime]] = None):
        self.path = path
        self.half_life_days = half_life_days
        self._now = now or datetime.datetime.now
        self._lock = threading.RLock()
        self._batch_depth = 0
        self._dirty = False
        self._unsafe_to_save = False  # set when the file exists but could not be READ
        self.entities: Dict[str, Dict[str, Any]] = {}
        self.facts: Dict[str, Dict[str, Any]] = {}
        self.relations: List[Dict[str, Any]] = []
        self._name_index: Dict[str, str] = {}
        self._load()

    # -- time ------------------------------------------------------------------
    def _iso(self) -> str:
        return self._now().isoformat(timespec="seconds")

    def _parse(self, stamp: Optional[str]) -> datetime.datetime:
        try:
            return datetime.datetime.fromisoformat(stamp) if stamp else self._now()
        except (TypeError, ValueError):
            return self._now()

    # -- persistence -----------------------------------------------------------
    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            data = read_json_state(self.path)
        except json.JSONDecodeError as e:
            logger.error(f"Memory graph corrupt (moved aside), starting empty: {e}")
            return
        except OSError as e:
            logger.error(f"Memory graph unreadable, will NOT overwrite it: {e}")
            self._unsafe_to_save = True
            return
        if not isinstance(data, dict):
            logger.error("Memory graph file is not a JSON object; ignoring it (file left untouched).")
            self._unsafe_to_save = True
            return
        for e in data.get("entities", []) if isinstance(data.get("entities"), list) else []:
            if isinstance(e, dict) and e.get("id") and e.get("name"):
                e.setdefault("type", "other")
                e.setdefault("aliases", [])
                e.setdefault("mentions", 0)
                e.setdefault("pinned", False)
                e.setdefault("created", self._iso())
                e.setdefault("updated", e["created"])
                self.entities[e["id"]] = e
        for f in data.get("facts", []) if isinstance(data.get("facts"), list) else []:
            if isinstance(f, dict) and f.get("id") and isinstance(f.get("text"), str):
                f.setdefault("kind", "fact")
                f.setdefault("entities", [])
                f.setdefault("source", "unknown")
                f.setdefault("confidence", 0.7)
                f.setdefault("importance", 0.5)
                f.setdefault("created", self._iso())
                f.setdefault("updated", f["created"])
                f.setdefault("last_accessed", f["created"])
                f.setdefault("access_count", 0)
                f.setdefault("status", "active")
                f.setdefault("superseded_by", None)
                f.setdefault("pinned", False)
                f["entities"] = [x for x in f["entities"] if x in self.entities]
                self.facts[f["id"]] = f
        for r in data.get("relations", []) if isinstance(data.get("relations"), list) else []:
            if isinstance(r, dict) and r.get("source") in self.entities and r.get("target") in self.entities and r.get("relation"):
                r.setdefault("id", "r_" + hashlib.sha1(f"{r['source']}|{r['relation']}|{r['target']}".encode()).hexdigest()[:10])
                r.setdefault("fact_id", None)
                r.setdefault("created", self._iso())
                self.relations.append(r)
        self._reindex()

    def _save(self) -> bool:
        if self._batch_depth:
            self._dirty = True
            return True
        if self._unsafe_to_save:
            logger.error("Refusing to save the memory graph: the existing file could not be read.")
            return False
        payload = {"schema_version": SCHEMA_VERSION, "saved": self._iso(),
                   "entities": list(self.entities.values()), "facts": list(self.facts.values()),
                   "relations": self.relations}
        self._dirty = False
        return atomic_write_json(self.path, payload, indent=1, prefix="graph_")

    @contextlib.contextmanager
    def batch(self):
        """Group many mutations into ONE write: `with graph.batch(): ...`"""
        with self._lock:
            self._batch_depth += 1
            try:
                yield self
            finally:
                self._batch_depth -= 1
                if self._batch_depth == 0 and self._dirty:
                    self._save()

    def _reindex(self) -> None:
        idx: Dict[str, str] = {}
        for eid, e in self.entities.items():
            idx[_norm_name(e["name"])] = eid
            for alias in e.get("aliases", []):
                idx.setdefault(_norm_name(alias), eid)
        self._name_index = idx

    # -- entities --------------------------------------------------------------
    def get_or_create_entity(self, name: str, etype: str = "other") -> Dict[str, Any]:
        with self._lock:
            name = _clean_name(name)
            if not name:
                raise ValueError("entity name is empty")
            etype = etype if etype in ENTITY_TYPES else "other"
            eid = self._name_index.get(_norm_name(name))
            if eid:
                ent = self.entities[eid]
                if ent["type"] in ("other", "topic", "concept") and etype not in ("other", "topic", "concept", ent["type"]):
                    ent["type"] = etype  # a more specific type beats a vague one
                    ent["updated"] = self._iso()
                return ent
            eid = _slug(name)
            if eid in self.entities:
                eid = f"{eid}-{hashlib.sha1(name.encode('utf-8')).hexdigest()[:4]}"
            now = self._iso()
            ent = {"id": eid, "name": name, "type": etype, "aliases": [], "mentions": 0,
                   "pinned": False, "created": now, "updated": now}
            self.entities[eid] = ent
            self._name_index[_norm_name(name)] = eid
            return ent

    def add_alias(self, entity_name: str, alias: str) -> None:
        with self._lock:
            ent = self.get_or_create_entity(entity_name)
            alias = _clean_name(alias)
            key = _norm_name(alias)
            if alias and key not in self._name_index:
                ent["aliases"].append(alias)
                self._name_index[key] = ent["id"]
                self._save()

    def find_entity(self, name: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            eid = self._name_index.get(_norm_name(_clean_name(name)))
            return self.entities.get(eid) if eid else None

    def merge_entities(self, source_name: str, target_name: str) -> bool:
        """Fold `source` into `target`: facts, relations and the name (as an alias) move over."""
        with self._lock:
            src, dst = self.find_entity(source_name), self.find_entity(target_name)
            if not src or not dst or src["id"] == dst["id"]:
                return False
            for f in self.facts.values():
                if src["id"] in f["entities"]:
                    f["entities"] = [dst["id"] if x == src["id"] else x for x in f["entities"]]
                    f["entities"] = list(dict.fromkeys(f["entities"]))
            seen = set()
            merged = []
            for r in self.relations:
                s = dst["id"] if r["source"] == src["id"] else r["source"]
                t = dst["id"] if r["target"] == src["id"] else r["target"]
                if s == t:
                    continue
                key = (s, r["relation"], t)
                if key in seen:
                    continue
                seen.add(key)
                r["source"], r["target"] = s, t
                merged.append(r)
            self.relations = merged
            dst["mentions"] += src.get("mentions", 0)
            for alias in [src["name"]] + src.get("aliases", []):
                if _norm_name(alias) != _norm_name(dst["name"]) and alias not in dst["aliases"]:
                    dst["aliases"].append(alias)
            del self.entities[src["id"]]
            self._reindex()
            dst["updated"] = self._iso()
            self._save()
            return True

    # -- facts -----------------------------------------------------------------
    def _find_near_duplicate(self, text: str, entity_ids: List[str]) -> Optional[Dict[str, Any]]:
        norm = _norm_text(text)
        if not norm:
            return None
        pool = [f for f in self.facts.values() if f["status"] == "active"]
        if entity_ids:
            sharing = [f for f in pool if set(f["entities"]) & set(entity_ids)]
            pool = sharing or pool
        pool = sorted(pool, key=lambda f: f["created"], reverse=True)[:300]
        for f in pool:
            other = _norm_text(f["text"])
            if not other or not (0.8 <= len(other) / max(1, len(norm)) <= 1.25):
                continue
            sm = difflib.SequenceMatcher(None, norm, other, autojunk=False)
            if sm.real_quick_ratio() >= NEAR_DUPLICATE_RATIO and sm.quick_ratio() >= NEAR_DUPLICATE_RATIO \
                    and sm.ratio() >= NEAR_DUPLICATE_RATIO and _same_statement(text, f["text"]):
                return f
        return None

    def add_fact(self, text: str, entities: Optional[List[Any]] = None,
                 relations: Optional[List[Dict[str, str]]] = None, source: str = "operator",
                 confidence: float = 0.8, importance: float = 0.5, kind: str = "fact",
                 auto_extract: bool = True, pinned: bool = False) -> Dict[str, Any]:
        """Store one fact. `entities` may be names or {"name", "type"} dicts; extra
        entities are found by rule when auto_extract is on. Returns
        {"fact_id", "created", "entities"}; re-adding a known (or near-identical)
        fact refreshes it instead of duplicating it."""
        with self._lock:
            text = _clean_text(text)
            if not text:
                raise ValueError("fact text is empty")
            kind = kind if kind in FACT_KINDS else "fact"
            confidence = max(0.0, min(1.0, float(confidence)))
            importance = max(0.0, min(1.0, float(importance)))

            specs: List[Tuple[str, str]] = []
            for e in entities or []:
                if isinstance(e, dict):
                    specs.append((str(e.get("name", "")), str(e.get("type", "other"))))
                else:
                    specs.append((str(e), "other"))
            if auto_extract:
                specs += extract_entities(text, known_names=[e["name"] for e in self.entities.values()])
            ent_ids: List[str] = []
            for name, etype in specs:
                if len(ent_ids) >= MAX_ENTITIES_PER_FACT:
                    break
                try:
                    ent = self.get_or_create_entity(name, etype)
                except ValueError:
                    continue
                if ent["id"] not in ent_ids:
                    ent_ids.append(ent["id"])

            now = self._iso()
            fid = "f_" + hashlib.sha1(_norm_text(text).encode("utf-8")).hexdigest()[:12]
            existing = self.facts.get(fid) or self._find_near_duplicate(text, ent_ids)
            if existing:
                existing["updated"] = existing["last_accessed"] = now
                existing["entities"] = list(dict.fromkeys(existing["entities"] + ent_ids))
                existing["confidence"] = max(existing["confidence"], confidence)
                existing["importance"] = max(existing["importance"], importance)
                if existing["status"] == "archived":
                    existing["status"] = "active"
                fact = existing
                created = False
            else:
                fact = {"id": fid, "text": text, "kind": kind, "entities": ent_ids, "source": str(source)[:120],
                        "confidence": confidence, "importance": importance, "created": now, "updated": now,
                        "last_accessed": now, "access_count": 0, "status": "active", "superseded_by": None,
                        "pinned": bool(pinned)}
                self.facts[fid] = fact
                for eid in ent_ids:
                    self.entities[eid]["mentions"] += 1
                    self.entities[eid]["updated"] = now
                created = True

            for rel in relations or []:
                try:
                    self._add_relation_unlocked(rel.get("source"), rel.get("relation"), rel.get("target"), fact["id"])
                except (ValueError, AttributeError):
                    continue
            self._save()
            return {"fact_id": fact["id"], "created": created,
                    "entities": [self.entities[e]["name"] for e in fact["entities"] if e in self.entities]}

    def _add_relation_unlocked(self, source: Any, relation: Any, target: Any, fact_id: Optional[str]) -> None:
        relation = re.sub(r"\s+", " ", str(relation or "")).strip()[:40]
        if not relation:
            raise ValueError("relation is empty")
        s = self.get_or_create_entity(source)["id"]
        t = self.get_or_create_entity(target)["id"]
        if s == t:
            raise ValueError("relation links an entity to itself")
        for r in self.relations:
            if (r["source"], r["relation"].casefold(), r["target"]) == (s, relation.casefold(), t):
                return
        self.relations.append({"id": "r_" + hashlib.sha1(f"{s}|{relation}|{t}".encode()).hexdigest()[:10],
                               "source": s, "relation": relation, "target": t,
                               "fact_id": fact_id, "created": self._iso()})

    def add_relation(self, source: str, relation: str, target: str) -> bool:
        with self._lock:
            try:
                self._add_relation_unlocked(source, relation, target, None)
            except ValueError:
                return False
            self._save()
            return True

    def supersede(self, old_id: str, new_id: str) -> bool:
        with self._lock:
            old, new = self.facts.get(old_id), self.facts.get(new_id)
            if not old or not new or old_id == new_id:
                return False
            old["status"], old["superseded_by"], old["updated"] = "superseded", new_id, self._iso()
            self._save()
            return True

    def archive(self, fact_id: str) -> bool:
        with self._lock:
            f = self.facts.get(fact_id)
            if not f or f["status"] == "archived":
                return False
            f["status"], f["updated"] = "archived", self._iso()
            self._save()
            return True

    def import_legacy_facts(self, facts: Iterable[str]) -> int:
        """One-time import of the old flat memory list. Idempotent."""
        added = 0
        with self.batch():
            for text in facts:
                if isinstance(text, str) and text.strip():
                    if self.add_fact(text, source="legacy-memory", confidence=0.7)["created"]:
                        added += 1
        return added

    # -- ranking / forgetting ----------------------------------------------------
    def effective_importance(self, fact: Dict[str, Any], now: Optional[datetime.datetime] = None) -> float:
        """Stored importance, decayed by time since last recall, reinforced by use."""
        if fact.get("pinned"):
            return float(fact["importance"])
        now = now or self._now()
        age_days = max(0.0, (now - self._parse(fact.get("last_accessed") or fact.get("created"))).total_seconds() / 86400.0)
        decay = 0.5 ** (age_days / max(0.1, self.half_life_days))
        reinforce = min(0.2, 0.02 * fact.get("access_count", 0))
        return max(0.0, min(1.0, (float(fact["importance"]) + reinforce) * decay))

    def entity_importance(self, entity_id: str, now: Optional[datetime.datetime] = None) -> float:
        with self._lock:
            ent = self.entities.get(entity_id)
            if not ent:
                return 0.0
            vals = [self.effective_importance(f, now) for f in self.facts.values()
                    if entity_id in f["entities"] and f["status"] == "active"]
            mention_part = min(1.0, math.log1p(ent.get("mentions", 0)) / math.log(10))
            return round(min(1.0, 0.7 * (max(vals) if vals else 0.0) + 0.3 * mention_part), 3)

    def recall(self, query: str, top_k: int = 5, kinds: Optional[Iterable[str]] = None,
               touch: bool = True, min_score: float = 0.05) -> List[Dict[str, Any]]:
        """Facts relevant to `query`, best first. Scoring blends word overlap, a
        boost for named entities (and a smaller one for their neighbours), then
        weights by effective importance and confidence. Recalled facts are
        reinforced (access_count / last_accessed) so useful memories stay alive."""
        with self._lock:
            q = set(_tokens(query))
            qnorm = " " + _norm_text(query) + " "
            matched = set()
            for key, eid in self._name_index.items():
                nk = _norm_text(key)
                if nk and f" {nk} " in qnorm:  # a name made only of punctuation normalises to "" - never match on that
                    matched.add(eid)
            if not q and not matched:
                return []
            neighbours = set()
            for r in self.relations:
                if r["source"] in matched:
                    neighbours.add(r["target"])
                if r["target"] in matched:
                    neighbours.add(r["source"])
            wanted = set(kinds) if kinds else None
            now = self._now()
            scored = []
            for f in self.facts.values():
                if f["status"] != "active" or (wanted and f["kind"] not in wanted):
                    continue
                t = set(_tokens(f["text"]))
                overlap = len(q & t)
                base = overlap / math.sqrt(len(q) * len(t)) if overlap and q and t else 0.0
                fe = set(f["entities"])
                if fe & matched:
                    base += 0.5
                elif fe & neighbours:
                    base += 0.15
                if base <= 0:
                    continue
                score = base * (0.4 + 0.6 * self.effective_importance(f, now)) * (0.5 + 0.5 * f["confidence"])
                if score >= min_score:
                    scored.append((score, f))
            scored.sort(key=lambda x: (-x[0], x[1]["created"]))
            out = []
            stamp = self._iso()
            for score, f in scored[:max(0, top_k)]:
                if touch:
                    f["access_count"] += 1
                    f["last_accessed"] = stamp
                    f["importance"] = min(1.0, f["importance"] + 0.02)
                out.append({"id": f["id"], "text": f["text"], "kind": f["kind"], "score": round(score, 3),
                            "entities": [self.entities[e]["name"] for e in f["entities"] if e in self.entities],
                            "source": f["source"], "created": f["created"],
                            "untrusted": is_untrusted_source(f["source"])})
            if out and touch:
                self._save()
            return out

    def top_facts(self, limit: int = 25, kinds: Optional[Iterable[str]] = None,
                  include_untrusted: bool = False) -> List[str]:
        """The `limit` active facts that currently matter most (importance after decay),
        for the standing part of the prompt - so the prompt stops growing with memory.
        Facts from untrusted sources (web pages, imported notes) are EXCLUDED by default:
        the standing section carries no per-fact warning label, so they may only reach the
        prompt through recall(), which flags them."""
        with self._lock:
            wanted = set(kinds) if kinds else None
            now = self._now()
            ranked = sorted((f for f in self.facts.values()
                             if f["status"] == "active" and (not wanted or f["kind"] in wanted)
                             and (include_untrusted or not is_untrusted_source(f["source"]))),
                            key=lambda f: (-self.effective_importance(f, now), f["created"]))
            return [f["text"] for f in ranked[:max(0, limit)]]

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for f in self.facts.values() if f["status"] == "active")

    def prune(self, min_effective: float = 0.03, max_active: int = 3000) -> int:
        """Archive (never delete) facts whose effective importance has faded, and
        the weakest ones if there are too many. Pinned facts are never touched."""
        with self._lock:
            now = self._now()
            active = [f for f in self.facts.values() if f["status"] == "active" and not f.get("pinned")]
            doomed = [f for f in active if self.effective_importance(f, now) < min_effective]
            keep = [f for f in active if f not in doomed]
            over = len(keep) + sum(1 for f in self.facts.values() if f["status"] == "active" and f.get("pinned")) - max_active
            if over > 0:
                keep.sort(key=lambda f: self.effective_importance(f, now))
                doomed += keep[:over]
            for f in doomed:
                f["status"], f["updated"] = "archived", self._iso()
            if doomed:
                self._save()
            return len(doomed)

    # -- inspection --------------------------------------------------------------
    def neighbors(self, entity_name: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            ent = self.find_entity(entity_name)
            if not ent:
                return None
            eid = ent["id"]
            facts = [f for f in self.facts.values() if eid in f["entities"] and f["status"] == "active"]
            co: Dict[str, int] = {}
            for f in facts:
                for other in f["entities"]:
                    if other != eid and other in self.entities:
                        co[other] = co.get(other, 0) + 1
            rels = [{"source": self.entities[r["source"]]["name"], "relation": r["relation"],
                     "target": self.entities[r["target"]]["name"]}
                    for r in self.relations if eid in (r["source"], r["target"])]
            return {"entity": dict(ent), "facts": [dict(f) for f in sorted(facts, key=lambda f: f["created"])],
                    "relations": rels,
                    "related": sorted(((self.entities[o]["name"], n) for o, n in co.items()), key=lambda x: (-x[1], x[0])),
                    "importance": self.entity_importance(eid)}

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            by_status: Dict[str, int] = {}
            for f in self.facts.values():
                by_status[f["status"]] = by_status.get(f["status"], 0) + 1
            by_type: Dict[str, int] = {}
            for e in self.entities.values():
                by_type[e["type"]] = by_type.get(e["type"], 0) + 1
            return {"entities": len(self.entities), "facts": len(self.facts), "relations": len(self.relations),
                    "facts_by_status": by_status, "entities_by_type": by_type}

    def export_snapshot(self) -> Dict[str, Any]:
        """A consistent deep copy (with computed importances) for exporters."""
        with self._lock:
            now = self._now()
            facts = copy.deepcopy(self.facts)
            for f in facts.values():
                f["effective_importance"] = round(self.effective_importance(f, now), 3)
            entities = copy.deepcopy(self.entities)
            for eid, e in entities.items():
                e["importance"] = self.entity_importance(eid, now)
            return {"entities": entities, "facts": facts, "relations": copy.deepcopy(self.relations)}
