"""Desktop-only settings (window behaviour, workspace, first run). Stored as JSON in the data folder,
written atomically. Provider keys are NOT stored here (see credentials.py); the assistant's own
settings stay in prometheus_config.json, owned by gui_config.py."""

from __future__ import annotations

import copy
import os
import sys
from typing import Any, Dict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from state_io import atomic_write_json, quarantine_file, read_json_state  # noqa: E402

FILE_NAME = "desktop_settings.json"

DEFAULTS: Dict[str, Any] = {
    "version": 1,
    "first_run_done": False,
    "workspace": "",
    "close_to_tray": False,
    "launch_at_login": False,
    "show_notifications": True,
    "reduced_motion": False,
    "auto_approve": False,
    "global_shortcut": "",
    "window_geometry": [],
    #: A folder to import data from at the next start (before the core loads its state).
    "pending_import": "",
}

TYPES = {k: type(v) for k, v in DEFAULTS.items()}


class DesktopSettings:
    def __init__(self, data_dir: str):
        self.path = os.path.join(data_dir, FILE_NAME)
        self.data: Dict[str, Any] = copy.deepcopy(DEFAULTS)
        self.load_error = ""
        self.load()

    def load(self) -> None:
        self.data = copy.deepcopy(DEFAULTS)
        if not os.path.exists(self.path):
            return
        try:
            raw = read_json_state(self.path)
            if not isinstance(raw, dict):
                raise ValueError("not a JSON object")
        except Exception as e:
            moved = quarantine_file(self.path)
            self.load_error = f"{type(e).__name__}: {e}" + (f" (kept as {os.path.basename(moved)})" if moved else "")
            return
        for k, v in raw.items():
            if k in DEFAULTS and isinstance(v, TYPES[k]) and not (TYPES[k] is int and isinstance(v, bool)):
                self.data[k] = v

    def get(self, key: str) -> Any:
        return self.data[key]

    def set(self, key: str, value: Any) -> bool:
        if key not in DEFAULTS:
            raise KeyError(key)
        if not isinstance(value, TYPES[key]):
            raise TypeError(f"{key} must be {TYPES[key].__name__}")
        self.data[key] = value
        return atomic_write_json(self.path, self.data, prefix="desktop_")
