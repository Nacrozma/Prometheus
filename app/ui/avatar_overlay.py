"""The avatar's state vocabulary: one geometric sign per state, drawn over the sun.

Each state gets a different *shape* (not only a colour), so states stay distinguishable in grey scale,
at small sizes and for colour-blind viewers, and the state is also given in words next to the avatar:

* IDLE         nothing: a quiet sun
* THINKING     two tilted orbits, a body travelling on each
* RESEARCHING  one orbit and a radar-like sweep
* WORKING      a rotating dashed ring
* BUILDING     a segmented ring of six blocks turning, warmer
* ADAPTING     two arcs turning in opposite directions
* LISTENING    rings moving inward, their strength from the real microphone level
* SPEAKING     radial strokes moving outward, their length from the real playback level
* PAUSED       a still, closed ring with two short gaps (waiting for your approval)
* OFFLINE      a dotted grey ring around a dimmed, desaturated sun
* ERROR        a broken ring, slowly pulsing, restrained
* SUCCESS      a single soft ring

Under Reduce motion the shapes are drawn still (time is frozen), so the state is still visible.
"""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen

GOLD = QColor(244, 181, 44)
CHAMPAGNE = QColor(247, 217, 139)
AMBER = QColor(255, 138, 36)
GREY = QColor(146, 151, 166)
ERRC = QColor(240, 120, 96)
COBALT = QColor(125, 184, 255)


def _pen(c: QColor, alpha: float, width: float, style=Qt.PenStyle.SolidLine) -> QPen:
    col = QColor(c)
    col.setAlphaF(max(0.0, min(1.0, alpha)))
    p = QPen(col, width, style)
    p.setCapStyle(Qt.PenCapStyle.RoundCap)
    return p


def draw(p: QPainter, w: float, h: float, state: str, t: float, level: float = 0.0) -> None:
    """Draw the sign for `state` around a sun centred in a w × h area. `t` is seconds; `level` 0..1."""
    cx, cy = w / 2, h / 2
    R = min(w, h) * 0.42  # around the corona
    s = max(1.0, min(w, h) / 230.0)  # line widths scale with size
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(Qt.BrushStyle.NoBrush)
    rect = QRectF(cx - R, cy - R, 2 * R, 2 * R)

    if state == "THINKING":
        for k, tilt in enumerate((25.0, -35.0)):
            p.save()
            p.translate(cx, cy)
            p.rotate(tilt)
            p.setPen(_pen(CHAMPAGNE, 0.35, 1.0 * s))
            p.drawEllipse(QRectF(-R, -R * 0.38, 2 * R, R * 0.76))
            a = t * (1.1 + 0.4 * k) + k * 2.1
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(CHAMPAGNE)
            p.drawEllipse(QPointF(math.cos(a) * R, math.sin(a) * R * 0.38), 3.0 * s, 3.0 * s)
            p.restore()
    elif state == "RESEARCHING":
        p.setPen(_pen(CHAMPAGNE, 0.3, 1.0 * s))
        p.drawEllipse(rect)
        start = -(t * 90.0 % 360.0)
        for i in range(6):
            p.setPen(_pen(CHAMPAGNE, 0.55 - i * 0.08, 2.2 * s))
            p.drawArc(rect, int((start + i * 6) * 16), int(6 * 16))
    elif state == "WORKING":
        p.save()
        p.translate(cx, cy)
        p.rotate(t * 40.0 % 360.0)
        p.setPen(_pen(GOLD, 0.6, 1.6 * s, Qt.PenStyle.DashLine))
        p.drawEllipse(QRectF(-R, -R, 2 * R, 2 * R))
        p.restore()
    elif state == "BUILDING":
        for i in range(6):
            a0 = (t * 55.0 + i * 60.0) % 360.0
            p.setPen(_pen(AMBER, 0.8, 4.0 * s))
            p.drawArc(rect, int(-a0 * 16), int(-34 * 16))
    elif state == "ADAPTING":
        for k, sign in enumerate((1, -1)):
            a0 = (t * 80.0 * sign + k * 180.0) % 360.0
            r2 = R * (1.0 - 0.08 * k)
            p.setPen(_pen(COBALT, 0.65, 2.0 * s))
            p.drawArc(QRectF(cx - r2, cy - r2, 2 * r2, 2 * r2), int(a0 * 16), int(110 * 16))
    elif state == "LISTENING":
        lvl = max(0.15, min(1.0, level))
        for i in range(3):
            phase = (t * 0.7 + i / 3.0) % 1.0
            r2 = R * (1.15 - 0.35 * phase)
            p.setPen(_pen(CHAMPAGNE, (0.25 + 0.6 * lvl) * (1 - phase), 1.4 * s))
            p.drawEllipse(QRectF(cx - r2, cy - r2, 2 * r2, 2 * r2))
    elif state == "SPEAKING":
        lvl = max(0.0, min(1.0, level))
        for i in range(48):
            a = i * math.tau / 48
            wob = 0.55 + 0.45 * math.sin(t * 6.0 + i * 0.9)
            ln = (3 + 22 * lvl * wob) * s
            r1 = R * 0.98
            p.setPen(_pen(GOLD, 0.35 + 0.55 * lvl, 1.6 * s))
            p.drawLine(QPointF(cx + math.cos(a) * r1, cy + math.sin(a) * r1), QPointF(cx + math.cos(a) * (r1 + ln), cy + math.sin(a) * (r1 + ln)))
    elif state in ("PAUSED", "WARNING"):
        p.setPen(_pen(CHAMPAGNE, 0.75, 2.0 * s))
        p.drawArc(rect, int(100 * 16), int(160 * 16))
        p.drawArc(rect, int(280 * 16), int(160 * 16))
    elif state == "OFFLINE":
        p.setPen(_pen(GREY, 0.55, 1.6 * s, Qt.PenStyle.DotLine))
        p.drawEllipse(rect)
    elif state == "ERROR":
        pulse = 0.45 + 0.25 * math.sin(t * 1.6)
        p.setPen(_pen(ERRC, pulse, 2.2 * s))
        p.drawArc(rect, int(20 * 16), int(140 * 16))
        p.drawArc(rect, int(200 * 16), int(140 * 16))
    elif state == "SUCCESS":
        p.setPen(_pen(GOLD, 0.45, 1.4 * s))
        p.drawEllipse(rect)
