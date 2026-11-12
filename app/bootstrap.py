"""Start-up decisions made before the core is imported: where personal data lives, which folder the
workspace tools may use, and loading provider keys from the credential store.

Rules (tested in tests/test_desktop_app.py):
* PROMETHEUS_HOME / PROMETHEUS_WORKSPACE in the environment always win.
* Running from a source checkout that already holds Prometheus data (memory, sessions, audit log...):
  keep using the source folder for data and workspace, exactly as the terminal and HUD do, so nothing
  moves and nothing is copied.
* Otherwise (a packaged install, or a fresh checkout): the platform's per-user data folder, and a
  workspace in the user's Documents (or the folder chosen in Settings).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import List, Optional

SOURCE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Files that mean "someone already uses Prometheus from this folder".
LEGACY_MARKERS = ("memory.json", "memory_graph.json", "audit.jsonl", "task_state.json", "skills.json", "prometheus_config.json", "session.json", "schedule.json", ".env")


def frozen() -> bool:
    """Running from the packaged application (PyInstaller sets sys.frozen)."""
    return bool(getattr(sys, "frozen", False))


def legacy_data_present(folder: str) -> bool:
    if any(os.path.exists(os.path.join(folder, m)) for m in LEGACY_MARKERS):
        return True
    sessions = os.path.join(folder, "sessions")
    return os.path.isdir(sessions) and any(n.endswith(".json") for n in os.listdir(sessions))


@dataclass
class Paths:
    data_dir: str
    workspace: str
    #: "environment", "source checkout (existing data)" or "per-user folder"
    data_reason: str
    workspace_reason: str
    notes: List[str] = field(default_factory=list)


def resolve_paths(platform, chosen_workspace: str = "", source_dir: str = SOURCE_DIR, is_frozen: Optional[bool] = None) -> Paths:
    is_frozen = frozen() if is_frozen is None else is_frozen
    env_home = os.environ.get("PROMETHEUS_HOME", "").strip()
    env_ws = os.environ.get("PROMETHEUS_WORKSPACE", "").strip()
    keep_source = not is_frozen and legacy_data_present(source_dir)
    notes: List[str] = []

    if env_home:
        data_dir, data_reason = os.path.abspath(os.path.expanduser(env_home)), "environment (PROMETHEUS_HOME)"
    elif keep_source:
        data_dir, data_reason = source_dir, "source checkout (existing data kept in place)"
        notes.append("Prometheus data already lives in the source folder, so the desktop app uses it there. Nothing was moved.")
    else:
        data_dir, data_reason = platform.data_dir(), "per-user folder"

    if env_ws:
        workspace, ws_reason = os.path.abspath(os.path.expanduser(env_ws)), "environment (PROMETHEUS_WORKSPACE)"
    elif chosen_workspace.strip():
        workspace, ws_reason = os.path.abspath(os.path.expanduser(chosen_workspace.strip())), "chosen in Settings"
    elif keep_source:
        workspace, ws_reason = source_dir, "source checkout (as the terminal uses it)"
    else:
        workspace, ws_reason = platform.default_workspace(), "default"
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(workspace, exist_ok=True)
    return Paths(data_dir, workspace, data_reason, ws_reason, notes)


def apply(paths: Paths) -> None:
    """Tell the core where to work. Must run before `import prometheus`."""
    os.environ["PROMETHEUS_HOME"] = paths.data_dir
    os.environ["PROMETHEUS_WORKSPACE"] = paths.workspace
    # The desktop app has no terminal: skip the terminal boot animation.
    os.environ.setdefault("PROMETHEUS_FAST_BOOT", "1")
    if source_on_path := SOURCE_DIR:
        if source_on_path not in sys.path:
            sys.path.insert(0, source_on_path)
