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

import gui_orb as g

# semantic state → (shader mode, energy, tint rgb, dim)
STATES = {
    "IDLE": (0, 0.62, (1.0, 1.0, 1.0), 1.0),
    "SUCCESS": (0, 0.75, (1.0, 1.02, 0.96), 1.0),
    "THINKING": (1, 1.05, (1.0, 1.0, 1.0), 1.0),
    "WORKING": (1, 1.2, (1.04, 0.97, 0.9), 1.0),
    "RESEARCHING": (1, 1.0, (1.0, 1.04, 1.06), 1.0),
    "BUILDING": (1, 1.3, (1.08, 0.95, 0.85), 1.0),
    "ADAPTING": (3, 1.4, (1.0, 1.0, 1.0), 1.0),
    "SPEAKING": (2, 1.45, (1.0, 1.0, 1.0), 1.0),
    "LISTENING": (2, 0.9, (0.96, 1.02, 1.08), 1.0),
    "WARNING": (0, 0.9, (1.08, 1.0, 0.8), 1.0),
    "ERROR": (0, 0.55, (1.2, 0.7, 0.6), 0.9),
    "OFFLINE": (0, 0.35, (0.8, 0.8, 0.82), 0.55),
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

    # ----- state -----
    def set_semantic(self, state: str) -> None:
        mode, energy, tint, dim = STATES.get(state, STATES["IDLE"])
        self.semantic = state if state in STATES else "IDLE"
        self.state = mode
        self.STATE_ENERGY = {**g.SolarSunWidget.STATE_ENERGY, mode: energy}
        self._target_tint, self._target_dim = tint, dim
        self.setAccessibleDescription(self.semantic.capitalize())
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
        """Only real signals: an activity arc while working, a level ring while audio flows."""
        if self.semantic not in ACTIVE and self.semantic not in AUDIO:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r = min(w, h) * 0.42
        rect = QRectF(w / 2 - r, h / 2 - r, 2 * r, 2 * r)
        if self.semantic in ACTIVE:
            pen = QPen(QColor(247, 217, 139, 150), 1.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            start = int(((self.time * 70.0) % 360) * 16)
            p.drawArc(rect, -start, 70 * 16)
        else:
            level = max(0.0, min(1.0, float(self.audio_level)))
            col = QColor(247, 217, 139) if self.semantic == "LISTENING" else QColor(244, 181, 44)
            col.setAlpha(int(60 + 150 * level))
            p.setPen(QPen(col, 1.2 + 2.5 * level))
            grow = r * (1.0 + 0.05 * level)
            p.drawEllipse(QRectF(w / 2 - grow, h / 2 - grow, 2 * grow, 2 * grow))
            # a few ticks whose length follows the level, for a visible voice even at small sizes
            p.setPen(QPen(col, 1.4))
            for i in range(36):
                a = i * math.tau / 36
                length = 3 + 10 * level * (0.6 + 0.4 * math.sin(self.time * 7 + i))
                x1, y1 = w / 2 + math.cos(a) * (grow + 3), h / 2 + math.sin(a) * (grow + 3)
                x2, y2 = w / 2 + math.cos(a) * (grow + 3 + length), h / 2 + math.sin(a) * (grow + 3 + length)
                p.drawLine(int(x1), int(y1), int(x2), int(y2))
        p.end()
