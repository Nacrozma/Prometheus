"""ORBIT's spatial workspace for Prometheus: project stages, environments, panels and the connections between
them — all derived from the real session (plan versions, workflow, files, review marks). Plain Python, tested.

Nothing here invents content: a panel with no real data is reported empty (and the UI says what would fill it);
a connection exists only when a real relationship exists (a task in the plan, a file written by a step, an
approval waiting on a step). The UI may move and resize panels; that layout is stored per environment in the
session, as fractions of the stage, and clamped on load so a panel can never be lost off-screen.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from . import orbit as O

STAGES: List[Tuple[str, str]] = [
    ("overview", "Overview"), ("ideas", "Ideas"), ("plan", "Plan"), ("design", "Design"),
    ("build", "Build"), ("review", "Review"), ("complete", "Complete"),
]

ENVIRONMENTS: Dict[str, Dict[str, Any]] = {
    "command": {"name": "Command", "purpose": "Conversation, project overview, files, ideas and live activity",
                "panels": ["brief", "ideas", "files", "plan", "next", "activity"], "constellation": False},
    "design": {"name": "Design", "purpose": "Phases, tasks and how they depend on each other",
               "panels": ["brief", "plan", "structure"], "constellation": True},
    "operations": {"name": "Operations", "purpose": "Steps, progress, approvals, errors and recovery",
                   "panels": ["operations", "approvals", "next", "files"], "constellation": True},
    "intelligence": {"name": "Intelligence", "purpose": "Research results, ideas, open questions, assumptions and risks",
                     "panels": ["research", "ideas", "questions", "risks"], "constellation": False},
}

#: Panel id → (title, what fills it when empty)
PANELS: Dict[str, Tuple[str, str]] = {
    "brief": ("Project brief", "Tell Prometheus what you want to achieve; the brief appears with its first plan."),
    "ideas": ("Ideas", "Ideas Prometheus proposes for the project appear here."),
    "files": ("Files", "Files you attach, and files written by ORBIT steps, appear here."),
    "plan": ("Project plan", "The plan forms here as Prometheus proposes it."),
    "next": ("Next steps", "What to do next appears once there is a plan."),
    "activity": ("Live activity", "What happened in this session appears here."),
    "structure": ("Structure", "Phases and dependencies appear once there is a plan."),
    "operations": ("Operations", "Build the workflow from an approved plan to see its steps."),
    "approvals": ("Approvals", "Nothing is waiting for you."),
    "research": ("Research", "Results of reading and research steps appear here."),
    "questions": ("Open questions", "Questions Prometheus still needs answered appear here."),
    "risks": ("Assumptions and risks", "Assumptions and risks in the plan appear here."),
}

#: where panels sit by default, as (centre x, centre y) fractions of the stage: around the core, like a ring
SLOTS = [(0.16, 0.22), (0.84, 0.22), (0.16, 0.76), (0.84, 0.76), (0.5, 0.82), (0.5, 0.17)]
PANEL_W, PANEL_H = 0.26, 0.28
MIN_W, MIN_H = 0.14, 0.12


def plan_of(s: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return O.current_plan(s) if s else None


# ------------------------------------------------------------------ project stages

def stages(s: Dict[str, Any]) -> List[Dict[str, str]]:
    """Each stage with state done / current / open and the real reason, in order. Exactly one stage is current
    (the first that is not done), unless all are done."""
    plan = plan_of(s) or {}
    wf = s.get("workflow") or {}
    nodes = wf.get("nodes") or []
    has_conv = bool(s.get("conversation_id")) or bool(plan)
    approved = bool(s.get("approved_version")) and s.get("approved_version") == s.get("active_version")
    done_steps = sum(1 for n in nodes if n["status"] == "completed")
    facts = {
        "overview": (has_conv and bool(plan), "the project has a plan" if plan else "talk about what you want to achieve"),
        "ideas": (bool(plan.get("ideas") or plan.get("brief")), f"{len(plan.get('ideas') or [])} ideas, brief {'written' if plan.get('brief') else 'not written'}"),
        "plan": (approved and bool(plan.get("tasks")), f"version {s.get('active_version', 0)} {'approved' if approved else 'not approved yet'}"),
        "design": (bool(wf) and wf.get("plan_version") == s.get("approved_version"), "workflow built from the approved plan" if wf else "build the workflow to decide how each step is done"),
        "build": (wf.get("state") == "completed", f"{done_steps}/{len(nodes)} steps done" if nodes else "no steps yet"),
        "review": (bool(s.get("reviewed")), "you reviewed the results" if s.get("reviewed") else "review the results, then mark them reviewed"),
        "complete": (bool(s.get("completed")), "you marked the project complete" if s.get("completed") else "mark complete after review"),
    }
    out, current_found = [], False
    for key, name in STAGES:
        done, why = facts[key]
        state = "done" if done else ("open" if current_found else "current")
        if not done:
            current_found = True
        out.append({"key": key, "name": name, "state": state, "why": why})
    return out


def current_stage(s: Dict[str, Any]) -> str:
    return next((st["key"] for st in stages(s) if st["state"] == "current"), "complete")


def stage_environment(stage: str) -> Tuple[str, str]:
    """Where navigating to a stage takes you: (environment, panel to focus)."""
    return {"overview": ("command", "brief"), "ideas": ("intelligence", "ideas"), "plan": ("design", "plan"),
            "design": ("design", "structure"), "build": ("operations", "operations"), "review": ("operations", "operations"),
            "complete": ("command", "brief")}.get(stage, ("command", "brief"))


class StageError(ValueError):
    pass


def mark_reviewed(s: Dict[str, Any]) -> None:
    wf = s.get("workflow") or {}
    if wf.get("state") != "completed":
        raise StageError("Review comes after every step is completed.")
    s["reviewed"] = True
    O.log(s, "project.reviewed", "marked reviewed by you")


def mark_complete(s: Dict[str, Any]) -> None:
    if not s.get("reviewed"):
        raise StageError("Mark the results reviewed first.")
    s["completed"] = True
    O.log(s, "project.completed", "marked complete by you")


# ------------------------------------------------------------------ files

def safe_path(workspace: str, path: str) -> Optional[str]:
    """`path` resolved inside the workspace (symlinks followed), or None when it would leave it."""
    if not workspace or not path:
        return None
    root = os.path.realpath(workspace)
    full = os.path.realpath(path if os.path.isabs(path) else os.path.join(root, path))
    return full if full == root or full.startswith(root + os.sep) else None


def add_file(s: Dict[str, Any], workspace: str, path: str, origin: str, task_id: str = "") -> Optional[Dict[str, Any]]:
    """Record a file in the session (attached by you, or written by a step). Only files inside the workspace."""
    full = safe_path(workspace, path)
    if full is None:
        return None
    rel = os.path.relpath(full, os.path.realpath(workspace))
    files = s.setdefault("files", [])
    for f in files:
        if f["path"] == rel:
            if task_id and not f.get("task"):
                f["task"] = task_id
            return f
    rec = {"path": rel, "origin": origin if origin in ("attached", "written") else "attached", "task": task_id, "ts": O.now()}
    files.append(rec)
    del files[:-200]
    O.log(s, "file." + rec["origin"], rel)
    return rec


def read_preview(workspace: str, rel: str, limit: int = 200_000) -> str:
    full = safe_path(workspace, rel)
    if full is None or not os.path.isfile(full):
        raise FileNotFoundError("That file is not in the workspace any more.")
    with open(full, "rb") as f:
        data = f.read(limit + 1)
    if b"\0" in data[:4096]:
        return "(binary file: no preview)"
    text = data[:limit].decode("utf-8", errors="replace")
    return text + ("\n…(preview truncated)" if len(data) > limit else "")


# ------------------------------------------------------------------ panel content (real data only)

def panel_content(s: Dict[str, Any], pid: str) -> Dict[str, Any]:
    """{'title', 'items': [ {text, sub, state, ref} ], 'empty': hint or ''} for a panel."""
    plan = plan_of(s) or {}
    wf = s.get("workflow") or {}
    nodes = wf.get("nodes") or []
    title, hint = PANELS[pid]
    items: List[Dict[str, str]] = []
    if pid == "brief" and plan:
        items.append({"text": plan["title"], "sub": "", "state": "title", "ref": ""})
        for label, key in (("Objective", "objective"), ("Brief", "brief"), ("Outcome", "outcome"), ("Scope", "scope")):
            if plan.get(key):
                items.append({"text": plan[key], "sub": label, "state": "", "ref": ""})
    elif pid == "ideas":
        items = [{"text": i, "sub": "idea", "state": "", "ref": ""} for i in plan.get("ideas") or []]
    elif pid == "files":
        items = [{"text": f["path"], "sub": "written by a step" if f["origin"] == "written" else "attached", "state": f["origin"], "ref": f["path"]} for f in s.get("files") or []]
    elif pid == "plan" and plan:
        status = {n["id"]: n["status"] for n in nodes}
        for ph in plan["phases"]:
            ts = [t for t in plan["tasks"] if t["phase"] == ph]
            done = sum(1 for t in ts if status.get(t["id"]) == "completed")
            items.append({"text": ph, "sub": f"{len(ts)} tasks" + (f", {done} done" if status else ""), "state": "done" if ts and done == len(ts) else "", "ref": ""})
    elif pid == "next":
        waiting = [n for n in nodes if n["status"] == "awaiting_approval"]
        ready = [n for n in nodes if n["status"] == "ready"]
        failed = [n for n in nodes if n["status"] in ("failed", "blocked")]
        items += [{"text": n["title"], "sub": "waiting for your approval", "state": "awaiting_approval", "ref": n["id"]} for n in waiting]
        items += [{"text": n["title"], "sub": "failed — retry or change the plan" if n["status"] == "failed" else "blocked", "state": n["status"], "ref": n["id"]} for n in failed]
        items += [{"text": n["title"], "sub": "ready to start", "state": "ready", "ref": n["id"]} for n in ready[:4]]
        if plan and not nodes:
            approved = s.get("approved_version") == s.get("active_version") and s.get("approved_version")
            items.append({"text": "Build the workflow" if approved else "Review and approve the plan", "sub": f"version {s.get('active_version')}", "state": "", "ref": ""})
        items += [{"text": q, "sub": "open question", "state": "question", "ref": ""} for q in (plan.get("questions") or [])[:3]]
        if wf.get("state") == "completed" and not s.get("reviewed"):
            items.insert(0, {"text": "Review the results", "sub": "every step is done", "state": "", "ref": ""})
    elif pid == "activity":
        items = [{"text": e["kind"].replace(".", " "), "sub": f"{e['ts'][11:16]} {e['detail']}", "state": "", "ref": ""} for e in reversed((s.get("events") or [])[-12:])]
    elif pid == "structure" and plan:
        by = {t["id"]: t["title"] for t in plan["tasks"]}
        items = [{"text": f"{by.get(d['from'], '?')} → {by.get(d['to'], '?')}", "sub": "must finish first", "state": "", "ref": d["to"]} for d in plan["deps"]]
        items += [{"text": ph, "sub": f"phase {i + 1}", "state": "", "ref": ""} for i, ph in enumerate(plan["phases"])]
    elif pid == "operations":
        items = [{"text": n["title"], "sub": O.OPERATIONS.get(n["operation"], {}).get("name", n["operation"]), "state": n["status"], "ref": n["id"]} for n in nodes]
    elif pid == "approvals":
        items = [{"text": n["title"], "sub": (n["history"][-1].get("detail") or n["history"][-1]["event"]) if n["history"] else "", "state": "awaiting_approval", "ref": n["id"]} for n in nodes if n["status"] == "awaiting_approval"]
    elif pid == "research":
        reading = {"forge:architect"}
        items = [{"text": n["title"], "sub": (n.get("output") or "")[:600], "state": n["status"], "ref": n["id"]} for n in nodes if n.get("output") and (n["operation"] in reading or n["status"] == "completed")]
    elif pid == "questions":
        items = [{"text": q, "sub": "", "state": "question", "ref": ""} for q in plan.get("questions") or []]
    elif pid == "risks":
        items = [{"text": a, "sub": "assumption", "state": "", "ref": ""} for a in plan.get("assumptions") or []]
        items += [{"text": r, "sub": "risk", "state": "risk", "ref": ""} for r in plan.get("risks") or []]
    return {"id": pid, "title": title, "items": items, "empty": "" if items else hint}


# ------------------------------------------------------------------ connections (real relationships only)

def connections(s: Dict[str, Any], env: str) -> List[Dict[str, str]]:
    """Edges drawn in the workspace: core→panel when the panel has real content; task→plan; file→task;
    approval→operations. Each edge names its kind so it can be labelled and styled."""
    out: List[Dict[str, str]] = []
    panels = ENVIRONMENTS[env]["panels"]
    filled = {pid for pid in panels if panel_content(s, pid)["items"]}
    out += [{"from": "core", "to": pid, "kind": "context"} for pid in panels if pid in filled]
    plan = plan_of(s) or {}
    wf = s.get("workflow") or {}
    if "plan" in filled and "next" in filled and wf:
        out.append({"from": "plan", "to": "next", "kind": "drives"})
    if "brief" in filled and "ideas" in filled and plan.get("ideas"):
        out.append({"from": "ideas", "to": "brief", "kind": "informs"})
    task_ids = {t["id"] for t in plan.get("tasks") or []}
    for f in s.get("files") or []:
        if f.get("task") in task_ids and "files" in filled:
            target = "operations" if "operations" in filled else "plan" if "plan" in filled else ""
            if target:
                out.append({"from": "files", "to": target, "kind": "written by", "ref": f["path"]})
                break
    if "approvals" in filled and "operations" in filled:
        out.append({"from": "approvals", "to": "operations", "kind": "waits on"})
    return out


# ------------------------------------------------------------------ layout

def default_rect(env: str, pid: str) -> Dict[str, float]:
    panels = ENVIRONMENTS[env]["panels"]
    i = panels.index(pid) if pid in panels else 0
    cx, cy = SLOTS[i % len(SLOTS)]
    return {"x": cx - PANEL_W / 2, "y": cy - PANEL_H / 2, "w": PANEL_W, "h": PANEL_H, "collapsed": False, "hidden": False}


def clamp_rect(r: Dict[str, Any]) -> Dict[str, Any]:
    """Keep a stored rectangle usable: sizes within bounds and at least part of the panel on screen."""
    def num(k, d):
        try:
            v = float(r.get(k, d))
        except (TypeError, ValueError):
            v = d
        return v if v == v else d  # NaN guard

    w = min(0.9, max(MIN_W, num("w", PANEL_W)))
    h = min(0.9, max(MIN_H, num("h", PANEL_H)))
    x = min(1 - 0.06, max(-w + 0.06, num("x", 0.0)))
    y = min(1 - 0.05, max(0.0, num("y", 0.0)))
    return {"x": x, "y": y, "w": w, "h": h, "collapsed": bool(r.get("collapsed")), "hidden": bool(r.get("hidden"))}


def layout(s: Dict[str, Any], env: str) -> Dict[str, Dict[str, Any]]:
    stored = (s.get("layout") or {}).get(env) or {}
    return {pid: clamp_rect({**default_rect(env, pid), **(stored.get(pid) or {})}) for pid in ENVIRONMENTS[env]["panels"]}


def set_rect(s: Dict[str, Any], env: str, pid: str, **changes) -> Dict[str, Any]:
    if env not in ENVIRONMENTS or pid not in ENVIRONMENTS[env]["panels"]:
        raise ValueError("unknown panel")
    cur = layout(s, env)[pid]
    cur.update({k: v for k, v in changes.items() if k in ("x", "y", "w", "h", "collapsed", "hidden")})
    rect = clamp_rect(cur)
    s.setdefault("layout", {}).setdefault(env, {})[pid] = rect
    return rect


def reset_layout(s: Dict[str, Any], env: str) -> None:
    (s.get("layout") or {}).pop(env, None)


def set_environment(s: Dict[str, Any], env: str) -> None:
    if env not in ENVIRONMENTS:
        raise ValueError("unknown environment")
    s["environment"] = env
