"""ORBIT for Prometheus: sessions, structured plans with versions, workflows and their execution states.

Plain Python (no Qt), so every rule here is unit-tested. Storage: one JSON file per session in
`<data>/orbit/`, written atomically through `state_io`, validated on load (a damaged file is quarantined,
never half-read). Nothing here runs anything: execution is driven by the ORBIT page through the
existing worker, tools and approval gate; this module only records what really happened.

Vocabulary
* A **plan** is what should happen: objective, phases, tasks, dependencies, assumptions, open
  questions, risks. Every change creates a new version (author: you or Prometheus, and why).
  Plans proposed by Prometheus are drafts until you approve a version.
* A **workflow** is how it will be done: one node per task, each mapped to a real capability
  (`OPERATIONS`). Nodes move through `NODE_STATES` only by recorded events (`TRANSITIONS`).
* **Autonomy** decides whether a node may start without you; it never changes the tool approval gate:
  tools with real-world effects still ask every time.
"""

from __future__ import annotations

import copy
import json
import os
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from state_io import atomic_write_json, quarantine_file, read_json_state

SCHEMA = 1
FOLDER = "orbit"
_ID = re.compile(r"^[0-9a-f]{32}$")
MAX_TASKS = 80
MAX_TEXT = 300

# ----- workflow vocabulary ---------------------------------------------------------------------------

NODE_STATES = ("draft", "ready", "waiting", "awaiting_approval", "running", "completed", "failed", "paused", "cancelled", "blocked")
TRANSITIONS = {
    "draft": {"ready", "waiting", "cancelled"},
    "waiting": {"ready", "cancelled", "blocked"},
    "ready": {"awaiting_approval", "running", "paused", "cancelled", "waiting"},
    "awaiting_approval": {"running", "cancelled", "paused", "ready"},
    "running": {"completed", "failed", "paused", "cancelled", "awaiting_approval"},
    "paused": {"ready", "cancelled"},
    "failed": {"ready", "cancelled"},
    "blocked": {"ready", "cancelled"},
    "completed": set(),
    "cancelled": {"ready"},
}

#: Real capabilities a node can map to. `runs` says what actually executes it.
OPERATIONS: Dict[str, Dict[str, str]] = {
    "assistant": {"name": "Prometheus works on it", "runs": "a Prometheus turn with this task; any tool with real-world effects still asks you", "category": "think"},
    "forge:architect": {"name": "Forge · Architect", "runs": "an Architect turn (read-only: writes and runs are refused)", "category": "read"},
    "forge:builder": {"name": "Forge · Builder", "runs": "a Builder turn (each change asks you)", "category": "change"},
    "forge:debugger": {"name": "Forge · Debugger", "runs": "a Debugger turn (each change asks you)", "category": "change"},
    "forge:reconstructor": {"name": "Forge · Reconstructor", "runs": "a Reconstructor turn (new files only)", "category": "change"},
    "reminder": {"name": "Schedule a reminder", "runs": "the schedule_task tool", "category": "organise"},
    "manual": {"name": "You do it", "runs": "nothing automatic: you mark it done", "category": "manual"},
}

AUTONOMY = ("approval_first", "balanced", "advanced")
AUTONOMY_TEXT = {
    "approval_first": "Every step waits for your go-ahead. Tools with real-world effects also ask.",
    "balanced": "Thinking, reading and organising steps start on their own; steps that change files wait for you. Tools with real-world effects always ask.",
    "advanced": "The step categories you choose start on their own. Tools with real-world effects still ask every time; nothing irreversible runs unasked.",
}
CATEGORIES = ("think", "read", "organise", "change")


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _clip(s: Any, n: int = MAX_TEXT) -> str:
    return " ".join(str(s or "").split())[:n]


def _tid() -> str:
    return uuid.uuid4().hex[:10]


# ----- plans ----------------------------------------------------------------------------------------

def empty_plan(title: str = "", objective: str = "") -> Dict[str, Any]:
    return {"title": _clip(title, 120) or "Untitled plan", "objective": _clip(objective), "outcome": "", "scope": "", "phases": [], "tasks": [], "deps": [], "assumptions": [], "questions": [], "risks": []}


def normalise_plan(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and clean a plan (from Prometheus or from the file): bounded text, known phases, unique ids,
    dependencies only between existing tasks and never forming a cycle."""
    p = empty_plan(raw.get("title", ""), raw.get("objective", ""))
    for k in ("outcome", "scope"):
        p[k] = _clip(raw.get(k, ""))
    for k in ("assumptions", "questions", "risks"):
        p[k] = [_clip(x) for x in (raw.get(k) or []) if _clip(x)][:20]
    seen = set()
    for ph in raw.get("phases") or []:
        name = _clip(ph.get("name") if isinstance(ph, dict) else ph, 80)
        if name and name.lower() not in seen:
            seen.add(name.lower())
            p["phases"].append(name)
    ids = set()
    for t in (raw.get("tasks") or [])[:MAX_TASKS]:
        if not isinstance(t, dict):
            continue
        title = _clip(t.get("title") or t.get("name"), 160)
        if not title:
            continue
        tid = str(t.get("id") or "")
        tid = tid if re.fullmatch(r"[A-Za-z0-9_-]{1,24}", tid) and tid not in ids else _tid()
        ids.add(tid)
        phase = _clip(t.get("phase"), 80)
        if phase and phase.lower() not in seen:
            seen.add(phase.lower())
            p["phases"].append(phase)
        if not phase:
            phase = p["phases"][0] if p["phases"] else "Plan"
            if "Plan" == phase and "plan" not in seen:
                seen.add("plan")
                p["phases"].append("Plan")
        prio = str(t.get("priority") or "normal").lower()
        op = str(t.get("operation") or "assistant")
        p["tasks"].append({
            "id": tid, "title": title, "phase": phase, "detail": _clip(t.get("detail") or t.get("description"), 600),
            "priority": prio if prio in ("high", "normal", "low") else "normal",
            "estimate": _clip(t.get("estimate"), 40), "status": "proposed" if t.get("status") != "confirmed" else "confirmed",
            "operation": op if op in OPERATIONS else "assistant",
        })
    by_title = {t["title"].lower(): t["id"] for t in p["tasks"]}
    deps: List[Tuple[str, str]] = []
    for d in raw.get("deps") or raw.get("dependencies") or []:
        if isinstance(d, dict):
            a, b = d.get("from") or d.get("before"), d.get("to") or d.get("after")
        elif isinstance(d, (list, tuple)) and len(d) == 2:
            a, b = d
        else:
            continue
        a = a if a in ids else by_title.get(str(a).lower())
        b = b if b in ids else by_title.get(str(b).lower())
        if a and b and a != b and (a, b) not in deps and not _creates_cycle(deps, a, b):
            deps.append((a, b))
    p["deps"] = [{"from": a, "to": b} for a, b in deps]
    return p


def _creates_cycle(deps: List[Tuple[str, str]], a: str, b: str) -> bool:
    """True if adding a→b (a before b) would create a cycle."""
    graph: Dict[str, List[str]] = {}
    for x, y in deps:
        graph.setdefault(x, []).append(y)
    stack, seen = [b], set()
    while stack:
        n = stack.pop()
        if n == a:
            return True
        if n in seen:
            continue
        seen.add(n)
        stack.extend(graph.get(n, []))
    return False


def task(plan: Dict[str, Any], ref: str) -> Optional[Dict[str, Any]]:
    """A task by id, exact title, or a unique title fragment (case-insensitive)."""
    ref_l = (ref or "").strip().lower().strip(" .\"'")
    if not ref_l:
        return None
    for t in plan["tasks"]:
        if t["id"] == ref or t["title"].lower() == ref_l:
            return t
    hits = [t for t in plan["tasks"] if ref_l in t["title"].lower()]
    return hits[0] if len(hits) == 1 else None


class PlanError(ValueError):
    pass


def edit(plan: Dict[str, Any], op: str, **a) -> Tuple[Dict[str, Any], str]:
    """Apply one edit; returns (new plan, plain description). Raises PlanError with a reason."""
    p = copy.deepcopy(plan)
    if op == "add_task":
        title = _clip(a.get("title"), 160)
        if not title:
            raise PlanError("A task needs a title.")
        phase = _clip(a.get("phase"), 80) or (p["phases"][-1] if p["phases"] else "Plan")
        if phase not in p["phases"]:
            p["phases"].append(phase)
        if len(p["tasks"]) >= MAX_TASKS:
            raise PlanError("This plan already has the maximum number of tasks.")
        p["tasks"].append({"id": _tid(), "title": title, "phase": phase, "detail": _clip(a.get("detail"), 600), "priority": "normal", "estimate": "", "status": "confirmed", "operation": a.get("operation") if a.get("operation") in OPERATIONS else "assistant"})
        return p, f"Added “{title}” to {phase}."
    t = task(p, a.get("ref", "")) if a.get("ref") is not None else None
    if op in ("remove_task", "rename_task", "set_priority", "move_to_phase", "set_operation", "move_before", "confirm_task") and t is None:
        raise PlanError(f"No single task matches “{a.get('ref', '')}”.")
    if op == "remove_task":
        p["tasks"] = [x for x in p["tasks"] if x["id"] != t["id"]]
        p["deps"] = [d for d in p["deps"] if t["id"] not in (d["from"], d["to"])]
        return p, f"Removed “{t['title']}”."
    if op == "rename_task":
        new = _clip(a.get("title"), 160)
        if not new:
            raise PlanError("Give the new name.")
        old, t["title"] = t["title"], new
        return p, f"Renamed “{old}” to “{new}”."
    if op == "set_priority":
        prio = str(a.get("priority", "")).lower()
        if prio not in ("high", "normal", "low"):
            raise PlanError("Priority is high, normal or low.")
        t["priority"] = prio
        return p, f"“{t['title']}” is now {prio} priority."
    if op == "set_operation":
        if a.get("operation") not in OPERATIONS:
            raise PlanError("Unknown operation.")
        t["operation"] = a["operation"]
        return p, f"“{t['title']}” will be done by: {OPERATIONS[a['operation']]['name']}."
    if op == "confirm_task":
        t["status"] = "confirmed"
        return p, f"Confirmed “{t['title']}”."
    if op == "move_to_phase":
        phase = _clip(a.get("phase"), 80)
        if not phase:
            raise PlanError("Name the phase.")
        if phase not in p["phases"]:
            match = [x for x in p["phases"] if x.lower() == phase.lower()]
            phase = match[0] if match else phase
            if phase not in p["phases"]:
                p["phases"].append(phase)
        t["phase"] = phase
        return p, f"Moved “{t['title']}” to {phase}."
    if op == "move_before":
        other = task(p, a.get("other", ""))
        if other is None:
            raise PlanError(f"No single task matches “{a.get('other', '')}”.")
        tasks = [x for x in p["tasks"] if x["id"] != t["id"]]
        i = next(i for i, x in enumerate(tasks) if x["id"] == other["id"])
        t["phase"] = other["phase"]
        tasks.insert(i, t)
        p["tasks"] = tasks
        return p, f"Moved “{t['title']}” before “{other['title']}”."
    if op == "move_phase_before":
        a_ph, b_ph = _match_phase(p, a.get("phase")), _match_phase(p, a.get("other"))
        if not a_ph or not b_ph or a_ph == b_ph:
            raise PlanError("Name two different phases of this plan.")
        p["phases"].remove(a_ph)
        p["phases"].insert(p["phases"].index(b_ph), a_ph)
        return p, f"{a_ph} now comes before {b_ph}."
    if op in ("add_dep", "remove_dep"):
        x, y = task(p, a.get("before", "")), task(p, a.get("after", ""))
        if not x or not y or x["id"] == y["id"]:
            raise PlanError("Name two different tasks.")
        pair = {"from": x["id"], "to": y["id"]}
        if op == "remove_dep":
            if pair not in p["deps"]:
                raise PlanError("Those tasks are not linked.")
            p["deps"].remove(pair)
            return p, f"“{y['title']}” no longer waits for “{x['title']}”."
        if pair in p["deps"]:
            raise PlanError("They are already linked.")
        if _creates_cycle([(d["from"], d["to"]) for d in p["deps"]], x["id"], y["id"]):
            raise PlanError("That would make the tasks wait for each other in a loop.")
        p["deps"].append(pair)
        return p, f"“{y['title']}” now waits for “{x['title']}”."
    if op == "set_field":
        field = a.get("field")
        if field not in ("title", "objective", "outcome", "scope"):
            raise PlanError("Unknown field.")
        p[field] = _clip(a.get("value"), 120 if field == "title" else MAX_TEXT)
        return p, f"Changed the {field}."
    raise PlanError(f"Unknown edit “{op}”.")


def _match_phase(p: Dict[str, Any], name: Any) -> Optional[str]:
    n = _clip(name, 80).lower()
    exact = [x for x in p["phases"] if x.lower() == n]
    if exact:
        return exact[0]
    part = [x for x in p["phases"] if n and n in x.lower()]
    return part[0] if len(part) == 1 else None


# ----- plans from Prometheus's replies ----------------------------------------------------------------

PLAN_FENCE = re.compile(r"```orbit-plan\s*(\{.*?\})\s*```", re.S)
INSTRUCTION = (
    "[ORBIT planning context — not from the user] You are working with the user in ORBIT. Talk naturally. "
    "Whenever you propose or change a plan, append ONE fenced block ```orbit-plan {json} ``` with keys: title, "
    "objective, outcome, phases (list of names), tasks (list of {id, title, phase, detail, priority high|normal|low, "
    "estimate (only if you have a basis, else empty)}), deps (list of {from: task id, to: task id} meaning "
    "'from' must finish before 'to'), assumptions, questions (what you still need to know), risks. Never invent "
    "facts or confirmed requirements; put unknowns in questions. Keep task ids stable between versions.\n"
)


def extract_plan(text: str) -> Optional[Dict[str, Any]]:
    """The last complete orbit-plan block in a reply, normalised; None if there is none or it is invalid."""
    blocks = PLAN_FENCE.findall(text or "")
    for raw in reversed(blocks):
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        if isinstance(data, dict):
            return normalise_plan(data)
    return None


def partial_plan(text: str) -> Dict[str, List[str]]:
    """While a reply streams: the phase names and task titles that have fully arrived so far, so the plan can
    appear progressively. Shown as provisional; replaced by the complete block when it arrives."""
    i = (text or "").rfind("```orbit-plan")
    if i < 0:
        return {"phases": [], "tasks": []}
    body = text[i:]
    phases = re.findall(r'"phases"\s*:\s*\[([^\]]*)\]', body)
    names = re.findall(r'"([^"]{1,80})"', phases[0]) if phases else []
    titles = re.findall(r'"title"\s*:\s*"([^"]{1,160})"\s*,\s*"phase"', body)
    return {"phases": names[:20], "tasks": titles[:MAX_TASKS]}


def strip_plan_blocks(text: str) -> str:
    """The reply without plan blocks (for the transcript and for speech)."""
    t = PLAN_FENCE.sub("", text or "")
    j = t.find("```orbit-plan")
    return (t[:j] if j >= 0 else t).strip()


# ----- spoken / typed plan commands (handled locally, no model needed) --------------------------------

_CMDS = [
    (re.compile(r"^(?:please\s+)?move (?:the )?(?:phase )?(.+?) (?:phase )?before (?:the )?(?:phase )?(.+?)(?: phase)?$", re.I), "move_before"),
    (re.compile(r"^(?:please\s+)?(?:add|create) (?:a )?task (?:called |named )?(.+?)(?: (?:to|in|under) (?:the )?(.+?)(?: phase)?)?$", re.I), "add_task"),
    (re.compile(r"^(?:please\s+)?(?:remove|delete|drop) (?:the )?task (.+)$", re.I), "remove_task"),
    (re.compile(r"^(?:please\s+)?rename (?:the )?task (.+?) to (.+)$", re.I), "rename_task"),
    (re.compile(r"^(?:please\s+)?make (.+?) (high|normal|low) priority$", re.I), "set_priority"),
    (re.compile(r"^(.+?) (?:must|should) (?:come )?after (.+)$", re.I), "add_dep_after"),
    (re.compile(r"^(?:please\s+)?undo(?: that)?$", re.I), "undo"),
]
CONTROL_WORDS = {"stop": "stop_speaking", "wait": "stop_speaking", "hold on": "stop_speaking", "pause": "pause", "pause the workflow": "pause", "resume": "resume", "continue": "resume", "cancel the workflow": "cancel"}


def parse_command(text: str, plan: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """A direct plan edit or control word in what the user said or typed; None means 'send to Prometheus'."""
    t = " ".join((text or "").strip().rstrip(".!?").split())
    low = t.lower()
    if low in CONTROL_WORDS:
        return {"control": CONTROL_WORDS[low]}
    if not plan:
        return None
    for rx, kind in _CMDS:
        m = rx.match(t)
        if not m:
            continue
        if kind == "move_before":
            a_ph, b_ph = _match_phase(plan, m.group(1)), _match_phase(plan, m.group(2))
            if a_ph and b_ph and a_ph != b_ph:
                return {"op": "move_phase_before", "phase": a_ph, "other": b_ph}
            if task(plan, m.group(1)) and task(plan, m.group(2)):
                return {"op": "move_before", "ref": m.group(1), "other": m.group(2)}
            return None
        if kind == "add_task":
            return {"op": "add_task", "title": m.group(1), "phase": m.group(2) or ""}
        if kind == "remove_task":
            return {"op": "remove_task", "ref": m.group(1)}
        if kind == "rename_task":
            return {"op": "rename_task", "ref": m.group(1), "title": m.group(2)}
        if kind == "set_priority":
            return {"op": "set_priority", "ref": m.group(1), "priority": m.group(2).lower()} if task(plan, m.group(1)) else None
        if kind == "add_dep_after":
            return {"op": "add_dep", "before": m.group(2), "after": m.group(1)} if task(plan, m.group(1)) and task(plan, m.group(2)) else None
        if kind == "undo":
            return {"undo": True}
    return None


# ----- workflows --------------------------------------------------------------------------------------

def topo_order(plan: Dict[str, Any]) -> List[str]:
    """Task ids in an order that respects dependencies, keeping phase order and list order otherwise."""
    rank = {ph: i for i, ph in enumerate(plan["phases"])}
    tasks = sorted(plan["tasks"], key=lambda t: (rank.get(t["phase"], 99), plan["tasks"].index(t)))
    before = {t["id"]: {d["from"] for d in plan["deps"] if d["to"] == t["id"]} for t in tasks}
    out: List[str] = []
    while len(out) < len(tasks):
        progressed = False
        for t in tasks:
            if t["id"] not in out and before[t["id"]] <= set(out):
                out.append(t["id"])
                progressed = True
                break
        if not progressed:  # cannot happen with cycle-free deps; kept as a guard
            out += [t["id"] for t in tasks if t["id"] not in out]
    return out


def make_workflow(plan: Dict[str, Any], plan_version: int, autonomy: str = "approval_first", allowed: Optional[List[str]] = None) -> Dict[str, Any]:
    order = topo_order(plan)
    by_id = {t["id"]: t for t in plan["tasks"]}
    nodes = []
    for tid in order:
        t = by_id[tid]
        deps = [d["from"] for d in plan["deps"] if d["to"] == tid]
        nodes.append({"id": tid, "title": t["title"], "detail": t.get("detail", ""), "phase": t["phase"], "operation": t.get("operation", "assistant"), "deps": deps, "status": "waiting" if deps else "ready", "conversation_id": "", "output": "", "error": "", "history": [{"ts": now(), "event": "created", "status": "waiting" if deps else "ready"}]})
    return {"id": uuid.uuid4().hex[:12], "plan_version": plan_version, "autonomy": autonomy if autonomy in AUTONOMY else "approval_first", "allowed": [c for c in (allowed or []) if c in CATEGORIES], "state": "ready", "nodes": nodes, "created": now()}


def needs_go_ahead(workflow: Dict[str, Any], node: Dict[str, Any]) -> bool:
    """Whether this node must wait for the user before it starts (tool approvals are separate and always on)."""
    cat = OPERATIONS.get(node["operation"], OPERATIONS["assistant"])["category"]
    if cat == "manual":
        return True
    mode = workflow.get("autonomy", "approval_first")
    if mode == "approval_first":
        return True
    if mode == "balanced":
        return cat == "change"
    return cat not in set(workflow.get("allowed") or [])


def transition(workflow: Dict[str, Any], node_id: str, new: str, detail: str = "") -> Dict[str, Any]:
    """Move a node to a new state; raises ValueError for a transition the state machine does not allow."""
    node = next((n for n in workflow["nodes"] if n["id"] == node_id), None)
    if node is None:
        raise ValueError("no such node")
    if new not in TRANSITIONS.get(node["status"], set()):
        raise ValueError(f"cannot go from {node['status']} to {new}")
    node["status"] = new
    node["history"].append({"ts": now(), "event": new, "status": new, **({"detail": _clip(detail, 400)} if detail else {})})
    if new == "completed":
        for n in workflow["nodes"]:
            if n["status"] == "waiting" and all(next(x for x in workflow["nodes"] if x["id"] == d)["status"] == "completed" for d in n["deps"]):
                n["status"] = "ready"
                n["history"].append({"ts": now(), "event": "dependencies done", "status": "ready"})
    if new in ("failed", "cancelled"):
        for n in workflow["nodes"]:
            if node_id in n["deps"] and n["status"] in ("waiting", "ready"):
                n["status"] = "blocked"
                n["history"].append({"ts": now(), "event": f"blocked: “{node['title']}” {new}", "status": "blocked"})
    if new == "ready":  # retried: unblock what waited on it
        for n in workflow["nodes"]:
            if node_id in n["deps"] and n["status"] == "blocked":
                n["status"] = "waiting"
    workflow["state"] = workflow_state(workflow)
    return node


def workflow_state(workflow: Dict[str, Any]) -> str:
    st = [n["status"] for n in workflow["nodes"]]
    if not st:
        return "ready"
    if all(s == "completed" for s in st):
        return "completed"
    if any(s == "running" for s in st):
        return "running"
    if any(s == "awaiting_approval" for s in st):
        return "awaiting_approval"
    if workflow.get("paused"):
        return "paused"
    if any(s == "failed" for s in st):
        return "failed"
    if all(s in ("completed", "cancelled", "blocked") for s in st):
        return "cancelled"
    return "ready"


def next_node(workflow: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if workflow.get("paused"):
        return None
    return next((n for n in workflow["nodes"] if n["status"] == "ready"), None)


def recover(workflow: Dict[str, Any]) -> int:
    """After a restart: anything that was running or waiting for approval is paused, never re-run."""
    n = 0
    for node in workflow.get("nodes", []):
        if node["status"] in ("running", "awaiting_approval"):
            node["status"] = "paused"
            node["history"].append({"ts": now(), "event": "interrupted: Prometheus was closed while this step ran; it was not repeated", "status": "paused"})
            n += 1
    if n:
        workflow["paused"] = True
        workflow["state"] = workflow_state(workflow)
    return n


# ----- sessions ---------------------------------------------------------------------------------------

def new_session(title: str = "", context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"schema": SCHEMA, "id": uuid.uuid4().hex, "title": _clip(title, 80) or "New ORBIT session", "created": now(), "updated": now(),
            "conversation_id": "", "context": context or {}, "view": "conversation", "autonomy": "approval_first", "allowed": [],
            "plan_versions": [], "active_version": 0, "approved_version": 0, "workflow": None, "events": [], "archived": False}


def current_plan(s: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    v = s.get("active_version") or 0
    return copy.deepcopy(s["plan_versions"][v - 1]["plan"]) if v else None


def add_version(s: Dict[str, Any], plan: Dict[str, Any], author: str, why: str) -> int:
    s["plan_versions"].append({"version": len(s["plan_versions"]) + 1, "plan": normalise_plan(plan), "author": author if author in ("you", "prometheus") else "you", "why": _clip(why, 300), "ts": now()})
    s["active_version"] = len(s["plan_versions"])
    log(s, "plan.updated", f"version {s['active_version']} by {author}: {_clip(why, 120)}")
    return s["active_version"]


def compare(a: Dict[str, Any], b: Dict[str, Any]) -> List[str]:
    """Plain differences between two plan versions."""
    out = []
    ta, tb = {t["id"]: t for t in a["tasks"]}, {t["id"]: t for t in b["tasks"]}
    out += [f"+ {tb[i]['title']}" for i in tb if i not in ta]
    out += [f"− {ta[i]['title']}" for i in ta if i not in tb]
    for i in ta.keys() & tb.keys():
        x, y = ta[i], tb[i]
        if x["title"] != y["title"]:
            out.append(f"renamed: {x['title']} → {y['title']}")
        if x["phase"] != y["phase"]:
            out.append(f"moved: {y['title']} ({x['phase']} → {y['phase']})")
        if x["priority"] != y["priority"]:
            out.append(f"priority: {y['title']} {x['priority']} → {y['priority']}")
    if a["phases"] != b["phases"]:
        out.append("phases: " + " → ".join(b["phases"]))
    da, db = {(d["from"], d["to"]) for d in a["deps"]}, {(d["from"], d["to"]) for d in b["deps"]}
    if da != db:
        out.append(f"dependencies: {len(da)} → {len(db)}")
    for k in ("title", "objective", "outcome", "scope"):
        if a.get(k) != b.get(k):
            out.append(f"{k} changed")
    return out


def log(s: Dict[str, Any], kind: str, detail: str = "") -> None:
    s.setdefault("events", []).append({"ts": now(), "kind": kind, "detail": _clip(detail, 400)})
    del s["events"][:-500]


def valid_session(d: Any) -> bool:
    return isinstance(d, dict) and d.get("schema") == SCHEMA and _ID.match(str(d.get("id", ""))) is not None and isinstance(d.get("plan_versions"), list)


class OrbitStore:
    def __init__(self, data_dir: str):
        self.dir = os.path.join(data_dir, FOLDER)
        os.makedirs(self.dir, exist_ok=True)

    def _path(self, sid: str) -> str:
        if not _ID.match(sid or ""):
            raise ValueError("not a session id")
        return os.path.join(self.dir, f"{sid}.json")

    def save(self, s: Dict[str, Any]) -> bool:
        s["updated"] = now()
        return atomic_write_json(self._path(s["id"]), s)

    def get(self, sid: str) -> Optional[Dict[str, Any]]:
        try:
            path = self._path(sid)
        except ValueError:
            return None
        if not os.path.exists(path):
            return None
        try:
            d = read_json_state(path)
        except Exception:
            quarantine_file(path)
            return None
        if not valid_session(d):
            quarantine_file(path)
            return None
        if d.get("workflow"):
            recovered = recover(d["workflow"])
            if recovered:
                log(d, "session.restored", f"{recovered} interrupted step(s) paused, not repeated")
                self.save(d)
        return d

    def list(self, include_archived: bool = False) -> List[Dict[str, Any]]:
        out = []
        for name in os.listdir(self.dir):
            if not name.endswith(".json"):
                continue
            s = self.get(name[:-5])
            if s and (include_archived or not s.get("archived")):
                wf = s.get("workflow") or {}
                out.append({"id": s["id"], "title": s["title"], "updated": s["updated"], "versions": len(s["plan_versions"]), "workflow": wf.get("state", ""), "archived": s.get("archived", False)})
        out.sort(key=lambda x: x["updated"], reverse=True)
        return out

    def delete(self, sid: str) -> bool:
        try:
            path = self._path(sid)
        except ValueError:
            return False
        if os.path.exists(path):
            os.remove(path)
            return True
        return False
