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
