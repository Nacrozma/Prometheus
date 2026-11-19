"""The shared speech service as Qt signals, owned by the main window and used by Companion and ORBIT.

Worker-thread callbacks become signals, so pages update their avatar and state on the UI thread. The pages
call `speak`, `stop` and read `is_busy` / `enabled`; they never create their own speech engine.
"""

from __future__ import annotations

from typing import Callable, Optional, Tuple

from PyQt6.QtCore import QObject, pyqtSignal

from ..services import speech as S


class SpeechBridge(QObject):
    level = pyqtSignal(float)  # real playback level 0..1
    speaking = pyqtSignal(bool)  # audio actually started / finished playing
    error = pyqtSignal(str)  # the chosen engine could not speak (no fallback was used)

    def __init__(self, data_dir: str, settings, service: Optional[S.SpeechService] = None, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.service = service or S.SpeechService(data_dir, S.prefs_from(settings))
        self.service.on_level = self.level.emit
        self.service.on_speaking = self.speaking.emit
        self.service.on_error = self.error.emit

    @property
    def enabled(self) -> bool:
        return self.service.enabled

    @property
    def is_busy(self) -> bool:
        return self.service.is_busy

    def speak(self, text: str) -> bool:
        return self.service.speak(text)

    def stop(self) -> None:
        self.service.stop()

    def set_muted(self, muted: bool) -> None:
        self.service.set_muted(muted)

    def availability(self) -> Tuple[bool, str]:
        return self.service.availability()

    def describe(self) -> str:
        s = self.service.settings()
        if not s["enabled"]:
            return "Spoken replies: off"
        ok, why = self.availability()
        where = "on this computer" if s["engine"] == "local" else "Microsoft online (reply text is sent to Microsoft)"
        return f"Spoken replies: {where}" + ("" if ok else f" — not ready: {why}")

    def test(self, done: Callable[[bool, str], None], owner=None) -> None:
        from .widgets import run_bg

        run_bg(lambda: self.service.test(), lambda r: done(*r), lambda m: done(False, m.splitlines()[0]), owner=owner or self)

    def shutdown(self) -> None:
        self.service.shutdown()
