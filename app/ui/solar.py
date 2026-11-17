"""The living solar avatar for the desktop.

Built on the HUD's GLSL sun (`gui_orb.SolarSunWidget`, unchanged) with a desktop shader variant that
adds a state tint and a dim factor, and an overlay that only shows what is real: an activity arc while
Prometheus thinks or runs a tool, and a level ring driven by the actual audio level while it speaks or
listens. The HUD's decorative telemetry text is not drawn here.

States (each set by a real application event): IDLE, THINKING, WORKING, RESEARCHING, BUILDING,
ADAPTING, SPEAKING, LISTENING, WARNING, ERROR, OFFLINE, SUCCESS.

Frame rate: 60 fps while the window is active, 30 fps when it is not, stopped while hidden or
minimised; under Reduce motion the sun is drawn once per state change.
"""

from __future__ import annotations

import math
import time

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget

import gui_orb as g

# semantic state → (shader mode, energy, tint rgb, dim)
STATES = {
    "IDLE": (0, 0.62, (1.0, 1.0, 1.0), 1.0),
    "SUCCESS": (0, 0.8, (1.0, 1.03, 0.95), 1.0),
    "THINKING": (1, 1.05, (1.0, 1.02, 1.02), 1.0),
    "WORKING": (1, 1.2, (1.04, 0.97, 0.9), 1.0),
    "RESEARCHING": (1, 1.0, (0.97, 1.03, 1.1), 1.0),
    "BUILDING": (1, 1.35, (1.12, 0.92, 0.78), 1.0),
    "ADAPTING": (3, 1.4, (1.0, 1.0, 1.0), 1.0),
    "SPEAKING": (2, 1.45, (1.04, 1.0, 0.95), 1.0),
    "LISTENING": (2, 0.85, (0.92, 1.0, 1.1), 0.95),
    "PAUSED": (0, 0.55, (0.95, 0.95, 0.95), 0.85),
    "WARNING": (0, 0.55, (0.95, 0.95, 0.95), 0.85),
    "ERROR": (0, 0.5, (1.18, 0.72, 0.62), 0.8),
    "OFFLINE": (0, 0.3, (0.62, 0.62, 0.68), 0.45),
}
ACTIVE = {"THINKING", "WORKING", "RESEARCHING", "BUILDING", "ADAPTING"}
AUDIO = {"SPEAKING", "LISTENING"}

_TINT_DECL = "uniform float u_birth_scale; // 0 during the star-birth intro, ramps to 1\nuniform vec3 u_tint;\nuniform float u_dim;"
_TINT_APPLY = "    col = ACESFilm(col * 1.05);"


def desktop_shader() -> str:
    """The HUD's fragment shader with a tint and dim applied before tone mapping."""
    src = g.FRAGMENT_SHADER
    if "uniform float u_birth_scale; // 0 during the star-birth intro, ramps to 1" not in src or _TINT_APPLY not in src:
        return src  # unknown shader version: render it unchanged rather than break
    src = src.replace("uniform float u_birth_scale; // 0 during the star-birth intro, ramps to 1", _TINT_DECL, 1)
    src = src.replace(_TINT_APPLY, "    col *= u_tint * u_dim;\n" + _TINT_APPLY, 1)
    return src


class SolarAvatar(g.SolarSunWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.semantic = "IDLE"
        self.tint = STATES["IDLE"][2]
        self.dim = 1.0
        self._target_tint = self.tint
        self._target_dim = 1.0
        self._reduced = False
        self._paused = False
        self._active_window = True
        self._has_tint = False
        self.setAccessibleName("Prometheus, the solar avatar")
        self._sign = _StateSign(self)
        self._sign.setGeometry(self.rect())

    # ----- state -----
    def set_semantic(self, state: str) -> None:
        mode, energy, tint, dim = STATES.get(state, STATES["IDLE"])
        self.semantic = state if state in STATES else "IDLE"
        self.state = mode
        self.STATE_ENERGY = {**g.SolarSunWidget.STATE_ENERGY, mode: energy}
        self._target_tint, self._target_dim = tint, dim
        self.setAccessibleDescription(self.semantic.capitalize())
        if getattr(self, "_sign", None) is not None:
            self._sign.update()
        if self._reduced:
            self.energy, self.tint, self.dim = energy, tint, dim
            self.state_mix = 1.0 if mode == 3 else 0.0
        self.update()

    def advance_frame(self) -> None:
        k = 0.08
        self.tint = tuple(a + (b - a) * k for a, b in zip(self.tint, self._target_tint))
        self.dim += (self._target_dim - self.dim) * k
        if self.semantic not in AUDIO:
            self.audio_level *= 0.85  # a level that stopped arriving fades instead of sticking
        super().advance_frame()
        if self._sign is not None:
            self._sign.update()

    # ----- frame rate -----
    def set_reduced_motion(self, reduced: bool) -> None:
        self._reduced = reduced
        self._sync_timer()

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        self._sync_timer()

    def set_window_active(self, active: bool) -> None:
        self._active_window = active
        self._sync_timer()

    def _sync_timer(self) -> None:
        if self._paused or self._reduced:
            self.timer.stop()
            self.update()
            return
        interval = 16 if self._active_window else 33
        if not self.timer.isActive() or self.timer.interval() != interval:
            self._last_tick = time.perf_counter()
            self.timer.start(interval)

    # ----- GL -----
    def initializeGL(self) -> None:
        original = g.FRAGMENT_SHADER
        try:
            g.FRAGMENT_SHADER = desktop_shader()
            super().initializeGL()
        finally:
            g.FRAGMENT_SHADER = original
        from OpenGL import GL

        self.u_tint = GL.glGetUniformLocation(self.program, "u_tint")
        self.u_dim = GL.glGetUniformLocation(self.program, "u_dim")
        self._has_tint = self.u_tint >= 0 and self.u_dim >= 0

    def paintGL(self) -> None:
        if self._has_tint:
            from OpenGL import GL

            GL.glUseProgram(self.program)
            GL.glUniform3f(self.u_tint, *[float(v) for v in self.tint])
            GL.glUniform1f(self.u_dim, float(self.dim))
        super().paintGL()

    def _draw_hud_overlay(self) -> None:
        """Nothing inside the GL frame: the state's sign is drawn by the overlay layer above it."""
        return

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        if getattr(self, "_sign", None) is not None:
            self._sign.setGeometry(self.rect())


class _StateSign(QWidget):
    """A transparent layer over the shader sun that draws the state's sign (avatar_overlay.py)."""

    def __init__(self, avatar: "SolarAvatar"):
        super().__init__(avatar)
        self.avatar = avatar
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, _e) -> None:
        from . import avatar_overlay

        a = self.avatar
        if a.birth.active:
            return
        p = QPainter(self)
        avatar_overlay.draw(p, self.width(), self.height(), a.semantic, 0.0 if a._reduced else a.time, float(a.audio_level))
        p.end()
