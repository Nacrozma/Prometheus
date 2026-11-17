"""Conversations for the desktop app: many conversations instead of one session file.

Each conversation is one JSON file in `<data>/conversations/` (atomic writes through `state_io`). The
HUD's `session.json` is left in place; the first time the desktop opens, its messages become the first
conversation (copied, never deleted), and the current conversation is mirrored back to `session.json`
so the HUD (`gui_orb.py`) continues where the desktop left off.
"""

from __future__ import annotations

import os
import re
import time
import uuid
from typing import Any, Dict, List, Optional

from state_io import atomic_write_json, quarantine_file, read_json_state

FOLDER = "conversations"
INDEX_KEY = "current"
_ID = re.compile(r"^[0-9a-f]{32}$")
MAX_TITLE = 80


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def title_from(text: str) -> str:
    """A short title from the first user message: first line, trimmed at a word boundary."""
    line = " ".join((text or "").strip().split())
    if not line:
        return "New conversation"
    if len(line) <= 48:
        return line
    cut = line[:48].rsplit(" ", 1)[0]
    return (cut or line[:48]) + "…"


def visible(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The user and assistant messages with text: what a person sees in the conversation."""
    return [m for m in messages if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str) and m["content"].strip()]


class ConversationStore:
    def __init__(self, data_dir: str):
        self.dir = os.path.join(data_dir, FOLDER)
        os.makedirs(self.dir, exist_ok=True)
        self.state_path = os.path.join(self.dir, "_state.json")

    # ----- files -----
    def _path(self, cid: str) -> str:
        if not _ID.match(cid or ""):
            raise ValueError("not a conversation id")
        return os.path.join(self.dir, f"{cid}.json")

    def _read(self, path: str) -> Optional[Dict[str, Any]]:
        try:
            data = read_json_state(path)
        except Exception:
            quarantine_file(path)
            return None
        return data if isinstance(data, dict) and isinstance(data.get("messages"), list) else None

    # ----- queries -----
    def list(self, query: str = "") -> List[Dict[str, Any]]:
        """Summaries, most recently updated first. `query` matches titles and message text."""
        q = query.lower().strip()
        out = []
        for name in os.listdir(self.dir):
            if not name.endswith(".json") or name.startswith("_"):
                continue
            c = self._read(os.path.join(self.dir, name))
            if c is None:
                continue
            shown = visible(c["messages"])
            if q and q not in c.get("title", "").lower() and not any(q in m["content"].lower() for m in shown):
                continue
            last = shown[-1]["content"] if shown else ""
            out.append({"id": c["id"], "title": c.get("title") or "New conversation", "created": c.get("created", ""), "updated": c.get("updated", ""), "messages": len(shown), "preview": " ".join(last.split())[:120]})
        out.sort(key=lambda c: c["updated"], reverse=True)
        return out

    def get(self, cid: str) -> Optional[Dict[str, Any]]:
        try:
            path = self._path(cid)
        except ValueError:
            return None
        return self._read(path) if os.path.exists(path) else None

    # ----- changes -----
    def create(self, messages: Optional[List[Dict[str, Any]]] = None, title: str = "") -> Dict[str, Any]:
        msgs = list(messages or [])
        first = next((m["content"] for m in visible(msgs) if m["role"] == "user"), "")
        c = {"id": uuid.uuid4().hex, "title": (title or title_from(first))[:MAX_TITLE], "created": _now(), "updated": _now(), "messages": msgs, "auto_title": not title}
        self.save(c)
        self.set_current(c["id"])
        return c

    def save(self, c: Dict[str, Any]) -> bool:
        c["updated"] = _now()
        if c.get("auto_title", True):
            first = next((m["content"] for m in visible(c["messages"]) if m["role"] == "user"), "")
            if first:
                c["title"] = title_from(first)
        return atomic_write_json(self._path(c["id"]), c)

    def rename(self, cid: str, title: str) -> bool:
        c = self.get(cid)
        title = " ".join((title or "").split())[:MAX_TITLE]
        if c is None or not title:
            return False
        c["title"], c["auto_title"] = title, False
        return self.save(c)

    def delete(self, cid: str) -> bool:
        try:
            path = self._path(cid)
        except ValueError:
            return False
        if not os.path.exists(path):
            return False
        os.remove(path)
        if self.current_id() == cid:
            self.set_current("")
        return True

    # ----- which one is open -----
    def current_id(self) -> str:
        try:
            data = read_json_state(self.state_path) if os.path.exists(self.state_path) else {}
        except Exception:
            data = {}
        cid = data.get(INDEX_KEY, "") if isinstance(data, dict) else ""
        return cid if self.get(cid) else ""

    def set_current(self, cid: str) -> None:
        atomic_write_json(self.state_path, {INDEX_KEY: cid})

    def open_current(self, legacy_messages: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """The conversation to show at start: the last open one; else the HUD session imported once;
        else a new one."""
        cid = self.current_id()
        if cid:
            return self.get(cid)  # type: ignore[return-value]
        existing = self.list()
        if existing:
            c = self.get(existing[0]["id"])
            if c is not None:
                self.set_current(c["id"])
                return c
        return self.create(legacy_messages if legacy_messages and visible(legacy_messages) else [])
