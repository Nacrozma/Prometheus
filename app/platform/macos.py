"""macOS adapter. Built to the contract but NOT validated on a Mac yet (see CROSS_PLATFORM_ROADMAP.md):
Application Support, a LaunchAgent for launch at login, the Keychain through `keyring`."""

from __future__ import annotations

import os
import plistlib

from .base import Platform

AGENT = os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents", "app.prometheus.desktop.plist")


class MacPlatform(Platform):
    name = "macos"

    def data_dir(self) -> str:
        return self._ensure(os.path.join(os.path.expanduser("~"), "Library", "Application Support", "Prometheus"))

    def default_workspace(self) -> str:
        return os.path.join(os.path.expanduser("~"), "Documents", "Prometheus Workspace")

    def credential_backend(self) -> str:
        return "macOS Keychain"

    def launch_at_login(self) -> bool:
        return os.path.exists(AGENT)

    def set_launch_at_login(self, enabled: bool, command: str) -> None:
        if not enabled:
            if os.path.exists(AGENT):
                os.remove(AGENT)
            return
        import shlex

        os.makedirs(os.path.dirname(AGENT), exist_ok=True)
        with open(AGENT, "wb") as f:
            plistlib.dump({"Label": "app.prometheus.desktop", "ProgramArguments": shlex.split(command), "RunAtLoad": True}, f)

    def notes(self) -> list[str]:
        return ["macOS support is built but has not been tested on a Mac. An app bundle, signing and notarisation are still to do."]
