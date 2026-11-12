"""Pick the adapter for the running operating system."""

from __future__ import annotations

import sys

from .base import Platform


def current() -> Platform:
    if sys.platform.startswith("win"):
        from .windows import WindowsPlatform

        return WindowsPlatform()
    if sys.platform == "darwin":
        from .macos import MacPlatform

        return MacPlatform()
    from .linux import LinuxPlatform

    return LinuxPlatform()


__all__ = ["Platform", "current"]
