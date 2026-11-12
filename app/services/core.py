"""The desktop app's one door into the Prometheus core.

Everything that changes state goes through `prometheus.dispatch_tool`, so the core's own permission
checks, audit log, reflection stats and undo journal apply exactly as they do in the terminal. The
UI never writes core state files itself.
"""

from __future__ import annotations

import inspect
import json
import os
from typing import Any, Dict, List, Optional


class Core:
    def __init__(self):
        import prometheus as p  # import after bootstrap.apply()

        self.p = p

    # ----- identity and routing -----
    @property
    def router(self):
        return self.p.llm_router

    def router_status(self) -> Dict[str, Any]:
        try:
            return self.p.tool_get_router_status()
        except Exception as e:  # never let a status query take the window down
            return {"status": "error", "message": str(e)}

    def reload_router(self) -> bool:
        return self.p.llm_router.reload()

    def providers(self) -> Dict[str, Dict[str, Any]]:
        return {name: dict(cfg) for name, cfg in self.p.PROVIDER_ENDPOINTS.items()}

    # ----- tools (all state changes go through here) -----
    def dispatch(self, tool: str, **args) -> Dict[str, Any]:
        return self.p.dispatch_tool(tool, args)

    def is_dangerous(self, tool: str) -> bool:
        return tool in self.p.DANGEROUS_TOOLS

    def tool_names(self) -> List[str]:
        return [t["function"]["name"] for t in self.p.TOOLS]

    # ----- memory -----
    def memory_stats(self) -> Dict[str, Any]:
        return self.p.memory_graph.stats()

    def recall(self, query: str, top_k: int = 20) -> List[Dict[str, Any]]:
        return self.p.memory_graph.recall(query, top_k=top_k)

    def facts(self, kinds: Optional[List[str]] = None, limit: int = 100) -> List[Dict[str, Any]]:
        return self.p.memory_graph.list_facts(kinds=kinds, limit=limit)

    def neighbors(self, entity: str) -> Optional[Dict[str, Any]]:
        return self.p.memory_graph.neighbors(entity)

    def is_untrusted(self, source: str) -> bool:
        import memory_graph

        return memory_graph.is_untrusted_source(source or "")

    # ----- engineering -----
    def engineering_calcs(self) -> Dict[str, inspect.Signature]:
        import engineering

        names = [n for n in ("convert_units", "section_properties", "beam", "bending_stress", "safety_factor", "torsion_shear", "euler_buckling", "plane_stress", "thermal_expansion", "isa_atmosphere", "lift", "stall_speed", "reynolds_number", "circular_orbit", "vis_viva", "hohmann", "rocket_equation") if hasattr(engineering, n)]
        return {n: inspect.signature(getattr(engineering, n)) for n in names}

    def engineering_doc(self, name: str) -> str:
        import engineering

        return inspect.getdoc(getattr(engineering, name, None)) or ""

    # ----- skills, patches -----
    def skills(self) -> List[Dict[str, Any]]:
        return self.p.skill_registry.list()

    def pending_patches(self) -> List[Dict[str, Any]]:
        out = []
        folder = self.p.PENDING_PATCHES_DIR
        for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
            path = os.path.join(folder, name)
            if name.endswith(".json"):
                try:
                    with open(path, encoding="utf-8") as f:
                        meta = json.load(f)
                    meta["_file"] = name
                    out.append(meta)
                except Exception as e:
                    out.append({"_file": name, "error": str(e)})
        return out

    # ----- scheduler and task state -----
    def scheduled(self) -> List[Dict[str, Any]]:
        return self.p.scheduler_engine.list_jobs()

    def drain_due(self) -> List[Dict[str, Any]]:
        return self.p.drain_due_reminders()

    # ----- trust -----
    def audit_tail(self, n: int = 100) -> List[Dict[str, Any]]:
        return self.p.audit_log.tail(n)

    def audit_verify(self):
        return self.p.audit_log.verify()

    def policy(self):
        return self.p.policy

    def undo_entries(self, n: int = 20) -> List[Dict[str, Any]]:
        return self.p.undo_journal.list(n)

    def tool_stats(self) -> Dict[str, Dict[str, Any]]:
        return self.p.tool_stats.summary()

    # ----- paths -----
    def paths(self) -> Dict[str, str]:
        return {"data": self.p.DATA_DIR, "workspace": self.p.WORKSPACE_DIR, "source": self.p.BASE_DIR}

    def shutdown(self) -> None:
        for step in (lambda: self.p.scheduler_engine.stop(), lambda: self.p.tool_stats.flush()):
            try:
                step()
            except Exception:
                pass
