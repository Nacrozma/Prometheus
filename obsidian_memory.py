"""
obsidian_memory.py — mirror Prometheus's memory graph into an Obsidian vault.

An Obsidian vault is just a folder of Markdown files; [[wikilinks]] between them
are what Obsidian's Graph View draws. So no plugin or API is needed: Prometheus
writes well-linked notes into  <vault>/Prometheus/  and Obsidian shows the map.

  Prometheus/Index.md        home note: stats, most important entities, recent days
  Prometheus/Entities/*.md   one note per entity: its facts (cross-linked), relations
  Prometheus/Timeline/*.md   one note per day: what was learned, chained by date
  Prometheus/Skills/*.md     skills Prometheus has acquired (name, version, status)
  Prometheus/Lessons.md      lessons learned from past tasks
  Prometheus/Current Task.md the active goal and steps
  Prometheus/Inbox/          drop notes here; they are ingested as facts (then moved)

Safety rules (each one is unit-tested):
  * It only ever writes inside  <vault>/<root>/  - note names are sanitised and a
    path (or symlink) that would escape is refused.
  * Your own writing is preserved. Each note has a generated block between
    <!-- prometheus:begin --> and <!-- prometheus:end -->; everything BELOW it is
    yours and survives every re-export, as do frontmatter properties you add.
    If you edit INSIDE the generated block the note is left alone and reported
    as a conflict (force=True overwrites the block, still keeping your tail).
  * Links are path-qualified, so a link can never be hijacked by a note of the same
    name elsewhere in your vault.
  * Writes are atomic, unchanged notes are not rewritten, stale generated notes are
    only deleted if you never touched them.
  * Inbox notes are untrusted input: size-capped, parsed as plain text only, and
    their facts are flagged as unverified when fed back into a prompt.
"""

import datetime
import hashlib
import json
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from state_io import atomic_write_json, atomic_write_text, read_json_state

DEFAULT_ROOT = "Prometheus"
MANIFEST_NAME = ".prometheus_manifest.json"
BEGIN = "<!-- prometheus:begin -->"
END = "<!-- prometheus:end -->"
USER_STUB = "\n\n## My notes\n\n"
MAX_NOTE_BYTES = 5_000_000
MAX_INBOX_BYTES = 64_000
MAX_INBOX_FACTS_PER_FILE = 50
RESERVED_STEMS = ("Index", "README", "Lessons", "Current Task")
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_FORBIDDEN_IN_NAMES = re.compile(r'[\\/:*?"<>|#^\[\]\x00-\x1f\x7f]')
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class VaultError(Exception):
    """The vault path or a note path is unusable or unsafe."""


def safe_note_name(title: Any, max_len: int = 80) -> str:
    """A filename (no extension) that is valid on Windows/macOS/Linux and in
    Obsidian links: forbidden characters become spaces, no leading/trailing
    dots, Windows device names get a suffix, empty becomes 'Untitled'."""
    s = _FORBIDDEN_IN_NAMES.sub(" ", str(title if title is not None else ""))
    s = re.sub(r"\s+", " ", s).strip().strip(".").strip()
    s = s[:max_len].strip().strip(".").strip()
    if not s:
        s = "Untitled"
    if s.split(".")[0].upper() in _WINDOWS_RESERVED:
        s += "_"
    return s


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _norm_nl(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _yaml_str(value: Any) -> str:
    return json.dumps(str(value), ensure_ascii=False)  # a JSON string is a valid YAML double-quoted scalar


def _yaml_list(items: List[str]) -> str:
    return "[" + ", ".join(_yaml_str(i) for i in items) + "]"


# ------------------------------------------------------------------------------
# frontmatter (just enough YAML to preserve what the user adds)
# ------------------------------------------------------------------------------
def split_frontmatter(text: str) -> Tuple[Optional[Dict[str, List[str]]], str]:
    """Returns (properties, rest). properties maps each top-level key to its raw
    lines (key line first, then any continuation lines). (None, text) if there
    is no leading frontmatter block."""
    text = _norm_nl(text)
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---", 3)
    if end < 0:
        return None, text
    after = text[end + 4:]
    if after and not after.startswith("\n"):
        return None, text
    props: Dict[str, List[str]] = {}
    current: Optional[str] = None
    for line in text[4:end].split("\n"):
        m = re.match(r"^([A-Za-z0-9_\-]+):", line)
        if m:
            current = m.group(1)
            props[current] = [line]
        elif current is not None:
            props[current].append(line)
    return props, after.lstrip("\n")


def _parse_list_value(lines: List[str]) -> List[str]:
    first = lines[0].split(":", 1)[1].strip()
    items: List[str] = []
    if first.startswith("[") and first.endswith("]"):
        inner = first[1:-1]
        items = [p.strip().strip("'\"") for p in inner.split(",")]
    elif first:
        items = [p.strip().strip("'\"") for p in first.split(",")]
    for ln in lines[1:]:
        m = re.match(r"^\s*-\s+(.*)$", ln)
        if m:
            items.append(m.group(1).strip().strip("'\""))
    return [i for i in items if i]


def render_frontmatter(generated: Dict[str, Any], tags: List[str], aliases: List[str],
                       existing: Optional[Dict[str, List[str]]]) -> str:
    """Generated properties first; the user's `tags`/`aliases` are merged in, and
    any other property the user added is carried over untouched."""
    existing = existing or {}
    lines = ["---"]
    for key, value in generated.items():
        if isinstance(value, list):
            lines.append(f"{key}: {_yaml_list(value)}")
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            lines.append(f"{key}: {value}")
        elif isinstance(value, str) and _DAY_RE.match(value):
            lines.append(f"{key}: {value}")
        else:
            lines.append(f"{key}: {_yaml_str(value)}")
    for key, ours in (("tags", tags), ("aliases", aliases)):
        merged = list(dict.fromkeys(list(ours) + (_parse_list_value(existing[key]) if key in existing else [])))
        if merged:
            lines.append(f"{key}: {_yaml_list(merged)}")
    for key, raw in existing.items():
        if key not in generated and key not in ("tags", "aliases"):
            lines.extend(raw)
    lines.append("---")
    return "\n".join(lines)


# ------------------------------------------------------------------------------
# names and links
# ------------------------------------------------------------------------------
class Names:
    """Stable, collision-free note names inside the Prometheus folder. Names are
    remembered in the manifest, so a note keeps its filename (and every link to
    it stays valid) even when new entities with similar names appear."""

    FOLDERS = {"ent": "Entities", "skill": "Skills", "day": "Timeline"}

    def __init__(self, root_name: str, known: Optional[Dict[str, str]] = None):
        self.root_name = root_name
        self.map: Dict[str, str] = dict(known or {})
        self.used = {v.casefold() for v in self.map.values()} | {s.casefold() for s in RESERVED_STEMS}

    def assign(self, key: str, preferred: str) -> str:
        if key in self.map:
            return self.map[key]
        if key.startswith("day:"):
            name = key[4:]
        else:
            base = safe_note_name(preferred)
            name, n = base, 2
            while name.casefold() in self.used:
                name = f"{base} ({n})"
                n += 1
        self.map[key] = name
        self.used.add(name.casefold())
        return name

    def rel(self, key: str) -> str:
        return f"{self.FOLDERS[key.split(':', 1)[0]]}/{self.map[key]}.md"

    def link(self, key: str, display: Optional[str] = None) -> str:
        name = self.map[key]
        target = f"{self.root_name}/{self.FOLDERS[key.split(':', 1)[0]]}/{name}"
        shown = (display or name).replace("|", "/").replace("]", ")").replace("[", "(")
        return f"[[{target}|{shown}]]"

    def root_link(self, stem: str, display: Optional[str] = None) -> str:
        return f"[[{self.root_name}/{stem}|{display or stem}]]"


# ------------------------------------------------------------------------------
# text rendering
# ------------------------------------------------------------------------------
def neutralise(text: str) -> str:
    """Make arbitrary (model/web/user-supplied) text safe to place in a note:
    one line, no wikilinks, no HTML, no accidental #tags."""
    s = _norm_nl(str(text))
    s = re.sub(r"\[\[([^\[\]|]*)(?:\|([^\[\]]*))?\]\]", lambda m: m.group(2) or m.group(1), s)
    s = s.replace("[[", "[ [").replace("]]", "] ]")
    s = s.replace("<", "&lt;").replace(">", "&gt;")
    s = re.sub(r"(?<![\w&\\])#(?=\w)", r"\\#", s)
    s = re.sub(r"\s*\n\s*", " ", s)
    return s.strip()


def link_entities_in_text(text: str, entities: List[Dict[str, Any]], names: Names,
                          skip_id: Optional[str] = None) -> str:
    """Neutralise `text`, then turn the first mention of each of its entities into a
    wikilink. Entities that are not mentioned by name are appended as links."""
    out = neutralise(text)
    placeholders: List[str] = []
    unmentioned: List[str] = []
    for ent in sorted(entities, key=lambda e: -len(e["name"])):
        key = f"ent:{ent['id']}"
        if key not in names.map:
            continue
        if ent["id"] == skip_id:
            continue
        done = False
        for label in [ent["name"]] + list(ent.get("aliases", [])):
            m = re.search(rf"(?<![\w]){re.escape(label)}(?![\w])", out, flags=re.IGNORECASE)
            if m:
                placeholders.append(names.link(key, m.group(0)))
                out = out[:m.start()] + f"\x00{len(placeholders) - 1}\x00" + out[m.end():]
                done = True
                break
        if not done:
            unmentioned.append(names.link(key, ent["name"]))
    out = re.sub(r"\x00(\d+)\x00", lambda m: placeholders[int(m.group(1))], out)
    if unmentioned:
        out += "  — " + " · ".join(unmentioned)
    return out


def _day(stamp: str) -> str:
    return str(stamp)[:10]


# ------------------------------------------------------------------------------
# report
# ------------------------------------------------------------------------------
@dataclass
class ExportReport:
    created: List[str] = field(default_factory=list)
    updated: List[str] = field(default_factory=list)
    unchanged: List[str] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)   # you edited the generated block: left alone
    deleted: List[str] = field(default_factory=list)
    stale_kept: List[str] = field(default_factory=list)  # stale but touched by you: kept
    errors: List[str] = field(default_factory=list)
    vault_marker: bool = True

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        parts = [f"{len(self.created)} created", f"{len(self.updated)} updated", f"{len(self.unchanged)} unchanged"]
        if self.conflicts:
            parts.append(f"{len(self.conflicts)} skipped (you edited the generated block)")
        if self.deleted:
            parts.append(f"{len(self.deleted)} removed")
        if self.stale_kept:
            parts.append(f"{len(self.stale_kept)} stale kept")
        if self.errors:
            parts.append(f"{len(self.errors)} errors")
        return ", ".join(parts)


# ------------------------------------------------------------------------------
# the mirror
# ------------------------------------------------------------------------------
class ObsidianMirror:
    def __init__(self, vault_dir: str, root_name: str = DEFAULT_ROOT):
        vault = os.path.realpath(os.path.expanduser(str(vault_dir or "")))
        if not vault_dir or not os.path.isdir(vault):
            raise VaultError(f"Obsidian vault folder does not exist: {vault_dir!r}")
        if vault == os.path.dirname(vault) or vault == os.path.realpath(os.path.expanduser("~")):
            raise VaultError("Refusing to use a filesystem root or your home folder as the vault; pick the vault folder itself.")
        self.vault = vault
        self.root_name = safe_note_name(root_name or DEFAULT_ROOT)
        self.root = os.path.join(self.vault, self.root_name)
        self.manifest_path = os.path.join(self.root, MANIFEST_NAME)

    # -- paths ---------------------------------------------------------------
    @property
    def has_vault_marker(self) -> bool:
        return os.path.isdir(os.path.join(self.vault, ".obsidian"))

    def _safe_path(self, rel: str) -> str:
        parts = rel.replace("\\", "/").split("/")
        if any(p in ("", ".", "..") for p in parts):
            raise VaultError(f"unsafe note path: {rel!r}")
        full = os.path.join(self.root, *parts)
        real_root = os.path.realpath(self.root)
        try:
            inside = os.path.commonpath([os.path.realpath(os.path.dirname(full)), real_root]) == real_root
        except ValueError:
            inside = False
        if not inside or os.path.islink(full):
            raise VaultError(f"refusing path outside the Prometheus folder: {rel!r}")
        return full

    # -- manifest ------------------------------------------------------------
    def _load_manifest(self) -> Dict[str, Any]:
        empty = {"version": 1, "files": {}, "names": {}}
        if not os.path.exists(self.manifest_path):
            return empty
        try:
            data = read_json_state(self.manifest_path)
        except Exception:
            return empty  # unreadable/corrupt manifest: every existing note is then treated as "not ours to overwrite"
        if not isinstance(data, dict):
            return empty
        data.setdefault("files", {})
        data.setdefault("names", {})
        return data

    # -- export ----------------------------------------------------------------
    def export(self, snapshot: Dict[str, Any], skills: Optional[List[Dict[str, Any]]] = None,
               task_state: Optional[Dict[str, Any]] = None, force: bool = False,
               now: Optional[datetime.datetime] = None) -> ExportReport:
        report = ExportReport(vault_marker=self.has_vault_marker)
        now = now or datetime.datetime.now()
        try:
            os.makedirs(self.root, exist_ok=True)
        except OSError as e:
            report.errors.append(f"cannot create {self.root}: {e}")
            return report
        manifest = self._load_manifest()
        names = Names(self.root_name, manifest.get("names"))

        entities = snapshot.get("entities", {})
        facts = snapshot.get("facts", {})
        relations = snapshot.get("relations", [])
        skills = skills or []

        for eid in sorted(entities):
            names.assign(f"ent:{eid}", entities[eid]["name"])
        for sk in skills:
            names.assign(f"skill:{sk.get('name', 'skill')}", sk.get("name", "skill"))
        active = {fid: f for fid, f in facts.items() if f.get("status") == "active"}
        days = sorted({_day(f["created"]) for f in active.values() if _DAY_RE.match(_day(f["created"]))})
        for d in days:
            names.assign(f"day:{d}", d)

        desired: Dict[str, Tuple[Dict[str, Any], List[str], List[str], str]] = {}
        self._build_index(desired, names, entities, active, relations, skills, days, now)
        self._build_entities(desired, names, entities, facts, relations)
        self._build_timeline(desired, names, entities, active, days)
        self._build_lessons(desired, names, entities, active)
        self._build_skills(desired, names, skills)
        self._build_task(desired, task_state or {})
        self._build_readme(desired)

        for rel in sorted(desired):
            gen, tags, aliases, body = desired[rel]
            try:
                self._write_note(rel, gen, tags, aliases, body, force, manifest, report)
            except (VaultError, OSError) as e:
                report.errors.append(f"{rel}: {e}")

        self._remove_stale(set(desired), manifest, report)
        manifest["names"] = names.map
        comparable = lambda m: {k: v for k, v in m.items() if k != "updated"}  # noqa: E731
        if comparable(manifest) != comparable(self._load_manifest()) or not os.path.exists(self.manifest_path):
            manifest["updated"] = now.isoformat(timespec="seconds")
            if not atomic_write_json(self.manifest_path, manifest, indent=1, prefix="manifest_"):
                report.errors.append("could not save the export manifest")
        try:
            os.makedirs(os.path.join(self.root, "Inbox"), exist_ok=True)
        except OSError:
            pass
        return report

    # -- single note -------------------------------------------------------------
    def _compose(self, gen, tags, aliases, region, existing_fm, before, tail) -> str:
        fm = render_frontmatter(gen, tags, aliases, existing_fm)
        return f"{fm}\n{before}{region}{tail}"

    def _write_note(self, rel, gen, tags, aliases, body, force, manifest, report) -> None:
        path = self._safe_path(rel)
        region = f"{BEGIN}\n{body.rstrip()}\n{END}"
        new_sha = _sha(region)
        record = manifest["files"].get(rel)

        if not os.path.exists(path):
            text = self._compose(gen, tags, aliases, region, None, "", USER_STUB)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if not atomic_write_text(path, text, prefix="note_"):
                raise OSError("write failed")
            manifest["files"][rel] = {"body_sha": new_sha}
            report.created.append(rel)
            return

        if os.path.getsize(path) > MAX_NOTE_BYTES:
            raise OSError("existing note is unreasonably large; left untouched")
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            existing = _norm_nl(f.read())
        b = existing.find(BEGIN)
        e = existing.find(END, b + len(BEGIN)) if b >= 0 else -1
        if b < 0 or e < 0:
            report.conflicts.append(f"{rel} (generated-block markers were removed)")
            return
        cur_region = existing[b:e + len(END)]
        tail = existing[e + len(END):]
        cur_sha = _sha(cur_region)
        recorded = record.get("body_sha") if isinstance(record, dict) else None

        if cur_sha != new_sha and cur_sha != recorded and not force:
            report.conflicts.append(rel)  # you edited inside the generated block (or this note is not ours)
            return

        pre = existing[:b]
        existing_fm, remainder = split_frontmatter(pre)
        before = (remainder.strip() + "\n") if remainder.strip() else ""
        text = self._compose(gen, tags, aliases, region, existing_fm, before, tail)
        manifest["files"][rel] = {"body_sha": new_sha}
        if text == existing:
            report.unchanged.append(rel)
            return
        if not atomic_write_text(path, text, prefix="note_"):
            raise OSError("write failed")
        report.updated.append(rel)

    def _remove_stale(self, wanted: set, manifest: Dict[str, Any], report: ExportReport) -> None:
        for rel in sorted(set(manifest["files"]) - wanted):
            try:
                path = self._safe_path(rel)
            except VaultError:
                manifest["files"].pop(rel, None)
                continue
            if not os.path.exists(path):
                manifest["files"].pop(rel, None)
                continue
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    existing = _norm_nl(f.read())
                b = existing.find(BEGIN)
                e = existing.find(END, b + len(BEGIN)) if b >= 0 else -1
                untouched = b >= 0 and e >= 0 and _sha(existing[b:e + len(END)]) == manifest["files"][rel].get("body_sha")
                tail = existing[e + len(END):].strip() if e >= 0 else "x"
                if untouched and tail in ("", "## My notes"):
                    os.remove(path)
                    report.deleted.append(rel)
                    manifest["files"].pop(rel, None)
                else:
                    report.stale_kept.append(rel)
                    manifest["files"].pop(rel, None)  # stop managing it; it is yours now
            except OSError as ex:
                report.errors.append(f"{rel}: {ex}")

    # -- note builders -------------------------------------------------------------
    def _build_entities(self, desired, names, entities, facts, relations) -> None:
        by_entity: Dict[str, List[Dict[str, Any]]] = {}
        for f in facts.values():
            for eid in f.get("entities", []):
                by_entity.setdefault(eid, []).append(f)
        for eid, ent in sorted(entities.items()):
            key = f"ent:{eid}"
            mine = sorted(by_entity.get(eid, []), key=lambda f: f["created"])
            active = [f for f in mine if f["status"] == "active"]
            old = [f for f in mine if f["status"] != "active"]
            lines = [f"# {neutralise(ent['name'])}", ""]
            first = _day(ent.get("created", ""))
            lines.append(f"**{ent['type']}** · importance {ent.get('importance', 0):.2f} · "
                         f"{len(active)} active fact{'s' if len(active) != 1 else ''}"
                         + (f" · first seen {names.link('day:' + first, first)}" if f"day:{first}" in names.map else ""))
            if ent.get("aliases"):
                lines.append(f"_Also known as: {', '.join(neutralise(a) for a in ent['aliases'])}_")
            lines += ["", "## Facts", ""]
            if not active:
                lines.append("_Nothing active yet._")
            for f in active:
                members = [entities[x] for x in f["entities"] if x in entities]
                text = link_entities_in_text(f["text"], members, names, skip_id=eid)
                flags = " · ⚠ unverified source" if _untrusted(f.get("source", "")) else ""
                day = _day(f["created"])
                when = names.link(f"day:{day}", day) if f"day:{day}" in names.map else day
                lines.append(f"- {text}")
                lines.append(f"  - _{f['kind']} · learned {when} · {neutralise(f.get('source', ''))} · "
                             f"confidence {f.get('confidence', 0):.0%}{flags}_")
            rels = [r for r in relations if eid in (r["source"], r["target"]) and r["source"] in entities and r["target"] in entities]
            if rels:
                lines += ["", "## Relations", ""]
                for r in sorted(rels, key=lambda r: (r["relation"], r["source"], r["target"])):
                    if r["source"] == eid:
                        lines.append(f"- **{neutralise(r['relation'])}** → {names.link('ent:' + r['target'])}")
                    else:
                        lines.append(f"- {names.link('ent:' + r['source'])} **{neutralise(r['relation'])}** → this")
            co: Dict[str, int] = {}
            for f in active:
                for other in f["entities"]:
                    if other != eid and other in entities:
                        co[other] = co.get(other, 0) + 1
            if co:
                lines += ["", "## Related", ""]
                lines.append(" · ".join(f"{names.link('ent:' + o)} ({n})" for o, n in
                                        sorted(co.items(), key=lambda x: (-x[1], entities[x[0]]['name']))))
            if old:
                lines += ["", "## History (superseded / archived)", ""]
                lines += [f"- ~~{neutralise(f['text'])}~~ _{f['status']}_" for f in old]
            gen = {"prometheus_id": eid, "type": "entity", "entity_type": ent["type"],
                   "importance": round(float(ent.get("importance", 0)), 3), "facts": len(active),
                   "first_seen": first if _DAY_RE.match(first) else _day(ent.get("created", "")), "source": "prometheus"}
            tags = ["prometheus", "prometheus/entity", f"prometheus/{ent['type']}"]
            desired[names.rel(key)] = (gen, tags, [neutralise(a) for a in ent.get("aliases", [])], "\n".join(lines))

    def _build_timeline(self, desired, names, entities, active, days) -> None:
        for i, d in enumerate(days):
            lines = [f"# {d}", ""]
            nav = []
            if i > 0:
                nav.append("← " + names.link(f"day:{days[i - 1]}", days[i - 1]))
            if i + 1 < len(days):
                nav.append(names.link(f"day:{days[i + 1]}", days[i + 1]) + " →")
            if nav:
                lines += [" · ".join(nav), ""]
            lines += ["## Learned", ""]
            todays = sorted((f for f in active.values() if _day(f["created"]) == d), key=lambda f: f["created"])
            for f in todays:
                members = [entities[x] for x in f["entities"] if x in entities]
                lines.append(f"- {link_entities_in_text(f['text'], members, names)}")
            gen = {"type": "day", "date": d, "facts": len(todays)}
            desired[names.rel(f"day:{d}")] = (gen, ["prometheus", "prometheus/day"], [], "\n".join(lines))

    def _build_lessons(self, desired, names, entities, active) -> None:
        lessons = sorted((f for f in active.values() if f.get("kind") == "lesson"), key=lambda f: f["created"], reverse=True)
        lines = ["# Lessons", "", "What Prometheus has learned from how past tasks went.", ""]
        if not lessons:
            lines.append("_No lessons recorded yet._")
        for f in lessons:
            members = [entities[x] for x in f["entities"] if x in entities]
            lines.append(f"- {link_entities_in_text(f['text'], members, names)} _({_day(f['created'])})_")
        desired["Lessons.md"] = ({"type": "lessons", "count": len(lessons)}, ["prometheus", "prometheus/lessons"], [], "\n".join(lines))

    def _build_skills(self, desired, names, skills) -> None:
        for sk in skills:
            key = f"skill:{sk.get('name', 'skill')}"
            lines = [f"# {neutralise(sk.get('name', 'skill'))}", "", neutralise(sk.get("description", "")), "",
                     f"**Version** v{sk.get('version', 1)} · **Status** {neutralise(sk.get('status', 'unknown'))} · "
                     f"**Tests** {neutralise(sk.get('tests', 'n/a'))} · **Updated** {_day(sk.get('updated', ''))}"]
            if sk.get("history"):
                lines += ["", "## History", ""]
                lines += [f"- v{h.get('version')} · {neutralise(h.get('status', ''))} · {_day(h.get('created', ''))}" for h in sk["history"]]
            gen = {"type": "skill", "skill": sk.get("name", "skill"), "version": sk.get("version", 1),
                   "status": sk.get("status", "unknown")}
            desired[names.rel(key)] = (gen, ["prometheus", "prometheus/skill"], [], "\n".join(lines))

    def _build_task(self, desired, task_state) -> None:
        lines = ["# Current Task", ""]
        if task_state.get("goal"):
            lines += [f"**Goal:** {neutralise(task_state['goal'])}", f"**Status:** {neutralise(task_state.get('status', 'idle'))}", ""]
            steps = task_state.get("steps") or []
            if steps:
                lines += ["## Steps", ""] + [f"- [ ] {neutralise(s)}" for s in steps] + [""]
            notes = (task_state.get("notes") or [])[-20:]
            if notes:
                lines += ["## Notes", ""] + [f"- {neutralise(n.get('note', n) if isinstance(n, dict) else n)}" for n in notes]
        else:
            lines.append("_No active task._")
        desired["Current Task.md"] = ({"type": "task", "status": str(task_state.get("status", "idle"))},
                                      ["prometheus", "prometheus/task"], [], "\n".join(lines))

    def _build_index(self, desired, names, entities, active, relations, skills, days, now) -> None:
        top = sorted(entities.values(), key=lambda e: (-e.get("importance", 0), e["name"]))[:15]
        lines = ["# Prometheus — Memory Index", "",
                 f"_Last export: {now.strftime('%Y-%m-%d %H:%M')}_", "",
                 f"**{len(entities)} entities · {len(active)} active facts · {len(relations)} relations**", "",
                 "## Most important", ""]
        lines += [f"- {names.link('ent:' + e['id'], e['name'])} — {e['type']} · {e.get('importance', 0):.2f}" for e in top] or ["_Empty._"]
        lines += ["", "## Recent days", ""]
        lines += [f"- {names.link('day:' + d, d)}" for d in reversed(days[-7:])] or ["_Nothing yet._"]
        if skills:
            lines += ["", "## Skills", ""] + [f"- {names.link('skill:' + s.get('name', 'skill'), s.get('name', 'skill'))}" for s in skills]
        lines += ["", "## Browse", "",
                  f"- {names.root_link('Lessons')} · {names.root_link('Current Task')} · {names.root_link('README')}"]
        desired["Index.md"] = ({"type": "index", "entities": len(entities), "facts": len(active)}, ["prometheus", "prometheus/index"], [], "\n".join(lines))

    def _build_readme(self, desired) -> None:
        body = f"""# How this folder works

Prometheus writes this folder from its memory. **Everything between the begin/end comments in each note is regenerated** on every export. **Write your own notes below the generated block** (under *My notes*) - they are never touched, and neither are properties you add to the frontmatter.

If you edit *inside* the generated block, Prometheus leaves that note alone and tells you so.

## Dropping notes in
Put a Markdown note in `Inbox/`. Each bullet or paragraph becomes a remembered fact (wikilinks written with double square brackets, and #tags, become entities); then the file is moved to `Inbox/_processed/`. Imported facts are marked *unverified*.

## Getting a good graph
Open Graph View, then in the filters use `path:{self.root_name}/Entities` for the entity map. Colour groups by tag work well: `tag:#prometheus/project`, `tag:#prometheus/tool`, `tag:#prometheus/person`, `tag:#prometheus/skill`.
"""
        desired["README.md"] = ({"type": "readme"}, ["prometheus"], [], body)

    # -- inbox -------------------------------------------------------------------------
    def ingest_inbox(self, graph, dry_run: bool = False) -> Dict[str, Any]:
        """Read notes dropped into Inbox/ and add their content to the memory
        graph as facts. Notes are untrusted input: capped in size, treated as plain
        text, flagged as an unverified source, then moved to Inbox/_processed/."""
        inbox = os.path.join(self.root, "Inbox")
        result = {"files": 0, "facts": 0, "skipped": [], "errors": []}
        if not os.path.isdir(inbox):
            return result
        for fname in sorted(os.listdir(inbox)):
            src = os.path.join(inbox, fname)
            if not fname.lower().endswith(".md") or not os.path.isfile(src) or os.path.islink(src):
                continue
            try:
                if os.path.getsize(src) > MAX_INBOX_BYTES:
                    result["skipped"].append(f"{fname} (larger than {MAX_INBOX_BYTES // 1000} KB)")
                    continue
                with open(src, "r", encoding="utf-8", errors="replace") as f:
                    text = f.read()
                units, tags = parse_inbox_note(text)
                if dry_run:
                    result["files"] += 1
                    result["facts"] += len(units)
                    continue
                added = 0
                with graph.batch():
                    for unit in units:
                        try:
                            graph.add_fact(unit, entities=[{"name": t.replace("-", " ").replace("_", " "), "type": "topic"} for t in tags],
                                           source=f"obsidian-inbox:{safe_note_name(fname)}", confidence=0.6)
                            added += 1
                        except ValueError:
                            continue
                done_dir = os.path.join(inbox, "_processed")
                os.makedirs(done_dir, exist_ok=True)
                dest = os.path.join(done_dir, fname)
                if os.path.exists(dest):
                    dest = os.path.join(done_dir, f"{int(time.time())}_{fname}")
                shutil.move(src, dest)
                result["files"] += 1
                result["facts"] += added
            except (OSError, shutil.Error) as e:
                result["errors"].append(f"{fname}: {e}")
        return result


def _untrusted(source: str) -> bool:
    return str(source).startswith(("web:", "obsidian-inbox:", "tool:"))


def parse_inbox_note(text: str) -> Tuple[List[str], List[str]]:
    """Plain-text parse of an inbox note -> (fact texts, tags). Bullets and
    paragraphs become facts; headings, code fences, HTML comments and HTML are
    dropped. Capped at MAX_INBOX_FACTS_PER_FILE."""
    text = _norm_nl(text[:MAX_INBOX_BYTES])
    props, body = split_frontmatter(text)
    tags: List[str] = []
    if props and "tags" in props:
        tags = [t.lstrip("#") for t in _parse_list_value(props["tags"])][:10]
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    body = re.sub(r"```.*?```", "", body, flags=re.S)
    body = re.sub(r"<[^>\n]{1,200}>", "", body)
    units: List[str] = []
    paragraph: List[str] = []

    def flush():
        if paragraph:
            joined = " ".join(paragraph).strip()
            if len(joined) >= 8:
                units.append(joined)
            paragraph.clear()

    for raw in body.split("\n"):
        line = raw.strip()
        if not line:
            flush()
        elif line.startswith("#") and re.match(r"^#{1,6}\s", line):
            flush()
        elif re.match(r"^([-*+]|\d+[.)])\s+", line):
            flush()
            item = re.sub(r"^([-*+]|\d+[.)])\s+(\[[ xX]\]\s+)?", "", line).strip()
            if len(item) >= 8:
                units.append(item)
        else:
            paragraph.append(line)
    flush()
    return units[:MAX_INBOX_FACTS_PER_FILE], tags
