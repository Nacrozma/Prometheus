"""
gui_session.py — session persistence and message-history hygiene for the HUD.

Pure Python (no Qt, no network), so everything here is unit-testable headless.

Why this exists: the GUI used to write session.json straight into the live file
(a crash mid-write left truncated JSON, and the next launch silently started with
an empty history), kept the whole conversation forever (every turn re-sent all of
it), and could persist an assistant message whose tool calls never got results
(Stop pressed mid-tool-loop) - after which every later request was rejected by the
provider. These helpers fix those three things:

  * atomic_write_json / quarantine_file - temp file + fsync + os.replace; a file
    that fails to parse is moved aside instead of being overwritten.
  * sanitize_messages - repairs any history so every tool call has its result and
    no tool result is orphaned.
  * trim_messages - bounds history length without cutting a tool exchange in half.
"""

import json
import logging
import os
from typing import Any, Dict, List

from state_io import atomic_write_json, quarantine_file  # shared crash-safe helpers (re-exported here)

logger = logging.getLogger("PrometheusGUI")

VALID_ROLES = {"user", "assistant", "tool", "system"}
TOOL_RESULT_CHAR_CAP = 6000     # one giant tool result must not evict the rest of the context
DEFAULT_MAX_MESSAGES = 80       # roughly 40 turns


def cap_text(text: str, cap: int = TOOL_RESULT_CHAR_CAP) -> str:
    if len(text) <= cap:
        return text
    return text[:cap] + f"\n... [truncated {len(text) - cap} chars]"


def sanitize_messages(messages: Any) -> List[Dict[str, Any]]:
    """Return a copy of `messages` that is valid to send to a chat-completions API:
      * non-dict entries and unknown roles are dropped;
      * an assistant message's tool_calls are kept only if each call has a matching
        tool result directly after it (calls without one are removed, and an
        assistant message left with no content and no calls is dropped);
      * tool results that don't belong to such a message are dropped."""
    if not isinstance(messages, list):
        return []
    out: List[Dict[str, Any]] = []
    i, n = 0, len(messages)
    while i < n:
        m = messages[i]
        i += 1
        if not isinstance(m, dict) or m.get("role") not in VALID_ROLES:
            continue
        role = m["role"]
        if role == "tool":
            continue  # orphan - tool results are only kept when attached to their assistant message below
        if role == "assistant" and isinstance(m.get("tool_calls"), list) and m["tool_calls"]:
            calls = [c for c in m["tool_calls"] if isinstance(c, dict) and c.get("id")]
            responses: List[Dict[str, Any]] = []
            while i < n and isinstance(messages[i], dict) and messages[i].get("role") == "tool":
                responses.append(messages[i])
                i += 1
            answered = {r.get("tool_call_id") for r in responses}
            kept_calls = [c for c in calls if c["id"] in answered]
            kept_ids = {c["id"] for c in kept_calls}
            kept_responses = [r for r in responses if r.get("tool_call_id") in kept_ids]
            msg = dict(m)
            if kept_calls:
                msg["tool_calls"] = kept_calls
                out.append(msg)
                out.extend(kept_responses)
            else:
                msg.pop("tool_calls", None)
                if str(msg.get("content") or "").strip():
                    out.append(msg)
            continue
        out.append(m)
    return out


def trim_messages(messages: List[Dict[str, Any]], max_messages: int = DEFAULT_MAX_MESSAGES) -> int:
    """Drop the oldest messages IN PLACE so at most ~max_messages remain, always
    cutting at a user message so a tool call is never separated from its result.
    Returns how many messages were removed (0 if there was no safe cut point)."""
    if max_messages < 2 or len(messages) <= max_messages:
        return 0
    cut = len(messages) - max_messages
    while cut < len(messages) and messages[cut].get("role") != "user":
        cut += 1
    if cut >= len(messages):
        return 0
    del messages[:cut]
    return cut


def load_session(path: str) -> List[Dict[str, Any]]:
    """Load and repair the saved conversation. A file that is not valid JSON, or
    not a list, is quarantined (never silently overwritten) and [] is returned."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except ValueError:  # JSONDecodeError / UnicodeDecodeError
        quarantine_file(path)
        return []
    except OSError as e:
        logger.error(f"Session read failed: {e}")
        return []
    if not isinstance(data, list):
        quarantine_file(path)
        return []
    return sanitize_messages(data)


def save_session(path: str, messages: List[Dict[str, Any]]) -> bool:
    return atomic_write_json(path, messages)
