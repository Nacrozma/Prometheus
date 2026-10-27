"""
reflection.py — making "adaptive" mean something: Prometheus measures how its own
tools perform and turns repeated failure into lessons that feed back into prompts.

  * ToolStats   - per-tool outcome counts, rolling recent outcomes, latency and the
                  last error, persisted atomically (tool_stats.json).
  * lessons     - when a tool keeps failing the SAME way, or a skill/patch proposal is
                  rejected by a gate, a short lesson is written down. Lessons are stored in
                  the memory graph (kind="lesson"), recalled into later prompts when
                  relevant, and exported to the Obsidian vault.
  * reliability notes - a tool that has been failing recently gets a one-line caution
                  in the next prompt ("verify its arguments before retrying").

No LLM call is needed for any of this: it is bookkeeping on outcomes Prometheus already
sees. Error text can contain attacker-influenced content (a web page, a file), so
everything quoted into a lesson or a prompt is first reduced to a short, single-line,
printable excerpt.
"""

import json
import logging
import os
import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from state_io import atomic_write_json, read_json_state

logger = logging.getLogger("PrometheusReflection")

FAILURE_STATUSES = frozenset({"error", "execution_error", "unknown_tool", "nonzero_exit", "failed", "rejected"})
REFUSED_STATUSES = frozenset({"refused"})
RECENT_WINDOW = 20
UNKNOWN_TOOL_KEY = "__unknown_tool__"
MAX_TRACKED_TOOLS = 200


def classify(result: Any) -> str:
    """'success' | 'failure' | 'refused' for a tool result."""
    status = result.get("status") if isinstance(result, dict) else None
    if status in REFUSED_STATUSES:
        return "refused"
    if status in FAILURE_STATUSES:
        return "failure"
    return "success"


def excerpt(text: Any, limit: int = 120) -> str:
    """A short, single-line, printable excerpt - safe to quote in a prompt or a note."""
    s = re.sub(r"[^\x20-\x7e¡-￿]", " ", str(text if text is not None else ""))
    s = re.sub(r"\s+", " ", s).strip()
    return (s[:limit - 1] + "…") if len(s) > limit else s


def error_text(result: Any) -> str:
    if not isinstance(result, dict):
        return ""
    for key in ("message", "error", "exception", "reason"):
        if result.get(key):
            return str(result[key])
    problems = result.get("problems")
    if isinstance(problems, list) and problems:
        return str(problems[0])
    return ""


def error_signature(text: str) -> str:
    """The error with the variable parts (quoted names, numbers, hex ids) blanked, so the
    same failure on different files/values counts as the same failure."""
    s = text.lower()
    s = re.sub(r"'[^']*'|\"[^\"]*\"", "Q", s)
    s = re.sub(r"0x[0-9a-f]+|\b[0-9a-f]{8,}\b", "H", s)
    s = re.sub(r"\d+", "N", s)
    return re.sub(r"\s+", " ", s).strip()[:160]


class ToolStats:
    def __init__(self, path: str, flush_interval: float = 2.0, clock: Callable[[], float] = time.monotonic):
        self.path = path
        self.flush_interval = flush_interval
        self._clock = clock
        self._lock = threading.RLock()
        self._last_flush = float("-inf")
        self._dirty = False
        self._unsafe_to_save = False
        self.tools: Dict[str, Dict[str, Any]] = {}
        self._load()

    # -- persistence ---------------------------------------------------------------
    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            data = read_json_state(self.path)
        except json.JSONDecodeError as e:
            logger.error(f"Tool stats corrupt (moved aside), starting empty: {e}")
            return
        except OSError as e:
            logger.error(f"Tool stats unreadable; will NOT overwrite them: {e}")
            self._unsafe_to_save = True
            return
        tools = data.get("tools") if isinstance(data, dict) else None
        if isinstance(tools, dict):
            for name, t in list(tools.items())[:MAX_TRACKED_TOOLS]:
                if isinstance(name, str) and isinstance(t, dict):
                    self.tools[name] = self._normalise(t)

    @staticmethod
    def _normalise(t: Dict[str, Any]) -> Dict[str, Any]:
        def num(k):
            v = t.get(k, 0)
            return v if isinstance(v, (int, float)) and v >= 0 else 0
        recent = t.get("recent", "")
        sigs = t.get("recent_signatures", [])
        return {"calls": int(num("calls")), "successes": int(num("successes")), "failures": int(num("failures")),
                "refused": int(num("refused")), "latency_total_ms": float(num("latency_total_ms")),
                "recent": "".join(c for c in recent if c in "SFR")[-RECENT_WINDOW:] if isinstance(recent, str) else "",
                "recent_signatures": [str(s)[:160] for s in sigs][-5:] if isinstance(sigs, list) else [],
                "last_error": excerpt(t.get("last_error", ""), 200), "updated": str(t.get("updated", ""))}

    def flush(self) -> bool:
        with self._lock:
            if self._unsafe_to_save or not self._dirty:
                return not self._unsafe_to_save
            ok = atomic_write_json(self.path, {"schema_version": 1, "tools": self.tools}, indent=1, prefix="stats_")
            if ok:
                self._dirty = False
                self._last_flush = self._clock()
            return ok

    # -- recording ---------------------------------------------------------------------
    def record(self, tool: str, result: Any, latency_s: float = 0.0) -> str:
        """Record one call. Returns its classification."""
        outcome = classify(result)
        with self._lock:
            if tool not in self.tools and len(self.tools) >= MAX_TRACKED_TOOLS:
                tool = UNKNOWN_TOOL_KEY
            t = self.tools.setdefault(tool, self._normalise({}))
            t["calls"] += 1
            t["latency_total_ms"] += max(0.0, float(latency_s)) * 1000.0
            t["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            if outcome == "success":
                t["successes"] += 1
                t["recent"] = (t["recent"] + "S")[-RECENT_WINDOW:]
            elif outcome == "refused":
                t["refused"] += 1                      # the operator said no: not the tool's fault
                t["recent"] = (t["recent"] + "R")[-RECENT_WINDOW:]
            else:
                t["failures"] += 1
                text = error_text(result)
                t["last_error"] = excerpt(text, 200)
                t["recent"] = (t["recent"] + "F")[-RECENT_WINDOW:]
                t["recent_signatures"] = (t["recent_signatures"] + [error_signature(text)])[-5:]
            self._dirty = True
            if outcome == "failure" or self._clock() - self._last_flush >= self.flush_interval:
                self.flush()
        return outcome

    # -- queries -------------------------------------------------------------------------
    def failure_rate(self, tool: str, window: int = 5, min_calls: int = 3) -> Optional[float]:
        """Share of the last `window` operator-accepted calls that failed (refusals are ignored);
        None when there is not enough data."""
        with self._lock:
            t = self.tools.get(tool)
            if not t:
                return None
            recent = [c for c in t["recent"] if c != "R"][-window:]
            if len(recent) < min_calls:
                return None
            return recent.count("F") / len(recent)

    def struggling(self, threshold: float = 0.5, window: int = 5, min_calls: int = 3) -> List[Tuple[str, float, str]]:
        """Tools failing more than `threshold` of their recent calls: [(tool, rate, last_error)], worst first."""
        with self._lock:
            out = []
            for name, t in self.tools.items():
                rate = self.failure_rate(name, window, min_calls)
                if rate is not None and rate >= threshold and name != UNKNOWN_TOOL_KEY:
                    out.append((name, rate, t["last_error"]))
            return sorted(out, key=lambda x: (-x[1], x[0]))

    def summary(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            out = {}
            for name, t in sorted(self.tools.items()):
                counted = t["successes"] + t["failures"]
                out[name] = {"calls": t["calls"], "successes": t["successes"], "failures": t["failures"],
                             "refused": t["refused"],
                             "success_rate": round(t["successes"] / counted, 3) if counted else None,
                             "avg_ms": round(t["latency_total_ms"] / t["calls"], 1) if t["calls"] else 0.0,
                             "recent": t["recent"], "last_error": t["last_error"]}
            return out

    # -- lessons ---------------------------------------------------------------------------
    def lesson_for(self, tool: str) -> Optional[str]:
        """A lesson, if `tool` has just failed the same way repeatedly: >= 3 of the last 5
        calls failed, and the latest failure's signature has occurred at least twice."""
        with self._lock:
            t = self.tools.get(tool)
            if not t or tool == UNKNOWN_TOOL_KEY:
                return None
            recent = [c for c in t["recent"] if c != "R"][-5:]
            sigs = t["recent_signatures"]
            if recent.count("F") < 3 or len(sigs) < 2 or not sigs[-1] or sigs.count(sigs[-1]) < 2:
                return None
            return (f"Tool '{tool}' keeps failing the same way (\"{excerpt(t['last_error'], 100)}\"). "
                    "Check its arguments and that its target exists before retrying, and change approach after one failure.")


def lesson_from_rejection(kind: str, stage: str, problems: List[str]) -> str:
    """A lesson from a rejected skill / patch proposal: what the gate objected to."""
    reasons = "; ".join(excerpt(p, 110) for p in problems[:2]) or "no reason given"
    return f"A proposed {kind} was rejected at the {excerpt(stage, 40)} stage: {reasons}. Avoid this next time."
