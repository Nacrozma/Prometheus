"""Forge disciplines: Architect, Builder, Debugger, Reconstructor.

A mission is a conversation with Prometheus about one project in the workspace, framed by a discipline.
The discipline's boundary is enforced at the approval gate in the desktop app (the worker cannot run a
real-world tool without an answer from it), in addition to the core's own policy:

* Architect: read-only. Every tool with real-world effects is refused automatically.
* Builder: may change files and run code, each step with your approval as usual.
* Debugger: may change files and run code with your approval; asked to reproduce before fixing.
* Reconstructor: may only create NEW files (recovery docs). Editing or overwriting an existing file,
  running code or a shell command is refused automatically.

During a mission, auto-approve is off whatever the setting says. Missions are listed in
`<data>/forge_missions.json` (atomic writes), each with the conversation that holds its work.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from state_io import atomic_write_json, quarantine_file, read_json_state

READ_ONLY = {"run_code_forge", "ghost_control", "sculpt_workspace", "synthesize_dynamic_tool", "apply_pending_patch", "execute_shell", "write_file", "edit_file", "export_obsidian", "propose_code_change", "run_skill"}

DISCIPLINES: Dict[str, Dict[str, str]] = {
    "architect": {
        "name": "Architect",
        "summary": "Inspects a project, explains its architecture, finds risks and writes an implementation plan.",
        "boundary": "Read-only: tools that change anything are refused automatically.",
        "prompt": "You are working as Prometheus's Architect discipline on the project folder '{project}'. Read-only: inspect files with read_file only; do not try to change files or run commands (such calls are refused). Produce: 1) a short architecture overview, 2) risks and weak points with file references, 3) a step-by-step implementation plan for the objective. Objective: {objective}",
    },
    "builder": {
        "name": "Builder",
        "summary": "Implements a change: creates and edits files, runs the relevant tests, documents what changed.",
        "boundary": "Every file change and every run asks you first.",
        "prompt": "You are working as Prometheus's Builder discipline on the project folder '{project}'. Read the relevant files first, then implement the objective in small steps with write_file/edit_file (each needs the operator's approval), run the relevant tests if any, and finish with a summary listing every file changed and the test result. Objective: {objective}",
    },
    "debugger": {
        "name": "Debugger",
        "summary": "Reproduces a problem, traces its cause from code and logs, then proposes and validates a fix.",
        "boundary": "Changes and runs ask you first; it must reproduce before fixing.",
        "prompt": "You are working as Prometheus's Debugger discipline on the project folder '{project}'. First reproduce or locate the failure (read code and logs; run only what is needed, with approval). State the root cause with evidence, then propose the smallest fix; apply it only through approved edits, and validate it. Problem: {objective}",
    },
    "reconstructor": {
        "name": "Reconstructor",
        "summary": "Recovers an undocumented project's architecture and writes recovery documentation as new files.",
        "boundary": "May only create new files; editing existing files and running code are refused.",
        "prompt": "You are working as Prometheus's Reconstructor discipline on the project folder '{project}'. Read the project to recover its structure, purpose, entry points and data flow. Write your findings only as NEW files under '{project}/RECOVERY/' (for example ARCHITECTURE.md); never modify existing files (such calls are refused). Objective: {objective}",
    },
}


def decide(discipline: str, tool: str, args: Dict[str, Any], workspace: str) -> Tuple[bool, str]:
    """Whether the discipline lets this tool call reach the approval card. (False, reason) = refused."""
    if discipline == "architect" and tool in READ_ONLY:
        return False, "The Architect discipline is read-only."
    if discipline == "reconstructor":
        if tool == "write_file":
            path = str(args.get("path") or args.get("filepath") or "")
            target = os.path.realpath(os.path.join(workspace, path))
            if not path or os.path.exists(target) or args.get("append"):
                return False, "The Reconstructor may only create new files, not change existing ones."
            return True, ""
        if tool in READ_ONLY:
            return False, "The Reconstructor may only create new documentation files."
    return True, ""


class MissionLog:
    def __init__(self, data_dir: str):
        self.path = os.path.join(data_dir, "forge_missions.json")

    def _load(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.path):
            return []
        try:
            data = read_json_state(self.path)
        except Exception:
            quarantine_file(self.path)
            return []
        return data if isinstance(data, list) else []

    def list(self) -> List[Dict[str, Any]]:
        return sorted(self._load(), key=lambda m: m.get("started", ""), reverse=True)

    def start(self, discipline: str, project: str, objective: str, conversation_id: str) -> Dict[str, Any]:
        if discipline not in DISCIPLINES:
            raise ValueError("unknown discipline")
        m = {"id": uuid.uuid4().hex[:12], "discipline": discipline, "project": project, "objective": objective[:500], "conversation_id": conversation_id, "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "refused": 0}
        data = self._load()
        data.append(m)
        atomic_write_json(self.path, data[-200:])
        return m

    def count_refusal(self, mission_id: str) -> None:
        data = self._load()
        for m in data:
            if m.get("id") == mission_id:
                m["refused"] = int(m.get("refused", 0)) + 1
        atomic_write_json(self.path, data)


def prompt(discipline: str, project: str, objective: str) -> str:
    return DISCIPLINES[discipline]["prompt"].format(project=project, objective=objective.strip())


def describe(m: Dict[str, Any]) -> str:
    return json.dumps({k: m.get(k) for k in ("discipline", "project", "started")})


READ_TOOLS = {"read_file", "read_source_code", "recall_memory", "memory_graph_view", "web_search", "list_skills", "get_router_status", "usage_history"}
CHANGE_TOOLS = {"write_file", "edit_file", "sculpt_workspace", "propose_code_change", "apply_pending_patch", "synthesize_dynamic_tool"}
RUN_TOOLS = {"run_code_forge", "execute_shell", "run_skill"}

STAGES = {
    "architect": ["Started", "Investigating", "Plan written"],
    "builder": ["Started", "Reading", "Changing", "Verifying", "Report"],
    "debugger": ["Started", "Reproducing", "Fixing", "Verifying", "Report"],
    "reconstructor": ["Started", "Investigating", "Writing recovery docs", "Report"],
}


def progress(discipline: str, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """What a mission has actually done, from its conversation: tool calls, their results, the report.
    Stages are reached only by recorded events; nothing is estimated."""
    calls: List[Dict[str, Any]] = []
    results: Dict[str, Dict[str, Any]] = {}
    for m in messages:
        if m.get("role") == "assistant":
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function") or {}
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except ValueError:
                    args = {}
                calls.append({"id": tc.get("id"), "tool": fn.get("name", ""), "args": args if isinstance(args, dict) else {}})
        elif m.get("role") == "tool":
            try:
                res = json.loads(m.get("content") or "{}")
            except ValueError:
                res = {"status": "unknown"}
            results[m.get("tool_call_id", "")] = res if isinstance(res, dict) else {"status": "unknown"}
    for c in calls:
        c["status"] = str(results.get(c["id"], {}).get("status", "pending"))
    reads = [c for c in calls if c["tool"] in READ_TOOLS]
    changes = [c for c in calls if c["tool"] in CHANGE_TOOLS]
    runs = [c for c in calls if c["tool"] in RUN_TOOLS]
    refused = [c for c in calls if c["status"] in ("refused", "denied", "declined")]
    last_text = next((m.get("content") for m in reversed(messages) if m.get("role") == "assistant" and isinstance(m.get("content"), str) and m["content"].strip() and not m.get("tool_calls")), "")
    ended_with_text = bool(messages) and messages[-1].get("role") == "assistant" and bool(last_text)
    names = STAGES.get(discipline, STAGES["builder"])
    reached = 1 if messages else 0
    done_changes = [c for c in changes if c["status"] == "success"]
    if discipline == "architect":
        reached = 1 + bool(reads) + ended_with_text
    elif discipline == "reconstructor":
        reached = 1 + bool(reads) + bool(done_changes) + ended_with_text
    else:
        reached = 1 + bool(reads or runs) + bool(changes) + bool(runs and changes and calls.index(runs[-1]) > calls.index(changes[0])) + ended_with_text
    if not messages:
        reached = 0  # nothing recorded yet: no stage is claimed
    files = []
    for c in changes:
        p = c["args"].get("path") or c["args"].get("target_file") or c["args"].get("file")
        if p and p not in [f["path"] for f in files]:
            files.append({"path": str(p), "tool": c["tool"], "status": c["status"]})
    return {"stages": names, "reached": min(reached, len(names)), "calls": calls, "reads": len(reads), "changes": len(changes), "runs": runs, "refused": len(refused), "files": files, "report": last_text if ended_with_text else ""}


def recommend(objective: str) -> str:
    """A discipline that fits the wording of an objective (the owner can choose another)."""
    t = (objective or "").lower()
    if any(w in t for w in ("bug", "error", "fail", "crash", "broken", "exception", "traceback", "fix", "doesn't work", "does not work")):
        return "debugger"
    if any(w in t for w in ("document", "undocumented", "recover", "understand how", "reverse", "legacy", "what does this")):
        return "reconstructor"
    if any(w in t for w in ("plan", "review", "architecture", "assess", "audit", "design", "risk", "evaluate")):
        return "architect"
    return "builder"
