"""ORBIT's spatial universe for Prometheus (PyQt6): the layered solar core around the existing GLSL sun, the
atmospheric background, holographic panels, the project-stage bar, the environment switcher, the entry sequence
and the visual-experience settings.

Everything drawn is driven by real state: the core's motion comes from `orbit_motion.visual(state)` for the
page's real state; listening and speaking rings move with the real microphone / playback level; panels show
`orbit_space.panel_content` (real data or an honest empty hint); lines join only real relationships
(`orbit_space.connections`); effects start only from real events. Painting is cheap by design: the background is
cached, the frame timer runs only while ORBIT is visible, and a frame monitor lowers quality on slow machines.
"""

from __future__ import annotations

import html
import math
import random
import time
from typing import Callable, Dict, List, Optional

from PyQt6.QtCore import QEasingCurve, QLineF, QParallelAnimationGroup, QPointF, QPropertyAnimation, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizeGrip,
    QSlider,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..services import orbit_motion as M
from ..services import orbit_space as SP
from . import theme as T

GOLD = QColor(244, 181, 44)
CHAMPAGNE = QColor(247, 217, 139)
STATE_MARK = {"done": "✓", "current": "●", "open": "○"}
TORUS_MAJOR = 2.6   # the particle torus's ring radius, in core radii
TORUS_MINOR = 0.46  # its tube radius
TORUS_RATIO = 0.36  # how flat the ring looks (sin of the viewing tilt)
GEO_VERTS, GEO_EDGES = M.geodesic(1)


def _c(rgb, a: float) -> QColor:
    c = QColor(*rgb)
    c.setAlphaF(max(0.0, min(1.0, a)))
    return c


# ====================================================================== core + connections overlay

class CoreFX(QWidget):
    """Transparent layer over the stage (above the sun, below the panels): concentric tilted rings, the inner
    energy mesh, particles, arcs, the outer shield, audio-reactive rings, event effects and pulses travelling
    along real connections. Mouse events pass through."""

    def __init__(self, stage, settings: M.Settings):
        super().__init__(stage)
        self.stage = stage
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.settings = settings
        self.state = "IDLE"
        self.level = 0.0  # real microphone or playback level
        self.progress = 0.0
        self.t = 0.0
        self.fx = M.Effects(energy=settings.energy)
        self.monitor = M.FrameMonitor()
        self.particles = M.spawn(settings.particle_count())
        self.torus = M.torus(settings.torus_count())
        self.arcs: List[tuple] = []
        self.links: List[tuple] = []  # (QPointF a, QPointF ctrl, QPointF b, kind, key)
        self._last = time.perf_counter()
        self._rnd = random.Random(3)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._frame)

    # --- control ---
    def apply(self, settings: M.Settings) -> None:
        self.settings = settings
        self.fx.energy = settings.energy
        self.particles = M.spawn(settings.particle_count(self.monitor.quality))
        self.torus = M.torus(settings.torus_count(self.monitor.quality))
        self.running(self.isVisible())
        self.update()

    def running(self, on: bool) -> None:
        if on and self.settings.animate():
            self._last = time.perf_counter()
            self.timer.start(self.settings.frame_interval_ms(self.monitor.quality))
        else:
            self.timer.stop()
            self.update()

    def set_state(self, state: str, progress: float = 0.0) -> None:
        self.state, self.progress = state, progress
        self.update()

    def set_level(self, level: float) -> None:
        self.level = max(0.0, min(1.0, float(level)))

    def event_fx(self, event: str) -> None:
        for kind, target in M.effects_for(event):
            self.fx.start(kind, target)
        self.update()

    def _frame(self) -> None:
        now = time.perf_counter()
        dt = min(0.1, now - self._last)
        self._last = now
        t0 = now
        self.t += dt
        v = M.visual(self.state)
        M.advance(self.particles, dt, float(v["flow"]) * self.settings.scale(), float(v["inflow"]))
        self.fx.tick(dt)
        if self.settings.energy and self._rnd.random() < float(v["arcs"]) * dt * self.settings.scale():
            self.arcs.append([self._rnd.uniform(0, math.tau), 0.0])
        for a in self.arcs:
            a[1] += dt
        self.arcs = [a for a in self.arcs if a[1] < 0.35]
        self.stage.update()  # the background parallax and connection pulses live in the stage
        self.update()
        if self.monitor.quality != getattr(self, "_q", 1.0):  # paint cost (measured in paintEvent) changed quality
            self._q = self.monitor.quality
            self.apply(self.settings)

    # --- painting ---
    def _paint_torus(self, p: QPainter, c: QPointF, R: float, v: dict, tone, glow: float, s: float, t: float) -> None:
        pitch = math.asin(TORUS_RATIO)
        spin = t * 0.16 * max(0.15, float(v["ring_speed"]))
        swirl = t * 0.5 * max(0.2, float(v["flow"]) * 2)
        major = R * TORUS_MAJOR
        minor = R * TORUS_MINOR * (1.0 + 0.6 * self.level)
        depth_max = major + minor
        buckets: List[List[QPointF]] = [[], [], [], []]
        for u, w, jit, _size in self.torus:
            x, y, z = M.rotate(M.torus_point(u + spin, w + swirl, jit, major, minor), 0.0, pitch)
            if z < 0 and x * x + y * y < (R * 1.02) ** 2:
                continue  # behind the sun
            k = min(3, int((z / depth_max + 1) * 2))
            buckets[k].append(QPointF(c.x() + x, c.y() - y))
        hot = CHAMPAGNE.getRgb()[:3]
        for k, pts in enumerate(buckets):
            if not pts:
                continue
            col = tone if k < 2 else tuple(int(tone[i] + (hot[i] - tone[i]) * (k - 1) / 2) for i in range(3))
            pen = QPen(_c(col, (0.30 + 0.22 * k) * (0.6 + 0.4 * glow) * (0.75 + 0.25 * s)), 1.3 + 0.6 * k)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawPoints(pts)

    def paintEvent(self, _e) -> None:
        t0 = time.perf_counter()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = self.stage.centre()
        R = self.stage.core_radius()
        v = M.visual(self.state)
        tone = M.TONES.get(str(v["tone"]), M.TONES["solar"])
        s = self.settings.scale()
        glow = float(v["glow"])
        t = self.t if self.settings.animate() else 0.0

        # outer shield: a soft translucent shell
        sh = float(v["shield"]) * (0.6 + 0.4 * s)
        if sh > 0.01:
            g = QRadialGradient(c, R * 3.1)
            g.setColorAt(0.55, _c(tone, 0.0))
            g.setColorAt(0.86, _c(tone, sh * 0.55))
            g.setColorAt(1.0, _c(tone, 0.0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(g))
            p.drawEllipse(c, R * 3.1, R * 3.1)

        # geodesic shell: a slowly turning wireframe sphere around the sun; thinking and building brighten it
        nodes = float(v["nodes"])
        yaw, pitch = t * 0.09, 0.42
        rg = R * 1.45
        verts = [M.rotate(q, yaw, pitch) for q in GEO_VERTS]
        front, back = [], []
        for i, j in GEO_EDGES:
            a3, b3 = verts[i], verts[j]
            line = QLineF(c.x() + a3[0] * rg, c.y() - a3[1] * rg, c.x() + b3[0] * rg, c.y() - b3[1] * rg)
            (front if a3[2] + b3[2] > 0 else back).append(line)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_c(tone, (0.05 + 0.06 * nodes) * (0.6 + 0.4 * s)), 0.7))
        p.drawLines(back)
        p.setPen(QPen(_c(tone, (0.24 + 0.24 * nodes + 0.1 * glow) * (0.6 + 0.4 * s)), 0.9))
        p.drawLines(front)
        dot = QPen(_c(CHAMPAGNE.getRgb()[:3], 0.35 + 0.35 * nodes), 2.2)
        dot.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(dot)
        p.drawPoints([QPointF(c.x() + q[0] * rg, c.y() - q[1] * rg) for q in verts if q[2] > 0])

        # particle torus: the core's luminous ring of dust. It turns with the real state's ring speed, the real
        # microphone / playback level swells its tube, and the sun hides the particles behind it.
        self._paint_torus(p, c, R, v, tone, glow, s, t)

        # concentric orbital rings: different radii, inclinations and directions; a bead travels on each
        n = self.settings.ring_count()
        for i in range(n):
            r = R * (TORUS_MAJOR + 0.75 + 0.4 * i)
            direction = 1 if i % 2 == 0 else -1
            orient = (t * float(v["ring_speed"]) * 6.0 * direction * (1 - 0.12 * i)) + i * 37
            incline = 18 + float(v["tilt"]) * ((i % 3) - 1) * 0.6 + 50
            ratio = max(0.18, math.cos(math.radians(incline)))
            p.save()
            p.translate(c)
            p.rotate(orient)
            alpha = (0.18 + 0.32 * glow) * (1 - 0.13 * i) * (0.55 + 0.45 * s)
            style = Qt.PenStyle.DashLine if self.state in ("PAUSED", "WARNING") and i == 0 else Qt.PenStyle.SolidLine
            if self.state == "ERROR" and i == 0:
                p.setPen(QPen(_c(tone, alpha), 1.4))
                p.drawArc(QRectF(-r, -r * ratio, 2 * r, 2 * r * ratio), 20 * 16, 140 * 16)
                p.drawArc(QRectF(-r, -r * ratio, 2 * r, 2 * r * ratio), 200 * 16, 140 * 16)
            else:
                p.setPen(QPen(_c(tone, alpha), 1.1 if i else 1.5, style))
                p.drawEllipse(QRectF(-r, -r * ratio, 2 * r, 2 * r * ratio))
            a = t * (0.6 + 0.25 * i) * direction * max(0.2, float(v["ring_speed"]) / 2) + i
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_c(tone, min(1.0, alpha * 2.4)))
            p.drawEllipse(QPointF(math.cos(a) * r, math.sin(a) * r * ratio), 2.6, 2.6)
            p.restore()

        # particles: an orbiting field that flows in when listening and out when speaking
        for q in self.particles:
            x = c.x() + math.cos(q.angle) * q.radius * R
            y = c.y() + math.sin(q.angle) * q.radius * R * 0.62
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_c(tone, (0.15 + 0.55 * q.depth) * (0.4 + 0.6 * glow)))
            p.drawEllipse(QPointF(x, y), q.size * 0.7, q.size * 0.7)

        # audio-reactive ring: real microphone level (listening) or real playback level (speaking)
        if self.state in ("LISTENING", "SPEAKING") and self.level > 0.01:
            path = QPainterPath()
            segs = 72
            for k in range(segs + 1):
                ang = k * math.tau / segs
                wob = math.sin(ang * 6 + t * (8 if self.state == "SPEAKING" else 5)) * self.level * R * 0.22
                rr = R * 1.18 + wob
                pt = QPointF(c.x() + math.cos(ang) * rr, c.y() + math.sin(ang) * rr)
                path.moveTo(pt) if k == 0 else path.lineTo(pt)
            p.setPen(QPen(_c(tone, 0.4 + 0.5 * self.level), 1.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)

        # core pulse
        if float(v["pulse"]) > 0 and self.settings.animate():
            ph = (t * float(v["pulse"])) % 1.0
            p.setPen(QPen(_c(tone, (1 - ph) * 0.35 * s), 1.2))
            p.drawEllipse(c, R * (1.05 + 0.6 * ph), R * (1.05 + 0.6 * ph))

        # electrical arcs (energy effects only)
        for ang, age in self.arcs:
            p.setPen(QPen(_c((255, 236, 190), (1 - age / 0.35) * 0.8), 1.1))
            path = QPainterPath(QPointF(c.x() + math.cos(ang) * R * 1.02, c.y() + math.sin(ang) * R * 1.02))
            for k in range(1, 6):
                rr = R * (1.02 + 0.12 * k)
                jit = self._rnd.uniform(-0.09, 0.09)
                path.lineTo(QPointF(c.x() + math.cos(ang + jit) * rr, c.y() + math.sin(ang + jit) * rr))
            p.drawPath(path)

        # event effects
        span = max(self.width(), self.height())
        for e in self.fx.active():
            k = e.progress
            if e.kind == "shockwave":
                rr = R * 1.1 + k * span * 0.45
                p.setPen(QPen(_c(tone, (1 - k) * 0.55 * e.strength), 2.0 * (1 - k) + 0.5))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(c, rr, rr * 0.92)
            elif e.kind == "celebrate":
                for j in range(28):
                    ang = j * math.tau / 28 + j * 0.3
                    rr = R * (1.2 + 3.2 * k)
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(_c((255, 214, 120), (1 - k) * 0.9))
                    p.drawEllipse(QPointF(c.x() + math.cos(ang) * rr, c.y() + math.sin(ang) * rr * 0.8), 2.4 * (1 - k) + 0.6, 2.4 * (1 - k) + 0.6)
        # pulses travelling along the real (curved) connections; a real event boosts its line
        for a, ctrl, b, kind, key in self.links:
            boosted = any(e.kind == "pulse" and e.target == key for e in self.fx.active())
            ph = ((t * 0.35) + (hash(key) % 100) / 100.0) % 1.0
            x, y = M.bezier((a.x(), a.y()), (ctrl.x(), ctrl.y()), (b.x(), b.y()), ph)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_c(tone, 0.9 if boosted else 0.5))
            rad = 3.4 if boosted else 2.2
            p.drawEllipse(QPointF(x, y), rad, rad)
        p.end()
        self.monitor.add((time.perf_counter() - t0) * 1000 * 2.2)  # paint dominates frame cost


def paint_background(p: QPainter, stage, cache: Dict[str, object], t: float, settings: M.Settings) -> None:
    """A dark spatial atmosphere: deep gradient, a faint hexagonal grid and distant points (cached), drifting
    gently with the camera setting; slow energy currents in immersive depth."""
    w, h = stage.width(), stage.height()
    key = (w, h, settings.depth)
    if cache.get("key") != key:
        pm = QPixmap(w + 40, h + 40)
        pm.fill(QColor(T.BG))
        q = QPainter(pm)
        q.setRenderHint(QPainter.RenderHint.Antialiasing)
        g = QRadialGradient(QPointF(pm.width() / 2, pm.height() / 2), max(w, h) * 0.7)
        g.setColorAt(0.0, QColor(28, 22, 14))
        g.setColorAt(0.5, QColor(14, 13, 16))
        g.setColorAt(1.0, QColor(T.BG))
        q.fillRect(pm.rect(), QBrush(g))
        size = 34.0
        q.setPen(QPen(_c((244, 181, 44), 0.045), 0.8))
        dx, dy = size * 1.5, size * math.sqrt(3)
        for col in range(int(pm.width() / dx) + 2):
            for row in range(int(pm.height() / dy) + 2):
                cx = col * dx
                cy = row * dy + (dy / 2 if col % 2 else 0)
                hexp = [QPointF(cx + size * math.cos(math.radians(60 * k)), cy + size * math.sin(math.radians(60 * k))) for k in range(6)]
                q.drawPolyline(hexp + [hexp[0]])
        rnd = random.Random(11)
        q.setPen(Qt.PenStyle.NoPen)
        for _ in range(int(pm.width() * pm.height() / 9000)):
            q.setBrush(_c((247, 230, 200), rnd.uniform(0.05, 0.35)))
            q.drawEllipse(QPointF(rnd.uniform(0, pm.width()), rnd.uniform(0, pm.height())), rnd.uniform(0.3, 1.2), rnd.uniform(0.3, 1.2))
        q.end()
        cache["key"], cache["pm"] = key, pm
    amp = M.CAMERA[settings.camera] * (1.0 if settings.animate() else 0.0)
    ox = -20 + math.sin(t * 0.07) * 20 * amp * 20
    oy = -20 + math.cos(t * 0.05) * 20 * amp * 20
    cache["off"] = (int(ox), int(oy))
    p.drawPixmap(int(ox), int(oy), cache["pm"])
    if settings.depth == "immersive":
        p.setPen(QPen(_c((255, 160, 60), 0.05), 1.2))
        for k in range(3):
            path = QPainterPath()
            base = h * (0.25 + 0.25 * k)
            for xx in range(0, w + 40, 40):
                y = base + math.sin(xx / 180.0 + t * 0.12 * (k + 1) + k) * 26
                path.moveTo(xx, y) if xx == 0 else path.lineTo(xx, y)
            p.drawPath(path)


# ====================================================================== holographic panels

#: each panel's accent (Prometheus stays solar: gold, amber, bronze, champagne; ideas carry a soft violet so
#: they read as possibilities rather than commitments; risks a warm red)
PANEL_ACCENT = {
    "brief": (247, 217, 139), "ideas": (178, 146, 255), "files": (244, 181, 44), "plan": (255, 170, 60),
    "next": (255, 196, 110), "activity": (214, 196, 160), "structure": (205, 150, 90), "operations": (255, 138, 36),
    "approvals": (247, 217, 139), "research": (247, 217, 139), "questions": (226, 204, 160), "risks": (240, 110, 90),
}
CHAMFER = 12


def chamfer_path(r: QRectF, k: float = CHAMFER) -> QPainterPath:
    """A panel outline with the top-left and bottom-right corners cut at 45°."""
    path = QPainterPath(QPointF(r.left() + k, r.top()))
    path.lineTo(r.right(), r.top())
    path.lineTo(r.right(), r.bottom() - k)
    path.lineTo(r.right() - k, r.bottom())
    path.lineTo(r.left(), r.bottom())
    path.lineTo(r.left(), r.top() + k)
    path.closeSubpath()
    return path


def paint_icon(p: QPainter, kind: str, r: QRectF, col: QColor) -> None:
    """Small line icons for the panels, drawn as vectors so they look the same on every system font."""
    p.save()
    p.translate(r.topLeft())
    s = r.width() / 14.0
    p.scale(s, s)
    pen = QPen(col, 1.3)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    P = QPointF
    if kind == "files":
        p.drawPolygon([P(1, 3), P(5.5, 3), P(7, 4.6), P(13, 4.6), P(13, 12), P(1, 12)])
    elif kind == "ideas":
        p.drawEllipse(P(7, 5.6), 4.2, 4.2)
        p.drawLine(P(5.2, 11), P(8.8, 11))
        p.drawLine(P(5.8, 13), P(8.2, 13))
    elif kind == "brief":
        p.drawRect(QRectF(2.5, 1, 9, 12))
        for y in (4.5, 7, 9.5):
            p.drawLine(P(4.5, y), P(9.5, y))
    elif kind in ("plan", "operations"):
        for y in (2.5, 7, 11.5):
            p.drawRect(QRectF(1, y - 1.3, 2.6, 2.6))
            p.drawLine(P(5.5, y), P(13, y))
    elif kind == "next":
        p.drawLine(P(1.5, 7), P(12, 7))
        p.drawPolyline([P(8, 3), P(12.5, 7), P(8, 11)])
    elif kind == "activity":
        p.drawPolyline([P(1, 7), P(4, 7), P(5.5, 2.5), P(8.5, 11.5), P(10, 7), P(13, 7)])
    elif kind == "approvals":
        p.drawPolygon([P(7, 1), P(12.5, 3), P(12, 8), P(7, 13), P(2, 8), P(1.5, 3)])
        p.drawPolyline([P(4.6, 7), P(6.4, 8.8), P(9.6, 5.2)])
    elif kind == "research":
        p.drawEllipse(P(6, 6), 4.2, 4.2)
        p.drawLine(P(9.2, 9.2), P(13, 13))
    elif kind == "questions":
        path = QPainterPath(P(4, 4.6))
        path.cubicTo(P(4, 0.6), P(10.5, 0.6), P(10.5, 4.6))
        path.cubicTo(P(10.5, 7), P(7, 7), P(7, 9.4))
        p.drawPath(path)
        p.drawPoint(P(7, 12.4))
    elif kind == "risks":
        p.drawPolygon([P(7, 1.5), P(13, 12.5), P(1, 12.5)])
        p.drawLine(P(7, 5.5), P(7, 8.8))
        p.drawPoint(P(7, 10.8))
    elif kind == "structure":
        for q in (P(3, 3), P(11, 3), P(7, 11.5)):
            p.drawEllipse(q, 1.8, 1.8)
        p.drawLine(P(4.6, 4.2), P(6.2, 9.8))
        p.drawLine(P(9.4, 4.2), P(7.8, 9.8))
    p.restore()


class HoloPanel(QFrame):
    """A floating translucent panel: drag by its title, resize from the corner, collapse, expand, hide. Its
    content is real data (or the honest empty hint). Clicking a link inside asks the page to act."""

    moved = pyqtSignal(str, QRect)
    state_changed = pyqtSignal(str, str)  # pid, "collapsed"/"expanded"/"hidden"/"restored"
    link = pyqtSignal(str, str)  # pid, href
    selected = pyqtSignal(str)

    def __init__(self, pid: str, title: str, parent):
        super().__init__(parent)
        self.pid = pid
        self.setObjectName("holo")
        self.setAccessibleName(f"{title} panel")
        self.collapsed = False
        self.expanded = False
        self._drag = None
        self._restore: Optional[QRect] = None
        self._focus = False
        self.accent = QColor(*PANEL_ACCENT.get(pid, (244, 181, 44)))
        self.setStyleSheet("QFrame#holo { background: transparent; border: none; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 7, 7, 6)
        lay.setSpacing(4)
        head = QHBoxLayout()
        head.addSpacing(20)  # the panel's icon is painted here
        self.title = QLabel(title)
        self.title.setStyleSheet(f"color: {T.TEXT}; font-size: 9.5pt; font-weight: 600; background: transparent; border: none;")
        self.title.setMinimumWidth(self.title.sizeHint().width())
        self.count = QLabel("")
        self.count.setStyleSheet(f"color: {T.TEXT_FAINT}; font-size: 8pt; background: transparent; border: none;")
        head.addWidget(self.title)
        head.addWidget(self.count)
        head.addStretch(1)
        self.extra = QHBoxLayout()
        head.addLayout(self.extra)
        for sym, tip, fn in (("▾", "Collapse or open", self.toggle_collapse), ("⤢", "Expand or restore", self.toggle_expand), ("×", "Hide panel (its data stays)", self.hide_panel)):
            b = QToolButton()
            b.setText(sym)
            b.setToolTip(tip)
            b.setAccessibleName(f"{tip}: {title}")
            b.setAutoRaise(True)
            b.setStyleSheet(f"QToolButton {{ color: {T.TEXT_SECONDARY}; background: transparent; border: none; padding: 0 1px; }} QToolButton:hover {{ color: {T.ACCENT}; }}")
            b.clicked.connect(fn)
            head.addWidget(b)
        lay.addLayout(head)
        self.body = QTextBrowser()
        self.body.setOpenLinks(False)
        self.body.anchorClicked.connect(lambda u: self.link.emit(self.pid, u.toString()))
        self.body.setStyleSheet(f"QTextBrowser {{ background: transparent; border: none; color: {T.TEXT}; }}")
        lay.addWidget(self.body, 1)
        # footer: the panel's real actions (left) and the resize grip (right)
        self.footer = QWidget()
        self.footer.setStyleSheet("background: transparent;")
        grip_row = QHBoxLayout(self.footer)
        grip_row.setContentsMargins(0, 0, 0, 0)
        grip_row.setSpacing(6)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(6)
        grip_row.addLayout(self.actions)
        grip_row.addStretch(1)
        self.grip = QSizeGrip(self)
        self._resizing = False
        self.grip.installEventFilter(self)
        grip_row.addWidget(self.grip)
        lay.addWidget(self.footer)
        self.opacity = QGraphicsOpacityEffect(self)
        self.opacity.setOpacity(1.0)
        self.setGraphicsEffect(self.opacity)
        self._anim = None

    def add_action(self, text: str, tip: str, fn: Callable[[], None], primary: bool = False) -> QPushButton:
        """A real action at the foot of the panel (e.g. "Compare ideas", "+ Add")."""
        a = self.accent
        rgb = f"{a.red()},{a.green()},{a.blue()}"
        b = QPushButton(text)
        b.setToolTip(tip)
        b.setAccessibleName(tip)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        fill = f"rgba({rgb},0.22)" if primary else "rgba(255,255,255,0.03)"
        b.setStyleSheet(f"QPushButton {{ color: {T.TEXT}; background: {fill}; border: 1px solid rgba({rgb},0.55); border-radius: 12px; "
                        f"padding: 3px 11px; font-size: 8.5pt; min-width: 0; }} QPushButton:hover {{ background: rgba({rgb},0.32); }} "
                        f"QPushButton:focus {{ border: 1px solid {T.FOCUS}; }}")
        b.clicked.connect(fn)
        b.ensurePolished()
        b.setMinimumWidth(b.sizeHint().width() + 6)  # never clipped: the label is the promise of what it does
        self.actions.addWidget(b)
        return b

    def paintEvent(self, _e) -> None:
        """The chamfered holographic frame: a dark translucent glass, a faint accent wash behind the title, a thin
        edge (brighter when focused), bright accent brackets on the cut corners and the panel's icon."""
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        path = chamfer_path(r)
        g = QLinearGradient(0, 0, 0, r.height())
        g.setColorAt(0.0, QColor(30, 26, 21, 242))
        g.setColorAt(1.0, QColor(12, 13, 18, 236))
        p.fillPath(path, QBrush(g))
        a = self.accent
        wash = QRadialGradient(QPointF(0, 0), max(80.0, r.width() * 0.7))
        wash.setColorAt(0.0, _c(a.getRgb()[:3], 0.13))
        wash.setColorAt(1.0, _c(a.getRgb()[:3], 0.0))
        p.fillPath(path, QBrush(wash))
        p.setPen(QPen(_c(a.getRgb()[:3], 0.7 if self._focus else 0.26), 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        k = CHAMFER
        pen = QPen(_c(a.getRgb()[:3], 0.95 if self._focus else 0.75), 1.6)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setPen(pen)
        p.drawPolyline([QPointF(r.left(), r.top() + k + 10), QPointF(r.left(), r.top() + k), QPointF(r.left() + k, r.top()), QPointF(r.left() + k + 22, r.top())])
        p.drawPolyline([QPointF(r.right(), r.bottom() - k - 10), QPointF(r.right(), r.bottom() - k), QPointF(r.right() - k, r.bottom()), QPointF(r.right() - k - 22, r.bottom())])
        paint_icon(p, self.pid, QRectF(13, 9, 14, 14), _c(a.getRgb()[:3], 0.95))
        p.end()

    def set_content(self, content: Dict[str, object], provisional: bool = False) -> None:
        items = content["items"]
        self.count.setText(f"{len(items)}" if items else "")
        if not items:
            self.body.setHtml(f"<p style='color:{T.TEXT_FAINT}'>{html.escape(str(content['empty']))}</p>")
            return
        rows = []
        for it in items:
            mark = {"completed": "✓", "done": "✓", "running": "▶", "failed": "!", "awaiting_approval": "?", "blocked": "⊘", "ready": "○", "question": "?", "risk": "⚠", "written": "✎"}.get(it["state"], "•")
            col = {"completed": T.OK, "done": T.OK, "failed": T.ERR, "awaiting_approval": T.HIGHLIGHT, "running": T.SECONDARY_ACCENT, "risk": T.WARN}.get(it["state"], T.ACCENT)
            text = html.escape(it["text"])
            if it["ref"]:
                kind = "file" if self.pid == "files" else "approve" if it["state"] == "awaiting_approval" and self.pid in ("approvals", "next") else "task"
                text = f"<a href='{kind}:{html.escape(it['ref'])}' style='color:{T.TEXT}; text-decoration:none'>{text}</a>"
            style = "font-size:11pt; font-weight:600" if it["state"] == "title" else ""
            sub = f"<br><span style='color:{T.TEXT_FAINT}; font-size:8.5pt'>{html.escape(it['sub'])}</span>" if it["sub"] else ""
            rows.append(f"<div style='margin-bottom:6px; {style}'><span style='color:{col}'>{mark}</span> {text}{sub}</div>")
        tag = f"<p style='color:{T.TEXT_FAINT}; font-size:8pt'>arriving…</p>" if provisional else ""
        self.body.setHtml(tag + "".join(rows))

    def set_compact(self, on: bool) -> None:
        """Title bar only (small stages); expanding opens it over the stage."""
        if not self.expanded and not self.collapsed:
            self.body.setVisible(not on)
            self.footer.setVisible(not on)

    def settle(self) -> None:
        """Finish any running animation at once (e.g. the stage was resized mid-animation)."""
        if self._anim is not None:
            self._anim.stop()
            self._anim = None
        self.opacity.setOpacity(1.0)

    def set_html(self, text: str) -> None:
        self.body.setHtml(text)

    def focus(self, on: bool) -> None:
        self._focus = on
        self.update()

    # --- interaction ---
    def mousePressEvent(self, e) -> None:
        self.raise_()
        self.selected.emit(self.pid)
        if e.position().y() < 28:
            self._drag = (e.globalPosition(), self.geometry())

    def mouseMoveEvent(self, e) -> None:
        if self._drag is None:
            return
        start, geo = self._drag
        d = e.globalPosition() - start
        r = QRect(geo)
        r.moveTo(int(geo.x() + d.x()), int(geo.y() + d.y()))
        par = self.parentWidget().rect()
        r.moveLeft(max(-r.width() + 60, min(par.width() - 60, r.left())))
        r.moveTop(max(0, min(par.height() - 30, r.top())))
        self.setGeometry(r)
        self.parentWidget().update()

    def mouseReleaseEvent(self, e) -> None:
        if self._drag is not None:
            self._drag = None
            self.moved.emit(self.pid, self.geometry())

    def mouseDoubleClickEvent(self, e) -> None:
        if e.position().y() < 28:
            self.toggle_expand()

    def eventFilter(self, obj, ev) -> bool:
        from PyQt6.QtCore import QEvent

        if obj is self.grip and ev.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
            self._resizing = ev.type() == QEvent.Type.MouseButtonPress
        return False

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        # only the owner's own resize (dragging the grip) is remembered; layout changes made by ORBIT itself
        # (compact chips on a small stage, overlap avoidance, animations) must never overwrite the saved layout
        from PyQt6.QtWidgets import QApplication

        user = self._resizing and bool(QApplication.mouseButtons() & Qt.MouseButton.LeftButton)
        if user and not self.expanded and not self.collapsed and self.isVisible() and e.oldSize().isValid():
            self.moved.emit(self.pid, self.geometry())

    def toggle_collapse(self) -> None:
        self.collapsed = not self.collapsed
        self.body.setVisible(not self.collapsed)
        self.footer.setVisible(not self.collapsed)
        self.state_changed.emit(self.pid, "collapsed" if self.collapsed else "restored")

    def toggle_expand(self) -> None:
        par = self.parentWidget().rect()
        if not self.expanded:
            self._restore = self.geometry()
            target = par.adjusted(int(par.width() * 0.12), int(par.height() * 0.08), -int(par.width() * 0.12), -int(par.height() * 0.08))
            self.expanded = True
            self.raise_()
            self.state_changed.emit(self.pid, "expanded")
        else:
            target = self._restore or self.geometry()
            self.expanded = False
            self.state_changed.emit(self.pid, "restored")
        if self.expanded:
            self.body.setVisible(True)
        self.animate_to(target, 260)

    def hide_panel(self) -> None:
        self.state_changed.emit(self.pid, "hidden")

    def animate_to(self, target: QRect, ms: int, reduced: bool = False) -> None:
        if reduced or ms <= 0:
            self.setGeometry(target)
            return
        a = QPropertyAnimation(self, b"geometry", self)
        a.setDuration(ms)
        a.setEasingCurve(QEasingCurve.Type.OutCubic)
        a.setStartValue(self.geometry())
        a.setEndValue(target)
        a.valueChanged.connect(lambda _v: self.parentWidget().update())
        self._anim = a
        a.start()

    def materialise(self, origin: QPointF, target: QRect, ms: int, delay: int, reduced: bool) -> None:
        """Assemble from the core outwards: grow from the core point while fading in."""
        if reduced or ms <= 0:
            self.setGeometry(target)
            self.opacity.setOpacity(1.0)
            self.show()
            return
        start = QRect(int(origin.x()) - 10, int(origin.y()) - 6, 20, 12)
        self.setGeometry(start)
        self.opacity.setOpacity(0.0)
        self.show()
        group = QParallelAnimationGroup(self)
        g = QPropertyAnimation(self, b"geometry")
        g.setDuration(ms)
        g.setEasingCurve(QEasingCurve.Type.OutBack)
        g.setStartValue(start)
        g.setEndValue(target)
        o = QPropertyAnimation(self.opacity, b"opacity")
        o.setDuration(ms)
        o.setStartValue(0.0)
        o.setEndValue(1.0)
        g.valueChanged.connect(lambda _v: self.parentWidget().update())
        group.addAnimation(g)
        group.addAnimation(o)
        self._anim = group
        # start later, unless settle() (a resize, an environment switch) has finished this panel meanwhile
        QTimer.singleShot(delay, lambda: group.start() if self._anim is group else None)

    def dissolve(self, reduced: bool, done: Callable[[], None]) -> None:
        if reduced:
            self.hide()
            done()
            return
        o = QPropertyAnimation(self.opacity, b"opacity", self)
        o.setDuration(220)
        o.setStartValue(self.opacity.opacity())
        o.setEndValue(0.0)
        o.finished.connect(lambda: (self.hide(), self.opacity.setOpacity(1.0), done()))
        self._anim = o
        o.start()


# ====================================================================== stage bar and environment switcher

class StageBar(QWidget):
    """OVERVIEW → IDEAS → PLAN → DESIGN → BUILD → REVIEW → COMPLETE, each with its real state (✓ done,
    ● current, ○ open) and why; clicking a stage takes you to where its work happens."""

    clicked = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.buttons: Dict[str, QPushButton] = {}
        for i, (key, name) in enumerate(SP.STAGES):
            if i:
                arrow = QLabel("→")
                arrow.setStyleSheet(f"color: {T.TEXT_FAINT};")
                lay.addWidget(arrow)
            b = QPushButton(name.upper())
            b.setFlat(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.clicked.emit(k))
            self.buttons[key] = b
            lay.addWidget(b)
        lay.addStretch(1)

    def set_stages(self, stages: List[Dict[str, str]]) -> None:
        for st in stages:
            b = self.buttons[st["key"]]
            col = {"done": T.OK, "current": T.ACCENT, "open": T.TEXT_FAINT}[st["state"]]
            b.setText(f"{STATE_MARK[st['state']]} {st['name'].upper()}")
            b.setToolTip(f"{st['name']}: {st['state']} — {st['why']}")
            b.setAccessibleName(f"Stage {st['name']}, {st['state']}: {st['why']}")
            weight = 700 if st["state"] == "current" else 500
            b.setStyleSheet(f"QPushButton {{ color: {col}; background: transparent; border: none; letter-spacing: 1px; font-size: 8pt; font-weight: {weight}; padding: 3px 4px; min-width: 0; }} QPushButton:hover {{ color: {T.HIGHLIGHT}; }}")


class EnvBar(QWidget):
    changed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.buttons: Dict[str, QPushButton] = {}
        for key, env in SP.ENVIRONMENTS.items():
            b = QPushButton(env["name"].upper())
            b.setCheckable(True)
            b.setToolTip(env["purpose"])
            b.setAccessibleName(f"ORBIT {env['name']}: {env['purpose']}")
            b.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
            self.buttons[key] = b
            lay.addWidget(b)

    def set_env(self, env: str) -> None:
        for k, b in self.buttons.items():
            b.setChecked(k == env)
            b.setStyleSheet(f"QPushButton {{ letter-spacing: 1px; font-size: 8pt; padding: 3px 8px; border-radius: 6px; min-width: 0; "
                            f"color: {T.ON_ACCENT if k == env else T.TEXT_SECONDARY}; background: {T.ACCENT if k == env else 'transparent'}; "
                            f"border: 1px solid {T.ACCENT if k == env else T.BORDER_STRONG}; }}")


# ====================================================================== entry sequence

class StageTrack(QWidget):
    """The immersive title: "Projects / ‹project›" over a gently curved track of the seven stages. Each dot
    shows the stage's real state (filled = done, ringed = current, hollow = open); clicking one (or arrow keys +
    Enter) goes where that stage's work happens."""

    clicked = pyqtSignal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAccessibleName("Project stages")
        self.title = ""
        self.stages: List[Dict[str, str]] = []
        self.cursor = -1

    def set_data(self, title: str, stages: List[Dict[str, str]]) -> None:
        self.title, self.stages = title, stages
        cur = next((st for st in stages if st["state"] == "current"), None)
        self.setAccessibleDescription(f"{title or 'New project'}. " + (f"Current stage: {cur['name']}, {cur['why']}" if cur else "All stages done"))
        self.update()

    def _dots(self) -> List[QPointF]:
        n = max(1, len(self.stages))
        w, h = self.width(), self.height()
        left, right, base, sag = 40.0, w - 40.0, h - 30.0, 12.0
        out = []
        for i in range(n):
            f = i / max(1, n - 1)
            out.append(QPointF(left + (right - left) * f, base - sag + 4 * sag * (f - 0.5) ** 2))  # a shallow smile
        return out

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        f = QFont(self.font())
        f.setPointSizeF(13.0)
        f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f)
        head = "Projects  /  "
        name = self.title or "New project"
        fm = p.fontMetrics()
        name = fm.elidedText(name, Qt.TextElideMode.ElideRight, max(80, self.width() - fm.horizontalAdvance(head) - 40))
        total = fm.horizontalAdvance(head) + fm.horizontalAdvance(name)
        x = (self.width() - total) / 2
        p.setPen(QColor(T.TEXT_SECONDARY))
        p.drawText(QPointF(x, 22), head)
        p.setPen(QColor(T.TEXT))
        p.drawText(QPointF(x + fm.horizontalAdvance(head), 22), name)
        dots = self._dots()
        if len(dots) > 1:
            path = QPainterPath(dots[0])
            for a, b in zip(dots, dots[1:]):
                path.quadTo(QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2 + 3), b)
            p.setPen(QPen(QColor(244, 181, 44, 70), 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
        f2 = QFont(self.font())
        f2.setPointSizeF(7.5)
        f2.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.0)
        p.setFont(f2)
        for i, (pt, st) in enumerate(zip(dots, self.stages)):
            state = st["state"]
            if state == "current":
                g = QRadialGradient(pt, 14)
                g.setColorAt(0.0, QColor(244, 181, 44, 120))
                g.setColorAt(1.0, QColor(244, 181, 44, 0))
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(g))
                p.drawEllipse(pt, 14, 14)
                p.setPen(QPen(GOLD, 1.6))
                p.setBrush(QColor(20, 18, 14))
                p.drawEllipse(pt, 6, 6)
                p.setBrush(GOLD)
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(pt, 2.6, 2.6)
            elif state == "done":
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(244, 181, 44, 200))
                p.drawEllipse(pt, 4.2, 4.2)
            else:
                p.setPen(QPen(QColor(T.TEXT_FAINT), 1.1))
                p.setBrush(QColor(12, 13, 18))
                p.drawEllipse(pt, 4.2, 4.2)
            if i == self.cursor and self.hasFocus():
                p.setPen(QPen(QColor(T.FOCUS), 1.2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(pt, 9, 9)
            label = st["name"].upper()
            p.setPen(QColor(T.HIGHLIGHT if state == "current" else T.TEXT_SECONDARY if state == "done" else T.TEXT_FAINT))
            tw = p.fontMetrics().horizontalAdvance(label)
            p.drawText(QPointF(pt.x() - tw / 2, pt.y() + 20), label)
        p.end()

    def _hit(self, pos: QPointF) -> int:
        for i, pt in enumerate(self._dots()):
            if abs(pt.x() - pos.x()) < 24 and abs(pt.y() - pos.y()) < 22:
                return i
        return -1

    def mouseMoveEvent(self, e) -> None:
        i = self._hit(e.position())
        if 0 <= i < len(self.stages):
            st = self.stages[i]
            self.setToolTip(f"{st['name']}: {st['state']} — {st['why']}")
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.setToolTip("")
            self.unsetCursor()

    def mousePressEvent(self, e) -> None:
        i = self._hit(e.position())
        if 0 <= i < len(self.stages):
            self.clicked.emit(self.stages[i]["key"])

    def keyPressEvent(self, e) -> None:
        n = len(self.stages)
        if not n:
            return super().keyPressEvent(e)
        if e.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            self.cursor = (max(0, self.cursor) + (1 if e.key() == Qt.Key.Key_Right else -1)) % n
            self.update()
        elif e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space) and self.cursor >= 0:
            self.clicked.emit(self.stages[self.cursor]["key"])
        else:
            super().keyPressEvent(e)


def caption_text(who: str, text: str, limit: int = 180) -> str:
    """One readable line for the caption bar from a real transcript line: markdown and plan blocks removed,
    whitespace collapsed; a long reply shows its end (the part being said now)."""
    import re

    t = re.sub(r"```.*?(```|$)", " ", text or "", flags=re.S)
    t = re.sub(r"[*_#>`]+", "", t)
    t = " ".join(t.split())
    if not t:
        return ""
    if len(t) > limit:
        t = "…" + t[-(limit - 1):].lstrip()
    return f"{who}: {t}" if who else t


class Hud:
    """The immersive heads-up layer over the ORBIT stage: status chip (top left), project title with the stage
    track (top centre), environment / conversation / visual settings / exit (top right), a talk button and
    message field (bottom left) and a caption of the latest real line (bottom centre). Only shown while ORBIT is
    immersive; every control does what the page's own controls do."""

    TOP, BOTTOM = 84, 58

    def __init__(self, stage: QWidget, on_stage: Callable[[str], None], on_send: Callable[[str], None], on_talk: Callable[[], None],
                 on_env: Callable[[str], None], on_conversation: Callable[[], None], on_visual: Callable[[], None], on_exit: Callable[[], None]):
        self.stage = stage
        self.visible = False
        self.chip = QLabel(stage)
        self.chip.setAccessibleName("ORBIT status")
        self.track = StageTrack(stage)
        self.track.clicked.connect(on_stage)
        self.caption = QLabel(stage)
        self.caption.setAccessibleName("Latest line")
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption.setStyleSheet(f"QLabel {{ color: {T.TEXT}; background: rgba(12,13,18,0.82); border: 1px solid rgba(244,181,44,0.22); "
                                   f"border-radius: 15px; padding: 6px 16px; font-size: 9.5pt; }}")
        pill = (f"QPushButton, QToolButton {{ color: {T.TEXT}; background: rgba(12,13,18,0.82); border: 1px solid rgba(244,181,44,0.30); "
                f"border-radius: 14px; padding: 4px 12px; font-size: 8.5pt; min-width: 0; }} "
                f"QPushButton:hover, QToolButton:hover {{ background: rgba(244,181,44,0.18); }} "
                f"QPushButton:checked {{ background: rgba(244,181,44,0.85); color: {T.ON_ACCENT}; }} "
                f"QPushButton:focus, QToolButton:focus {{ border: 1px solid {T.FOCUS}; }} QToolButton::menu-indicator {{ image: none; }}")
        self.tools = QWidget(stage)
        self.tools.setStyleSheet(pill)
        tl = QHBoxLayout(self.tools)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(6)
        from PyQt6.QtWidgets import QMenu

        self.env_btn = QToolButton()
        self.env_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.env_btn.setAccessibleName("ORBIT environment")
        menu = QMenu(self.env_btn)
        for key, env in SP.ENVIRONMENTS.items():
            menu.addAction(env["name"], lambda k=key: on_env(k)).setToolTip(env["purpose"])
        self.env_btn.setMenu(menu)
        tl.addWidget(self.env_btn)
        self.conv_btn = QPushButton("Conversation")
        self.conv_btn.setCheckable(True)
        self.conv_btn.setToolTip("Show or hide the conversation beside ORBIT")
        self.conv_btn.clicked.connect(on_conversation)
        tl.addWidget(self.conv_btn)
        gear = QPushButton("⚙")
        gear.setToolTip("Visual experience: intensity, particles, depth, camera, sounds")
        gear.setAccessibleName("Visual experience settings")
        gear.clicked.connect(on_visual)
        tl.addWidget(gear)
        ex = QPushButton("Exit")
        ex.setToolTip("Leave immersive ORBIT (Esc)")
        ex.setAccessibleName("Exit immersive ORBIT")
        ex.clicked.connect(on_exit)
        tl.addWidget(ex)
        self.composer = QWidget(stage)
        self.composer.setStyleSheet(pill + f" QLineEdit {{ color: {T.TEXT}; background: rgba(12,13,18,0.82); border: 1px solid rgba(244,181,44,0.30); "
                                    f"border-radius: 14px; padding: 4px 12px; font-size: 9pt; }} QLineEdit:focus {{ border: 1px solid {T.FOCUS}; }}")
        cl = QHBoxLayout(self.composer)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(6)
        self.talk_btn = QPushButton("Talk")
        self.talk_btn.setToolTip("Talk to Prometheus (the microphone opens only while you talk)")
        self.talk_btn.setAccessibleName("Talk to Prometheus")
        self.talk_btn.clicked.connect(on_talk)
        cl.addWidget(self.talk_btn)
        from PyQt6.QtWidgets import QLineEdit

        self.field = QLineEdit()
        self.field.setPlaceholderText("Message Prometheus…")
        self.field.setAccessibleName("Message Prometheus")
        self.field.returnPressed.connect(lambda: (on_send(self.field.text()), self.field.clear()))
        cl.addWidget(self.field, 1)
        self.widgets = [self.chip, self.track, self.caption, self.tools, self.composer]
        for w in self.widgets:
            w.hide()
        self.set_status("Idle", T.TEXT_SECONDARY, "")
        self.set_env("command")

    def show(self, on: bool) -> None:
        self.visible = on
        for w in self.widgets:
            w.setVisible(on and (w is not self.caption or bool(self.caption.text())))
            if on:
                w.raise_()
        self.place()

    def reserve(self):
        return (self.TOP, self.BOTTOM) if self.visible else (0, 0)

    def place(self) -> None:
        if not self.visible:
            return
        w, h = self.stage.width(), self.stage.height()
        self.chip.adjustSize()
        self.chip.move(14, 14)
        self.tools.adjustSize()
        self.tools.move(w - self.tools.width() - 14, 12)
        side = max(self.chip.width(), self.tools.width()) + 28
        tw = max(320, min(760, w - 2 * side))
        self.track.setGeometry(int((w - tw) / 2), 6, int(tw), 76)
        cw = min(360, int(w * 0.32))
        self.composer.setGeometry(14, h - 44, cw, 32)
        capw = max(200, min(int(w * 0.5), w - cw - 60))
        self.caption.setMaximumWidth(capw)
        self.caption.adjustSize()
        x = max(cw + 28, int((w - self.caption.width()) / 2))
        self.caption.move(x, h - 46)

    def set_status(self, word: str, colour: str, stage: str) -> None:
        extra = f"  ·  {stage}" if stage else ""
        self.chip.setText(f"<span style='color:{colour}'>●</span>&nbsp; {html.escape(word.upper())}<span style='color:{T.TEXT_FAINT}'>{html.escape(extra)}</span>")
        self.chip.setStyleSheet(f"QLabel {{ color: {T.TEXT}; background: rgba(12,13,18,0.82); border: 1px solid rgba(244,181,44,0.30); "
                                f"border-radius: 13px; padding: 5px 12px; font-size: 8.5pt; letter-spacing: 1px; }}")
        self.chip.setAccessibleDescription(f"{word}{extra}")
        self.place()

    def set_env(self, env: str) -> None:
        self.env_btn.setText(f"{SP.ENVIRONMENTS.get(env, SP.ENVIRONMENTS['command'])['name']} ▾")
        self.place()

    def set_caption(self, text: str) -> None:
        fm = self.caption.fontMetrics()
        cap = self.caption.maximumWidth() - 40 if self.caption.maximumWidth() < 10000 else 560
        self.caption.setText(fm.elidedText(text, Qt.TextElideMode.ElideLeft, max(120, cap)))
        self.caption.setToolTip(text)
        self.caption.setVisible(self.visible and bool(text))
        self.place()


class EntrySequence(QWidget):
    """Entering ORBIT: a point of light, the core forming, rings unfolding, the space opening. Click or any key
    skips it; it never blocks work (the page underneath is already live)."""

    done = pyqtSignal()

    def __init__(self, parent, seconds: float):
        super().__init__(parent)
        self.seconds = max(0.3, seconds)
        self.t0 = time.perf_counter()
        self.setGeometry(parent.rect())
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Entering ORBIT (click or press a key to skip)")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)
        self.show()
        self.raise_()
        self.setFocus()

    def progress(self) -> float:
        return min(1.0, (time.perf_counter() - self.t0) / self.seconds)

    def _tick(self) -> None:
        if self.progress() >= 1.0:
            self.finish()
        else:
            self.update()

    def finish(self) -> None:
        if self.timer.isActive():
            self.timer.stop()
            self.hide()
            self.deleteLater()
            self.done.emit()

    def mousePressEvent(self, _e) -> None:
        self.finish()

    def keyPressEvent(self, _e) -> None:
        self.finish()

    def paintEvent(self, _e) -> None:
        k = self.progress()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        veil = 1.0 if k < 0.55 else max(0.0, 1 - (k - 0.55) / 0.45)
        p.fillRect(self.rect(), _c((8, 9, 14), veil))
        c = QPointF(self.width() / 2, self.height() / 2)
        base = min(self.width(), self.height())
        # 1. a point of light; 2. the core forming
        core = base * 0.02 + base * 0.08 * min(1.0, k / 0.4)
        g = QRadialGradient(c, core * 3)
        g.setColorAt(0.0, _c((255, 244, 214), min(1.0, k * 4)))
        g.setColorAt(0.3, _c((244, 181, 44), min(0.9, k * 3)))
        g.setColorAt(1.0, _c((244, 181, 44), 0.0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(c, core * 3, core * 3)
        # 3. rings unfold
        for i in range(4):
            unfold = max(0.0, min(1.0, (k - 0.15 - i * 0.07) / 0.35))
            if unfold <= 0:
                continue
            r = base * (0.12 + 0.07 * i) * (0.4 + 0.6 * unfold)
            p.save()
            p.translate(c)
            p.rotate(i * 47 + k * 40 * (1 if i % 2 else -1))
            p.setPen(QPen(_c((247, 217, 139), 0.7 * unfold * max(0.2, veil)), 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(QRectF(-r, -r * 0.42, 2 * r, 2 * r * 0.42), 0, int(360 * 16 * unfold))
            p.restore()
        p.setPen(_c((247, 217, 139), 0.6 * veil))
        p.drawText(QRectF(0, self.height() - 40, self.width(), 20), Qt.AlignmentFlag.AlignCenter, "ORBIT  ·  click or press any key to skip")
        p.end()


# ====================================================================== visual settings

class VisualSettings(QDialog):
    """Settings that really change rendering: intensity, particles, depth, camera, cinematic entry, energy
    effects, ORBIT sounds and volume. Reduce motion (Settings → Desktop) overrides all motion."""

    changed = pyqtSignal()

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("ORBIT visual experience")
        form = QFormLayout(self)
        self.widgets = {}
        for key, label, options in (("orbit_fx_intensity", "Animation intensity", ["subtle", "balanced", "spectacular"]),
                                    ("orbit_fx_particles", "Particle density", ["low", "medium", "high"]),
                                    ("orbit_fx_depth", "Environment depth", ["standard", "immersive"]),
                                    ("orbit_fx_camera", "Camera movement", ["off", "gentle", "dynamic"])):
            cb = QComboBox()
            for o in options:
                cb.addItem(o.capitalize(), o)
            cb.setCurrentIndex(max(0, cb.findData(settings.get(key))))
            cb.currentIndexChanged.connect(lambda _i, k=key, w=cb: self._set(k, w.currentData()))
            cb.setAccessibleName(label)
            form.addRow(label, cb)
        for key, label in (("orbit_fx_cinematic", "Cinematic entry"), ("orbit_fx_energy", "Energy effects (arcs, shockwaves, pulses)"), ("orbit_fx_sound", "ORBIT sounds (quiet, synthesised; never over speech)")):
            ch = QCheckBox(label)
            ch.setChecked(bool(settings.get(key)))
            ch.toggled.connect(lambda v, k=key: self._set(k, bool(v)))
            form.addRow(ch)
        vol = QSlider(Qt.Orientation.Horizontal)
        vol.setRange(0, 100)
        vol.setValue(int(float(settings.get("orbit_fx_volume")) * 100))
        vol.valueChanged.connect(lambda v: self._set("orbit_fx_volume", v / 100.0))
        vol.setAccessibleName("ORBIT sound volume")
        form.addRow("Sound volume", vol)
        note = QLabel("Reduce motion (Settings → Desktop) turns all motion off: the scene is drawn still and panels appear without animation.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {T.TEXT_FAINT};")
        form.addRow(note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.accept)
        form.addRow(bb)

    def _set(self, key, value) -> None:
        self.settings.set(key, value)
        self.changed.emit()




# ====================================================================== the controller

class Universe:
    """Owns the core effects layer and the panels of one ORBIT stage, and keeps them in step with the session.
    The page tells it when the session or state changed; it never changes project data except panel layout and
    the chosen environment (both saved in the session)."""

    def __init__(self, stage, store, get_session: Callable[[], dict], save: Callable[[], None], on_link: Callable[[str, str], None],
                 workspace: str, sounds=None, speaking: Callable[[], bool] = lambda: False):
        self.stage, self.store, self.get_session, self.save, self.on_link = stage, store, get_session, save, on_link
        self.workspace = workspace
        self.sounds = sounds
        self.settings = M.Settings.from_store(store.get)
        self.core = CoreFX(stage, self.settings)
        self.core.setGeometry(stage.rect())
        self.panels: Dict[str, HoloPanel] = {}
        self.env = "command"
        self.focused = ""
        self.preview: Dict[str, str] = {}
        self._seen: Dict[str, object] = {}
        self.stage.universe = self
        self.stage_bar = StageBar()
        self.env_bar = EnvBar()
        self.env_bar.changed.connect(lambda e: self.set_env(e, user=True))
        self.stage_bar.clicked.connect(self.go_stage)
        self.hud: Optional[Hud] = None  # the immersive heads-up layer, attached by the page

    # --- settings ---
    def apply_settings(self) -> None:
        self.settings = M.Settings.from_store(self.store.get)
        self.core.apply(self.settings)
        self.stage.update()

    def reduced(self) -> bool:
        return not self.settings.animate()

    def play(self, cue: str) -> None:
        if self.sounds is not None:
            self.sounds.play(cue)

    # --- geometry ---
    def _band(self):
        """The vertical band panels live in: the whole stage, minus what the immersive HUD reserves."""
        top, bottom = self.hud.reserve() if self.hud is not None else (0, 0)
        return top, max(120, self.stage.height() - top - bottom)

    def to_px(self, r: Dict[str, float]) -> QRect:
        w = self.stage.width()
        top, h = self._band()
        narrow = w < 820
        pw = min(max(180 if narrow else 200, int(r["w"] * w)), max(180, int(w * (0.31 if narrow else 0.34))))
        ph = max(96, int(r["h"] * h))
        x, y = int(r["x"] * w), int(r["y"] * h)
        x = max(4, min(w - pw - 4, x)) if pw < w else 0  # always fully inside the stage when it fits
        y = max(4, min(h - ph - 4, y)) if ph < h else 0
        return QRect(x, y + top, pw, ph)

    def to_frac(self, g: QRect) -> Dict[str, float]:
        w = max(1, self.stage.width())
        top, h = self._band()
        return {"x": g.x() / w, "y": (g.y() - top) / max(1, h), "w": g.width() / w, "h": g.height() / max(1, h)}

    def _placed(self, lay: Dict[str, Dict[str, object]]) -> Dict[str, QRect]:
        """Pixel rectangles for this environment's visible panels, nudged apart when the stage is too small for
        them not to overlap (stored fractions are untouched; only what is drawn moves)."""
        out: Dict[str, QRect] = {}
        top, band = self._band()
        H, W = top + band, self.stage.width()  # H: the band's bottom edge
        c = self.stage.centre()
        narrow = W < 820
        chips = 0
        for k, pid in enumerate(SP.ENVIRONMENTS[self.env]["panels"]):
            r = self.to_px(lay[pid])
            if narrow and k >= 4 and not lay[pid]["hidden"]:
                # a small stage: extra panels become title bars along the top, opened with a click
                r = QRect(int(c.x() - 105), H - 38 * (chips + 1), 210, 34)
                chips += 1
                out[pid] = r
                continue
            if not lay[pid]["hidden"]:
                for _ in range(12):
                    hit = next((o for o in out.values() if o.intersects(r)), None)
                    if hit is None:
                        break
                    down = r.center().y() >= c.y()
                    dy = (hit.bottom() - r.top() + 6) if down else -(r.bottom() - hit.top() + 6)
                    moved = r.translated(0, dy)
                    if moved.top() < top + 4 or moved.bottom() > H - 4:  # no room vertically: shrink instead
                        r.setHeight(max(80, r.height() - abs(dy)))
                        if down:
                            r.moveTop(min(H - r.height() - 4, max(hit.bottom() + 6, r.top())))
                        else:
                            r.moveBottom(max(r.height() + 4, min(hit.top() - 6, r.bottom())))
                        break
                    r = moved
            out[pid] = r
        return out

    def relayout(self) -> None:
        self.core.setGeometry(self.stage.rect())
        s = self.get_session()
        if not s:
            return
        lay = SP.layout(s, self.env)
        targets = self._placed(lay)
        for pid, panel in self.panels.items():
            if pid in lay and not panel.expanded and panel.isVisible() and pid in SP.ENVIRONMENTS[self.env]["panels"]:
                panel.settle()
                panel.set_compact(targets[pid].height() <= 40)
                panel.setGeometry(targets[pid])
        self._links()

    # --- panels ---
    def _panel(self, pid: str) -> HoloPanel:
        if pid not in self.panels:
            pnl = HoloPanel(pid, SP.PANELS[pid][0], self.stage)
            pnl.hide()
            pnl.moved.connect(self._moved)
            pnl.state_changed.connect(self._panel_state)
            pnl.link.connect(self._link)
            pnl.selected.connect(self._select)
            # real actions only: each one goes through the page (a message to Prometheus or a plan edit)
            if pid == "files":
                pnl.add_action("+ Attach", "Attach a file from the workspace", lambda: self.on_link("files", "attach:"))
            elif pid == "ideas":
                pnl.add_action("Compare ideas", "Ask Prometheus to compare the ideas", lambda: self.on_link("ideas", "action:compare_ideas"), primary=True)
                pnl.add_action("+ Add", "Add an idea of your own", lambda: self.on_link("ideas", "action:add_idea"))
            elif pid == "brief":
                pnl.add_action("Edit brief", "Write or change the project brief", lambda: self.on_link("brief", "action:edit_brief"))
            self.panels[pid] = pnl
        return self.panels[pid]

    def set_env(self, env: str, user: bool = False, animate: bool = True) -> None:
        s = self.get_session()
        if env not in SP.ENVIRONMENTS:
            env = "command"
        old = self.env
        self.env = env
        if s is not None and s.get("environment") != env:
            SP.set_environment(s, env)
            if user:
                self.save()
        self.env_bar.set_env(env)
        if self.hud is not None:
            self.hud.set_env(env)
        self.stage.show_constellation = SP.ENVIRONMENTS[env]["constellation"]
        wanted = set(SP.ENVIRONMENTS[env]["panels"])
        for pid, pnl in self.panels.items():
            if pid not in wanted and pnl.isVisible():
                pnl.dissolve(self.reduced() or not animate, lambda: None)
            elif pid in wanted:
                if pnl.expanded:
                    pnl.expanded = False
                pnl.settle()  # a running restore/materialise animation must not land on the old environment's spot
        self.refresh(materialise=(old != env or not any(p.isVisible() for p in self.panels.values())) and animate)
        if user:
            self.play("select")

    def refresh(self, provisional: Optional[dict] = None, materialise: bool = False) -> None:
        s = self.get_session() or {}
        st = SP.stages(s)
        self.stage_bar.set_stages(st)
        if self.hud is not None:
            plan = SP.plan_of(s) or {}
            title = (provisional or {}).get("title") or plan.get("title") or s.get("title") or ""
            self.hud.track.set_data(str(title), st)
        lay = SP.layout(s, self.env)
        origin = self.stage.centre()
        targets = self._placed(lay)
        for i, pid in enumerate(SP.ENVIRONMENTS[self.env]["panels"]):
            pnl = self._panel(pid)
            content = SP.panel_content(s, pid)
            prov = False
            if provisional and not content["items"]:
                items = []
                if pid == "brief" and (provisional.get("title") or provisional.get("brief")):
                    items = [{"text": provisional.get("title", ""), "sub": "", "state": "title", "ref": ""}] + ([{"text": provisional["brief"], "sub": "Brief", "state": "", "ref": ""}] if provisional.get("brief") else [])
                elif pid == "ideas":
                    items = [{"text": x, "sub": "idea", "state": "", "ref": ""} for x in provisional.get("ideas") or []]
                elif pid == "plan":
                    items = [{"text": x, "sub": "phase", "state": "", "ref": ""} for x in provisional.get("phases") or []]
                    items += [{"text": x, "sub": "task", "state": "", "ref": ""} for x in provisional.get("tasks") or []]
                if items:
                    content, prov = {**content, "items": items, "empty": ""}, True
            if pid in self.preview:
                pnl.set_html(self.preview[pid])
            else:
                pnl.set_content(content, prov)
            r = lay[pid]
            if r["hidden"]:
                pnl.hide()
                continue
            pnl.set_compact(targets[pid].height() <= 40)
            if pnl.collapsed != r["collapsed"]:
                pnl.toggle_collapse()
            if not pnl.isVisible():
                pnl.materialise(origin, targets[pid], 420 if materialise else 0, 70 * i, self.reduced() or not materialise)
                if materialise:
                    self.play("panel") if i == 0 else None
            elif not pnl.expanded and pnl._drag is None and (pnl._anim is None or pnl._anim.state() != pnl._anim.State.Running):
                pnl.setGeometry(targets[pid])
            pnl.raise_()
        self._detect_events(s)
        self._links()

    def _links(self) -> None:
        """Curved lines for the real relationships only. Lines from the core leave from the particle torus's rim
        (an ellipse around the sun) and every curve bows away from the core, as in a star chart."""
        s = self.get_session() or {}
        edges = SP.connections(s, self.env)
        c = self.stage.centre()
        R = self.stage.core_radius()
        ra, rb = R * TORUS_MAJOR * 1.08, R * TORUS_MAJOR * TORUS_RATIO * 1.6
        lines = []
        for e in edges:
            a = self._anchor(e["from"], c, R)
            b = self._anchor(e["to"], c, R)
            if a is None or b is None:
                continue
            if e["from"] == "core":
                dx, dy = b.x() - c.x(), b.y() - c.y()
                k = 1.0 / max(1e-6, math.sqrt((dx / ra) ** 2 + (dy / rb) ** 2))
                a = QPointF(c.x() + dx * k, c.y() + dy * k)
            cx, cy = M.curve_ctrl((a.x(), a.y()), (b.x(), b.y()), (c.x(), c.y()))
            lines.append((a, QPointF(cx, cy), b, e["kind"], f"{e['from']}>{e['to']}"))
        self.stage.link_lines = lines
        self.core.links = lines
        self.stage.update()

    def _anchor(self, node: str, c: QPointF, R: float) -> Optional[QPointF]:
        if node == "core":
            return None if not self.panels else c
        pnl = self.panels.get(node)
        if pnl is None or not pnl.isVisible():
            return None
        g = pnl.geometry()
        cx, cy = g.center().x(), g.center().y()
        # the point on the panel's edge facing the core
        x = min(max(c.x(), g.left()), g.right())
        y = min(max(c.y(), g.top()), g.bottom())
        if g.contains(int(c.x()), int(c.y())):
            x, y = cx, cy
        return QPointF(x, y)

    # --- real events → effects and sounds ---
    def _detect_events(self, s: dict) -> None:
        wf = s.get("workflow") or {}
        nodes = wf.get("nodes") or []
        now = {
            "sid": s.get("id"), "versions": len(s.get("plan_versions") or []), "approved": s.get("approved_version", 0),
            "done": sum(1 for n in nodes if n["status"] == "completed"), "wf": wf.get("state", ""), "files": len(s.get("files") or []),
            "waiting": sum(1 for n in nodes if n["status"] == "awaiting_approval"),
        }
        old, self._seen = self._seen, now
        if not old or old.get("sid") != now["sid"]:
            return  # opening a session is not an event
        if now["versions"] > old["versions"]:
            self.core.event_fx("project.created" if old["versions"] == 0 else "plan.updated")
            self.play("milestone" if old["versions"] == 0 else "connect")
        if now["approved"] and now["approved"] != old["approved"]:
            self.core.event_fx("plan.approved")
            self.play("confirm")
        if now["done"] > old["done"]:
            self.core.event_fx("step.completed")
        if now["wf"] == "completed" and old["wf"] != "completed":
            self.core.event_fx("workflow.completed")
            self.play("milestone")
        if now["files"] > old["files"]:
            self.core.event_fx("file.written")
        if now["waiting"] > old["waiting"]:
            self.core.event_fx("approval.requested")

    # --- panel callbacks ---
    def _moved(self, pid: str, g: QRect) -> None:
        s = self.get_session()
        if s is None or self.panels[pid].expanded:
            return
        SP.set_rect(s, self.env, pid, **self.to_frac(g))
        self.save()
        self._links()

    def _panel_state(self, pid: str, what: str) -> None:
        s = self.get_session()
        pnl = self.panels[pid]
        if what == "hidden":
            if s is not None:
                SP.set_rect(s, self.env, pid, hidden=True)
                self.save()
            pnl.dissolve(self.reduced(), self._links)
            return
        if what == "expanded":
            for other in self.panels.values():
                if other is not pnl:
                    other.opacity.setOpacity(0.35)
        elif what == "restored":
            for other in self.panels.values():
                other.opacity.setOpacity(1.0)
        if s is not None and what in ("collapsed", "restored") and not pnl.expanded:
            SP.set_rect(s, self.env, pid, collapsed=pnl.collapsed)
            self.save()
        self._links()

    def _select(self, pid: str) -> None:
        self.focused = pid
        for k, p in self.panels.items():
            p.focus(k == pid)
        self.core.fx.start("pulse", f"core>{pid}")

    def _link(self, pid: str, href: str) -> None:
        if href == "back:":
            self.preview.pop(pid, None)
            self.refresh()
            return
        self.on_link(pid, href)

    def show_preview(self, pid: str, title: str, body_html: str) -> None:
        self.preview[pid] = f"<p><a href='back:' style='color:{T.ACCENT}'>← back</a> &nbsp; <b>{html.escape(title)}</b></p>{body_html}"
        pnl = self._panel(pid)
        pnl.set_html(self.preview[pid])
        if not pnl.expanded:
            pnl.toggle_expand()

    def show_panel(self, pid: str) -> None:
        s = self.get_session()
        if s is not None and pid in SP.ENVIRONMENTS[self.env]["panels"]:
            SP.set_rect(s, self.env, pid, hidden=False)
            self.save()
            self.refresh(materialise=True)

    def reset_layout(self) -> None:
        s = self.get_session()
        if s is not None:
            SP.reset_layout(s, self.env)
            self.save()
        for p in self.panels.values():
            if p.expanded:
                p.toggle_expand()
        self.refresh()

    def go_stage(self, key: str) -> None:
        env, pid = SP.stage_environment(key)
        self.set_env(env, user=True)
        pnl = self.panels.get(pid)
        if pnl is not None:
            self.show_panel(pid) if not pnl.isVisible() else None
            self._select(pid)
            pnl.raise_()

    def entry(self, first: bool, parent: QWidget) -> Optional[EntrySequence]:
        if not self.settings.cinematic or self.reduced():
            return None
        self.play("enter")
        seq = EntrySequence(self.stage, 2.6 if first else 0.9)
        return seq
