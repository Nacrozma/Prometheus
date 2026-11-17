"""The owner's own memory actions from the desktop: add, correct, forget, confirm.

These are the owner acting directly (not the model), so they do not go through an approval card; each
one is recorded in the hash-chained audit log like any tool call. Forgetting is meaningful: the fact is
archived in the graph (so it is no longer recalled or put into context) and its text is removed from the
flat memory file and the retrieval store, where older copies would otherwise still surface.

Provenance labels:
* "You"        source "operator" or "desktop": written or confirmed by the owner
* "Prometheus" source "assistant": suggested by the model during a conversation (not yet confirmed)
* "Unverified" sources starting web:, obsidian-inbox:, tool: (imported or derived from outside text)
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

KINDS = ("fact", "preference", "decision", "lesson")
OWNER_SOURCES = ("operator", "desktop")


def provenance(fact: Dict[str, Any], is_untrusted) -> str:
    src = str(fact.get("source", ""))
    if is_untrusted(src):
        return "Unverified"
    if src in OWNER_SOURCES or fact.get("confirmed"):
        return "You" if src in OWNER_SOURCES else "Confirmed by you"
    if src == "assistant":
        return "Prometheus (suggested)"
    return src or "Unknown"


def _words(s: str) -> set:
    return set(re.findall(r"[a-z0-9]+", s.lower()))


class MemoryOps:
    def __init__(self, core):
        self.core = core
        self.p = core.p
        self.g = core.p.memory_graph

    # ----- reading -----
    def rows(self, kinds: Optional[List[str]] = None, query: str = "", limit: int = 500) -> List[Dict[str, Any]]:
        """Active facts with provenance and effective importance, newest first (or by relevance)."""
        snap = self.g.export_snapshot()
        facts = snap["facts"]
        if query.strip():
            ids = [r.get("id") or (r.get("fact") or {}).get("id") for r in self.g.recall(query, top_k=50, touch=False)]
            order = [facts[i] for i in ids if i in facts]
        else:
            order = sorted(facts.values(), key=lambda f: f.get("updated", ""), reverse=True)
        out = []
        for f in order:
            if f.get("status") != "active" or (kinds and f.get("kind") not in kinds):
                continue
            ents = [snap["entities"][e]["name"] for e in f.get("entities", []) if e in snap["entities"]]
            out.append({**{k: f.get(k) for k in ("id", "text", "kind", "source", "created", "updated", "confidence", "pinned", "confirmed")}, "importance": f.get("effective_importance", f.get("importance", 0)), "entities": ents, "provenance": provenance(f, self.core.is_untrusted)})
            if len(out) >= limit:
                break
        return out

    def similar(self, text: str, exclude: str = "") -> List[Dict[str, Any]]:
        """Existing active facts that overlap strongly with `text` (possible duplicates or conflicts)."""
        mine = _words(text)
        if not mine:
            return []
        out = []
        for r in self.g.recall(text, top_k=8, touch=False):
            f = r if "text" in r else r.get("fact", {})
            if not f or f.get("id") == exclude:
                continue
            theirs = _words(f.get("text", ""))
            overlap = len(mine & theirs) / max(1, len(mine | theirs))
            if overlap >= 0.45:
                out.append({"id": f.get("id"), "text": f.get("text"), "overlap": round(overlap, 2), "same": f.get("text", "").strip().lower() == text.strip().lower()})
        return out

    # ----- changes (each one audited) -----
    def _audit(self, action: str, detail: Dict[str, Any], outcome: str = "success") -> None:
        self.p.audit_log.record(f"desktop.memory_{action}", detail, outcome, "owner action in the desktop app")

    def add(self, text: str, kind: str = "fact", importance: float = 0.6) -> Dict[str, Any]:
        text = " ".join((text or "").split())
        if len(text) < 3:
            return {"status": "error", "message": "Write the fact in a few words."}
        kind = kind if kind in KINDS else "fact"
        importance = max(0.0, min(1.0, float(importance)))
        self.p.update_memory_fact(text, importance=importance, kind=kind, source="operator")
        self._audit("add", {"kind": kind, "chars": len(text)})
        return {"status": "success"}

    def _remove_copies(self, text: str) -> None:
        """Remove a fact's text from the flat memory file and the retrieval store."""
        with self.p._STATE_LOCK:
            mem = self.p.load_memory(self.p.MEMORY_FILE)
            facts = mem.get("facts", [])
            if text in facts:
                mem["facts"] = [f for f in facts if f != text]
                self.p.save_memory_data(mem, self.p.MEMORY_FILE)
            store = self.p.rag_store
            before = len(store.documents)
            store.documents = [d for d in store.documents if d.get("content") != f"Memory Fact: {text}"]
            if len(store.documents) != before:
                store.save()

    def forget(self, fact_id: str) -> Dict[str, Any]:
        f = self.g.get_fact(fact_id)
        if not f or f.get("status") != "active":
            return {"status": "error", "message": "That memory is not active."}
        self.g.archive(fact_id)
        self._remove_copies(f["text"])
        self._audit("forget", {"fact_id": fact_id, "kind": f.get("kind")})
        return {"status": "success"}

    def correct(self, fact_id: str, new_text: str) -> Dict[str, Any]:
        f = self.g.get_fact(fact_id)
        new_text = " ".join((new_text or "").split())
        if not f or f.get("status") != "active":
            return {"status": "error", "message": "That memory is not active."}
        if len(new_text) < 3 or new_text == f["text"]:
            return {"status": "error", "message": "Write the corrected fact."}
        self.p.update_memory_fact(new_text, importance=max(0.6, float(f.get("importance", 0.5))), kind=f.get("kind", "fact"), source="operator")
        new = next((r for r in self.g.recall(new_text, top_k=5, touch=False) if (r.get("text") or (r.get("fact") or {}).get("text")) == new_text), None)
        new_id = (new or {}).get("id") or ((new or {}).get("fact") or {}).get("id")
        if new_id and new_id != fact_id:
            self.g.supersede(fact_id, new_id)
        else:
            self.g.archive(fact_id)
        self._remove_copies(f["text"])
        self._audit("correct", {"fact_id": fact_id, "new_fact_id": new_id, "kind": f.get("kind")})
        return {"status": "success", "new_id": new_id}

    def confirm(self, fact_id: str) -> Dict[str, Any]:
        ok = self.g.confirm(fact_id)
        if ok:
            self._audit("confirm", {"fact_id": fact_id})
        return {"status": "success" if ok else "error"}
