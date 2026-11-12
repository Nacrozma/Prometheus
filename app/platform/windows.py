"""Windows 10/11 adapter: %APPDATA%, the HKCU Run key, Windows Credential Manager."""

from __future__ import annotations

import os

from .base import Platform

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "Prometheus"


class WindowsPlatform(Platform):
    name = "windows"

    def data_dir(self) -> str:
        root = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
        return self._ensure(os.path.join(root, "Prometheus"))

    def default_workspace(self) -> str:
        return os.path.join(os.path.expanduser("~"), "Documents", "Prometheus Workspace")

    def credential_backend(self) -> str:
        return "Windows Credential Manager"

    def launch_at_login(self) -> bool:
        import winreg  # type: ignore[import-not-found]

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                winreg.QueryValueEx(key, RUN_VALUE)
                return True
        except OSError:
            return False

    def set_launch_at_login(self, enabled: bool, command: str) -> None:
        import winreg  # type: ignore[import-not-found]

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            if enabled:
                winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, command)
            else:
                try:
                    winreg.DeleteValue(key, RUN_VALUE)
                except FileNotFoundError:
                    pass
