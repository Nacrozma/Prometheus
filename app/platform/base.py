"""The contract every platform adapter fulfils. Shared code talks only to this interface;
operating-system specifics live in windows.py, macos.py and linux.py."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Dict


class Platform(ABC):
    #: "windows", "macos" or "linux"
    name: str = ""
    #: Whether this adapter has been validated on a real machine (not only built in CI).
    validated: bool = False

    @abstractmethod
    def data_dir(self) -> str:
        """Per-user folder for Prometheus's personal state (memory, sessions, audit log...)."""

    @abstractmethod
    def default_workspace(self) -> str:
        """A sensible folder for the workspace tools when the operator has not chosen one."""

    @abstractmethod
    def credential_backend(self) -> str:
        """Plain-language name of the secure credential store used on this system."""

    # ----- launch at login (off unless the operator turns it on) -----

    @abstractmethod
    def launch_at_login(self) -> bool:
        """Whether Prometheus is registered to start when the operator signs in."""

    @abstractmethod
    def set_launch_at_login(self, enabled: bool, command: str) -> None:
        """Register or remove the start-up entry. `command` is the exact command line to run."""

    def capabilities(self) -> Dict[str, bool]:
        """What this platform's adapter supports, for honest settings pages."""
        return {"tray": True, "notifications": True, "launch_at_login": True, "global_shortcut": False}

    def notes(self) -> list[str]:
        """Plain-language limits of this platform's support."""
        return []

    @staticmethod
    def _ensure(path: str) -> str:
        os.makedirs(path, exist_ok=True)
        return path
