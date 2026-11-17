"""The birth of the sun: Prometheus's launch sequence.

Reuses the HUD's tested star-birth timeline and shader (`gui_birth.py`: collapse of a cloud, protostar
and accretion, ignition, flash and shockwave, the new star settling), drawn full-window over the already
built main window, then the wordmark, then a fade that reveals Home. The application is fully loaded
underneath: the sequence never blocks start-up, and if OpenGL is unavailable a painted version runs
instead (or nothing, under Reduce motion).

Policy: once per application start (not when the window is restored from the tray, not on navigation),
skipped under Reduce motion, switchable in Settings → Appearance, skippable at any moment with a click,
Esc, Enter or Space. Phases and timings: docs/RENAISSANCE_LAUNCH_ANIMATION.md.
"""

from __future__ import annotations

import math
import time

from PyQt6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QRadialGradient
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QVBoxLayout, QWidget

from .. import APP_NAME
from . import theme as T

WORDMARK_FROM = 0.80  # timeline position where the name starts to appear
FADE_MS = 650


def wordmark_alpha(t: float) -> float:
    """0 before the star has settled, then eases to 1."""
    x = max(0.0, min(1.0, (t - WORDMARK_FROM) / (1.0 - WORDMARK_FROM)))
    return x * x * (3 - 2 * x)


def paint_wordmark(p: QPainter, w: int, h: int, t: float, cy: float) -> None:
    a = wordmark_alpha(t)
    if a <= 0:
        return
    f = QFont(T.FONT_DISPLAY.split(",")[0].strip('"'), 30)
    f.setWeight(QFont.Weight.DemiBold)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 12 + 6 * (1 - a))
    p.setFont(f)
    c = QColor(T.ACCENT)
    c.setAlphaF(a)
    p.setPen(c)
    p.drawText(QRectF(0, cy, w, 60), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, APP_NAME.upper())


def paint_skip_hint(p: QPainter, w: int, h: int) -> None:
    f = QFont(T.FONT_UI.split(",")[0].strip('"'), 9)
    p.setFont(f)
    p.setPen(QColor(255, 255, 255, 70))
    p.drawText(QRectF(0, h - 40, w, 20), Qt.AlignmentFlag.AlignHCenter, "Click or press Esc to skip")


def make_gl_sun():
    """The shader sun configured for the launch: no HUD captions (the wordmark is a layer above it)."""
    from .solar import SolarAvatar

    class LaunchSun(SolarAvatar):
        def _draw_birth_caption(self) -> None:
            return

        def _draw_hud_overlay(self) -> None:
            return

    sun = LaunchSun()
    sun._sign.hide()  # no state sign during the launch

    class Wordmark(QWidget):
        """Transparent layer over the shader: the name and the skip hint, timed from the birth timeline."""

        def __init__(self):
            super().__init__(sun)
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.update)
            self.timer.start(33)

        def paintEvent(self, _e) -> None:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            t = sun.birth.t if sun.birth.active else 1.0
            paint_wordmark(p, self.width(), self.height(), t, self.height() * 0.85)
            if sun.birth.active:
                paint_skip_hint(p, self.width(), self.height())
            p.end()

    sun._wordmark = Wordmark()
    _orig = sun.resizeEvent

    def resized(e):
        _orig(e)
        sun._wordmark.setGeometry(sun.rect())

    sun.resizeEvent = resized
    return sun


class PaintedBirth(QWidget):
    """The same phases drawn with QPainter, for machines without OpenGL 3.3."""

    def __init__(self):
        super().__init__()
        from gui_birth import BirthTimeline

        self.birth = BirthTimeline()
        self._last = time.perf_counter()
        self._cb = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

    def start_birth(self, ready: bool, on_finished=None) -> None:
        self._cb = on_finished
        self.birth.start(ready=ready)
        self._last = time.perf_counter()
        self.timer.start(16)

    def skip_birth(self) -> None:
        self.birth.skip()

    def _tick(self) -> None:
        now = time.perf_counter()
        dt, self._last = min(0.1, now - self._last), now
        if self.birth.tick(dt):
            self.timer.stop()
            if self._cb:
                self._cb()
        self.update()

    def paintEvent(self, _e) -> None:
        t = self.birth.t
        w, h = self.width(), self.height()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(T.BG))
        c = QPointF(w / 2, h * 0.42)
        base = min(w, h) * 0.16
        # collapsing cloud: faint dust contracting toward the centre
        if t < 0.6:
            for i in range(60):
                ang = i * 2.399
                r = base * 3.2 * (1.0 - t / 0.6) * (0.4 + (i % 7) / 7) + base * 0.15
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 200, 140, int(60 * (1 - t))))
                p.drawEllipse(QPointF(c.x() + math.cos(ang + t * 3) * r, c.y() + math.sin(ang + t * 3) * r * 0.6), 1.6, 1.6)
        # first light, ignition, the star growing
        core = base * (0.04 + 0.25 * min(1.0, t / 0.55) + self.birth.scale * 0.75)
        g = QRadialGradient(c, core * 3)
        glow = min(1.0, self.birth.energy / 2.0)
        g.setColorAt(0.0, QColor(255, 236, 190, 255))
        g.setColorAt(0.25, QColor(255, 170, 60, int(200 * glow + 55)))
        g.setColorAt(1.0, QColor(255, 120, 20, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(c, core * 3, core * 3)
        # shockwave at ignition
        if 0.68 < t < 0.9:
            k = (t - 0.68) / 0.22
            ring = QColor(T.HIGHLIGHT)
            ring.setAlphaF(max(0.0, 0.6 * (1 - k)))
            pen = p.pen()
            pen.setStyle(Qt.PenStyle.SolidLine)
            pen.setColor(ring)
            pen.setWidthF(2.0)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, base * (0.5 + 3.5 * k), base * (0.5 + 3.5 * k))
        paint_wordmark(p, w, h, t, h * 0.85)
        if self.birth.active:
            paint_skip_hint(p, w, h)
        p.end()


class LaunchOverlay(QWidget):
    """Covers the main window during the sequence, then fades away. Emits `done` once."""

    done = pyqtSignal()

    def __init__(self, parent: QWidget, use_gl: bool):
        super().__init__(parent)
        self.setObjectName("launch")
        self.setAutoFillBackground(True)
        self.setStyleSheet(f"QWidget#launch {{ background: {T.BG}; }}")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(f"{APP_NAME} is starting")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.sun = None
        if use_gl:
            try:
                self.sun = make_gl_sun()
            except Exception:
                self.sun = None
        if self.sun is None:
            self.sun = PaintedBirth()
        self.sun.setAccessibleName("The birth of the sun")
        lay.addWidget(self.sun)
        self._finished = False
        self._started = 0.0

    def start(self) -> None:
        self.setGeometry(self.parent().rect())
        self.show()
        self.raise_()
        self.setFocus()
        self._started = time.perf_counter()
        self.sun.start_birth(ready=True, on_finished=self._settled)
        # a safety net: whatever happens to the animation, the app is revealed
        QTimer.singleShot(int((7.5 + 4.0) * 1000), self.finish)

    def _settled(self) -> None:
        QTimer.singleShot(900, self.finish)  # hold the name for a moment, then reveal Home

    def skip(self) -> None:
        if self.sun is not None and getattr(self.sun, "birth", None) is not None and self.sun.birth.active:
            self.sun.skip_birth()
        else:
            self.finish()

    def finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(fx)
        a = QPropertyAnimation(fx, b"opacity", self)
        a.setDuration(FADE_MS)
        a.setStartValue(1.0)
        a.setEndValue(0.0)
        a.setEasingCurve(QEasingCurve.Type.InOutCubic)
        a.finished.connect(self._close)
        a.start()
        self._anim = a

    def _close(self) -> None:
        self.hide()
        self.done.emit()
        self.deleteLater()

    def mousePressEvent(self, e) -> None:
        self.skip()

    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.skip()
        else:
            super().keyPressEvent(e)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
