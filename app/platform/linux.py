"""Linux adapter: XDG folders, an XDG autostart entry, Secret Service through `keyring`.
Built to the contract; tray and notifications depend on the desktop environment."""

from __future__ import annotations

import os

from .base import Platform


def _xdg(var: str, fallback: str) -> str:
    return os.environ.get(var) or os.path.join(os.path.expanduser("~"), fallback)


class LinuxPlatform(Platform):
    name = "linux"

    def data_dir(self) -> str:
        return self._ensure(os.path.join(_xdg("XDG_DATA_HOME", ".local/share"), "prometheus"))

    def default_workspace(self) -> str:
        return os.path.join(os.path.expanduser("~"), "Prometheus Workspace")

    def credential_backend(self) -> str:
        return "Secret Service (GNOME Keyring / KWallet)"

    def _autostart(self) -> str:
        return os.path.join(_xdg("XDG_CONFIG_HOME", ".config"), "autostart", "prometheus.desktop")

    def launch_at_login(self) -> bool:
        return os.path.exists(self._autostart())

    def set_launch_at_login(self, enabled: bool, command: str) -> None:
        path = self._autostart()
        if not enabled:
            if os.path.exists(path):
                os.remove(path)
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"[Desktop Entry]\nType=Application\nName=Prometheus\nExec={command}\nX-GNOME-Autostart-enabled=true\n")

    def notes(self) -> list[str]:
        return ["Linux support is built but has not been tested on a desktop session. The tray needs a desktop with tray support; some (stock GNOME) hide it."]
