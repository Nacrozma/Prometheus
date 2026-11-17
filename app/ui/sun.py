"""A painted solar presence: the same sun as the OpenGL orb, drawn with QPainter.

Used where the shader is not wanted (the small sun on Home) or not available (no OpenGL 3.3). It has
the same states and reacts to the same audio level, animates at a modest frame rate only while it is
visible, and holds still under Reduce motion.
"""

from __future__ import annotations

import math
import time

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QRadialGradient
from PyQt6.QtWidgets import QSizePolicy, QWidget

# state → (surface, corona, activity) ; activity drives how lively the corona is
PALETTES = {
    "IDLE": ("#FF8A24", "#F4B52C", 0.25),
    "THINKING": ("#FF9A2E", "#F7D98B", 0.55),
    "WORKING": ("#FF8A24", "#FFB347", 0.75),
    "RESEARCHING": ("#F4B52C", "#F7D98B", 0.6),
    "BUILDING": ("#FF7A1A", "#F4B52C", 0.8),
    "SPEAKING": ("#FFA53A", "#F7D98B", 0.5),
    "LISTENING": ("#E79A3A", "#F7D98B", 0.4),
    "ADAPTING": ("#FF6A1A", "#F4B52C", 0.9),
    "WARNING": ("#C98A3A", "#F7D98B", 0.15),
    "PAUSED": ("#C98A3A", "#F7D98B", 0.15),
    "ERROR": ("#C2412E", "#FF6B5E", 0.2),
    "OFFLINE": ("#6B5232", "#4A3A1E", 0.0),
}


class SolarGlyph(QWidget):
    def __init__(self, size: int = 96, animated: bool = True, parent=None):
        super().__init__(parent)
        self.setMinimumSize(size, size)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.resize(size, size)
        self.state = "IDLE"
        self.audio = 0.0
        self._t0 = time.perf_counter()
        self._reduced = False
        self._animated = animated
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)
        self.setAccessibleName("Prometheus")

    # ----- control -----
    def set_state(self, state: str) -> None:
        self.state = state if state in PALETTES else "IDLE"
        self.update()

    def set_audio_level(self, level: float) -> None:
        self.audio = max(0.0, min(1.0, float(level)))

    def set_reduced_motion(self, reduced: bool) -> None:
        self._reduced = reduced
        self._sync()

    def showEvent(self, e) -> None:
        self._sync()
        super().showEvent(e)

    def hideEvent(self, e) -> None:
        self.timer.stop()
        super().hideEvent(e)

    def _sync(self) -> None:
        if self._animated and not self._reduced and self.isVisible():
            if not self.timer.isActive():
                self.timer.start(33)  # ~30 fps is plenty for a painted glyph
        else:
            self.timer.stop()
            self.update()

    # ----- drawing -----
    def paintEvent(self, _e) -> None:
        surface, corona, activity = PALETTES.get(self.state, PALETTES["IDLE"])
        t = 0.0 if (self._reduced or not self._animated) else time.perf_counter() - self._t0
        w, h = self.width(), self.height()
        c = QPointF(w / 2, h / 2)
        R = min(w, h) * 0.27 * (1.0 + 0.04 * self.audio)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # corona: soft halo, brighter when active or speaking
        glow = 0.55 + 0.25 * activity + 0.35 * self.audio + 0.06 * math.sin(t * 1.3)
        halo = QRadialGradient(c, R * 2.0)
        cc = QColor(corona)
        halo.setColorAt(0.45, QColor(cc.red(), cc.green(), cc.blue(), int(110 * glow)))
        halo.setColorAt(0.7, QColor(cc.red(), cc.green(), cc.blue(), int(38 * glow)))
        halo.setColorAt(1.0, QColor(cc.red(), cc.green(), cc.blue(), 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo)
        p.drawEllipse(c, R * 2.0, R * 2.0)

        # rays: slow-turning flares whose length follows activity and audio
        if self.state != "OFFLINE":
            rays = 12
            p.save()
            p.translate(c)
            p.rotate((t * 6.0) % 360)
            for i in range(rays):
                a = i * 360 / rays
                length = R * (0.22 + 0.18 * activity + 0.3 * self.audio) * (0.7 + 0.3 * math.sin(t * 1.7 + i * 1.9))
                p.save()
                p.rotate(a)
                path = QPainterPath()
                path.moveTo(R * 0.92, -R * 0.06)
                path.quadTo(R + length * 0.6, 0, R + length, 0)
                path.quadTo(R + length * 0.6, 0, R * 0.92, R * 0.06)
                col = QColor(corona)
                col.setAlpha(int(150 * (0.5 + 0.5 * activity)))
                p.setBrush(col)
                p.drawPath(path)
                p.restore()
            p.restore()

        # photosphere: hot centre to darker limb
        sc = QColor(surface)
        body = QRadialGradient(QPointF(c.x() - R * 0.25, c.y() - R * 0.3), R * 1.35)
        body.setColorAt(0.0, QColor("#FFE7A8") if self.state != "OFFLINE" else sc.lighter(130))
        body.setColorAt(0.35, sc.lighter(115))
        body.setColorAt(0.8, sc)
        body.setColorAt(1.0, sc.darker(190))
        p.setBrush(body)
        p.drawEllipse(c, R, R)

        # granulation hint: a few drifting darker cells
        if self.state != "OFFLINE":
            p.setBrush(QColor(0, 0, 0, 26))
            for i in range(5):
                ang = t * 0.15 + i * 1.26
                rr = R * (0.25 + 0.12 * (i % 3))
                pt = QPointF(c.x() + math.cos(ang) * rr, c.y() + math.sin(ang) * rr * 0.8)
                p.drawEllipse(pt, R * 0.09, R * 0.07)

        # limb highlight
        rim = QColor(corona)
        rim.setAlpha(140)
        p.setBrush(Qt.BrushStyle.NoBrush)
        pen = p.pen()
        pen.setStyle(Qt.PenStyle.SolidLine)
        pen.setColor(rim)
        pen.setWidthF(max(1.0, R * 0.03))
        p.setPen(pen)
        p.drawEllipse(QRectF(c.x() - R, c.y() - R, 2 * R, 2 * R))
        from . import avatar_overlay

        avatar_overlay.draw(p, w, h, self.state, t, self.audio)
        p.end()
