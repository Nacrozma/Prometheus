"""Universal search: one query across the sources the desktop app really has access to.

Sources: conversations (titles and text), memory (the graph's own recall), reminders, workspace file
names (bounded walk inside the workspace only, hidden and dependency folders skipped) and recent tool
activity (the audit log). Nothing is searched that the app could not already show. Results are plain
dicts so the palette and tests can use them without Qt.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "env", "dist", "build", ".mypy_cache", ".pytest_cache", "target"}
MAX_WALK = 5000
MAX_DEPTH = 6


def _files(root: str, q: str, limit: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not root or not os.path.isdir(root):
        return out
    root = os.path.realpath(root)
    seen = 0
    for base, dirs, files in os.walk(root):
        depth = os.path.relpath(base, root).count(os.sep)
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".") and depth < MAX_DEPTH]
        for name in files:
            seen += 1
            if seen > MAX_WALK or len(out) >= limit:
                return out
            if name.startswith(".") or q not in name.lower():
                continue
            path = os.path.join(base, name)
            # never follow a link out of the workspace
            if os.path.islink(path) and not os.path.realpath(path).startswith(root + os.sep):
                continue
            out.append({"kind": "file", "title": name, "detail": os.path.relpath(path, root), "target": path})
    return out


def search(core, conversations, query: str, workspace: str = "", limit: int = 8) -> List[Dict[str, Any]]:
    q = (query or "").strip().lower()
    if len(q) < 2:
        return []
    results: List[Dict[str, Any]] = []

    def safe(fn) -> Iterable[Dict[str, Any]]:
        try:
            return fn()
        except Exception:  # one unavailable source never hides the others
            return []

    if conversations is not None:
        results += safe(lambda: [{"kind": "conversation", "title": c["title"], "detail": c["preview"] or f"{c['messages']} messages", "target": c["id"]} for c in conversations.list(q)[:limit]])
    results += safe(lambda: [{"kind": "memory", "title": f.get("text", "")[:90], "detail": f"{f.get('kind', 'fact')} · {f.get('source', '')}".strip(" ·"), "target": f.get("id", "")} for f in core.p.memory_graph.recall(q, top_k=limit, touch=False) if f.get("text")])
    results += safe(lambda: [{"kind": "reminder", "title": j.get("text", ""), "detail": f"{j.get('status', '')} · next {str(j.get('next_fire', ''))[:16].replace('T', ' ')}", "target": j.get("id", "")} for j in core.scheduled() if q in str(j.get("text", "")).lower()][:limit])
    results += safe(lambda: _files(workspace, q, limit))
    results += safe(lambda: [{"kind": "activity", "title": f"{e.get('tool', '')} · {e.get('outcome', '')}", "detail": e.get("ts", ""), "target": str(e.get("seq", ""))} for e in reversed(core.audit_tail(300)) if q in str(e.get("tool", "")).lower() or q in str(e.get("outcome", "")).lower()][:limit])
    return results
