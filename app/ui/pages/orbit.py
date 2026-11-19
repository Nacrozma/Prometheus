"""ORBIT: talk with Prometheus, watch the plan take shape around the sun, shape it, approve it, run it.

Everything shown is real: the plan is the structured data in the session (app/services/orbit.py), node
states change only from recorded events, the avatar shows what is actually happening, the level meter
is the real microphone or playback level. Running a step goes through the same worker, tools and
approval gate as the Companion; nothing on the canvas executes anything by being there.
"""

from __future__ import annotations

import json
import math
import time
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QKeySequence, QPainter, QPainterPath, QPen, QShortcut
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...services import orbit as O
from ...services.orbit_voice import LIMITS, TurnTaker
from .. import theme as T
from ..widgets import Page, label

#: How each node state is told apart without colour: a shape mark and a word.
STATUS_MARK = {
    "draft": ("◌", "Draft"), "ready": ("○", "Ready"), "waiting": ("⧗", "Waiting for a dependency"),
    "awaiting_approval": ("?", "Awaiting your approval"), "running": ("▶", "Running"), "completed": ("✓", "Completed"),
    "failed": ("!", "Failed"), "paused": ("‖", "Paused"), "cancelled": ("×", "Cancelled"), "blocked": ("⊘", "Blocked"),
    "proposed": ("◌", "Proposed"), "confirmed": ("○", "In the plan"),
}
STATUS_COLOUR = {
    "completed": T.OK, "running": T.SECONDARY_ACCENT, "failed": T.ERR, "awaiting_approval": T.HIGHLIGHT,
    "paused": T.TEXT_SECONDARY, "cancelled": T.TEXT_FAINT, "blocked": T.WARN, "waiting": T.TEXT_SECONDARY,
}
WF_WORDS = {"ready": "Ready to start", "running": "Running", "awaiting_approval": "Waiting for you", "paused": "Paused", "failed": "A step failed", "completed": "Completed", "cancelled": "Cancelled"}


def _gl_ok() -> bool:
    from .companion import _gl_available

    return _gl_available()


class _Vignette(QWidget):
    """A transparent layer over the sun that fades the square edges of its drawing area into the stage, so the
    sun sits in space rather than in a box. Mouse events pass through."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, _e) -> None:
        from PyQt6.QtGui import QRadialGradient

        p = QPainter(self)
        c = QPointF(self.width() / 2, self.height() / 2)
        r = min(self.width(), self.height()) / 2
        g = QRadialGradient(c, r * 1.42)
        bg, clear = QColor(T.BG), QColor(T.BG)
        clear.setAlpha(0)
        g.setColorAt(0.0, clear)
        g.setColorAt(0.46, clear)
        g.setColorAt(0.70, bg)
        g.setColorAt(1.0, bg)
        p.fillRect(self.rect(), g)
        p.end()


class OrbitStage(QWidget):
    """The spatial canvas. Phases are orbits around the sun, tasks are bodies on their phase's orbit,
    dependencies are arcs between them. Click selects, drag a body to another orbit to move it to that
    phase, drag empty space to pan, wheel or +/- to zoom, arrows move the selection, Enter opens it,
    Delete removes it (undo restores it)."""

    selected = pyqtSignal(str)
    activated = pyqtSignal(str)
    move_requested = pyqtSignal(str, str)  # task id, phase
    remove_requested = pyqtSignal(str)
    space_pressed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumSize(520, 420)
        self.setAccessibleName("ORBIT plan canvas")
        self.setAccessibleDescription("Phases are orbits around Prometheus; tasks sit on them. The Outline view lists the same plan.")
        self.plan: Optional[Dict[str, Any]] = None
        self.status: Dict[str, str] = {}
        self.provisional: Dict[str, List[str]] = {"phases": [], "tasks": []}
        self.sel = ""
        self.zoom, self.pan = 1.0, QPointF(0, 0)
        self._drag: Optional[Dict[str, Any]] = None
        self._born: Dict[str, float] = {}
        self.reduced = False
        self._anim = QTimer(self)
        self._anim.setInterval(33)
        self._anim.timeout.connect(self._tick)
        self.avatar = None
        self.glyph = None
        if _gl_ok():
            try:
                from ..solar import SolarAvatar

                self.avatar = SolarAvatar(self)
                self.avatar.disc_scale = 0.42
            except Exception:
                self.avatar = None
        self.vignette = None
        if self.avatar is None:
            from ..sun import SolarGlyph

            self.glyph = SolarGlyph(160, parent=self)
            self.glyph.setToolTip("Painted sun: OpenGL 3.3 is not available here.")
        else:
            self.vignette = _Vignette(self)
            self.vignette.raise_()

    # ----- data -----
    def set_plan(self, plan: Optional[Dict[str, Any]], status: Optional[Dict[str, str]] = None) -> None:
        old = {t["id"] for t in (self.plan or {}).get("tasks", [])}
        self.plan, self.status = plan, status or {}
        now = time.perf_counter()
        for t in (plan or {}).get("tasks", []):
            if t["id"] not in old and not self.reduced:
                self._born[t["id"]] = now + 0.08 * len(self._born)  # new bodies settle one after another
        if self.sel and not any(t["id"] == self.sel for t in (plan or {}).get("tasks", [])):
            self.sel = ""
        self.provisional = {"phases": [], "tasks": []}
        self._kick()
        self.update()

    def set_provisional(self, partial: Dict[str, List[str]]) -> None:
        self.provisional = partial
        self.update()

    def set_state(self, state: str, progress: float = 0.0) -> None:
        if self.avatar is not None:
            self.avatar.progress = progress
            self.avatar.set_semantic(state)
        if self.glyph is not None:
            self.glyph.progress = progress
            self.glyph.set_state(state)

    def set_level(self, level: float) -> None:
        (self.avatar or self.glyph).set_audio_level(level)

    def set_reduced_motion(self, reduced: bool) -> None:
        self.reduced = reduced
        (self.avatar or self.glyph).set_reduced_motion(reduced)
        if reduced:
            self._born.clear()

    def _kick(self) -> None:
        if self._born and not self._anim.isActive():
            self._anim.start()

    def _tick(self) -> None:
        now = time.perf_counter()
        self._born = {k: v for k, v in self._born.items() if now - v < 0.6}
        if not self._born:
            self._anim.stop()
        self.update()

    # ----- geometry -----
    def centre(self) -> QPointF:
        return QPointF(self.width() / 2 + self.pan.x(), self.height() / 2 + self.pan.y())

    def phases(self) -> List[str]:
        if self.plan:
            return list(self.plan["phases"])
        return list(self.provisional.get("phases") or [])

    def ring_radius(self, i: int) -> float:
        base = min(self.width(), self.height())
        n = max(1, len(self.phases()))
        inner, outer = base * 0.27, base * 0.47
        step = (outer - inner) / max(1, n - 1) if n > 1 else 0
        return (inner + step * i if n > 1 else (inner + outer) / 2) * self.zoom

    def avatar_size(self) -> int:
        k = 0.36 if self.avatar is not None else 0.2  # the GL sun is drawn smaller inside its widget
        return int(max(110, min(380, min(self.width(), self.height()) * k * self.zoom)))

    def positions(self) -> Dict[str, QPointF]:
        out: Dict[str, QPointF] = {}
        if not self.plan:
            return out
        c = self.centre()
        for i, ph in enumerate(self.plan["phases"]):
            items = [t for t in self.plan["tasks"] if t["phase"] == ph]
            r = self.ring_radius(i)
            off = -math.pi / 2 + 0.5 + i * 0.6  # the top of each orbit is kept for its phase name
            for k, t in enumerate(items):
                a = off + k * math.tau / max(1, len(items))
                out[t["id"]] = QPointF(c.x() + math.cos(a) * r, c.y() + math.sin(a) * r)
        return out

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._place_avatar()

    def _place_avatar(self) -> None:
        s = self.avatar_size()
        c = self.centre()
        w = self.avatar or self.glyph
        w.setGeometry(int(c.x() - s / 2), int(c.y() - s / 2), s, s)
        if self.vignette is not None:
            self.vignette.setGeometry(w.geometry())

    # ----- painting -----
    def paintEvent(self, _e) -> None:
        self._place_avatar()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(T.BG))
        c = self.centre()
        phases = self.phases()
        f = QFont(self.font())
        f.setPointSizeF(9.0)
        p.setFont(f)
        for i, ph in enumerate(phases):
            r = self.ring_radius(i)
            pen = QPen(QColor(T.BORDER_STRONG), 1.0, Qt.PenStyle.SolidLine if self.plan else Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, r, r)
            p.setPen(QColor(T.TEXT_FAINT))
            tag = f"{i + 1}  {ph.upper()}"
            p.drawText(QRectF(c.x() - 160, c.y() - r - 18, 320, 16), Qt.AlignmentFlag.AlignCenter, tag)
        if not self.plan:
            self._paint_provisional(p, c)
            p.end()
            return
        pos = self.positions()
        for d in self.plan["deps"]:
            a, b = pos.get(d["from"]), pos.get(d["to"])
            if a is None or b is None:
                continue
            path = QPainterPath(a)
            ctrl = QPointF((a.x() + b.x()) / 2 + (c.x() - (a.x() + b.x()) / 2) * 0.35, (a.y() + b.y()) / 2 + (c.y() - (a.y() + b.y()) / 2) * 0.35)
            path.quadTo(ctrl, b)
            p.setPen(QPen(QColor(T.BORDER_WARM), 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
            ang = math.atan2(b.y() - ctrl.y(), b.x() - ctrl.x())
            tip = QPointF(b.x() - math.cos(ang) * 17, b.y() - math.sin(ang) * 17)
            p.setBrush(QColor(T.BORDER_WARM))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawPolygon([tip, QPointF(tip.x() - math.cos(ang - 0.45) * 8, tip.y() - math.sin(ang - 0.45) * 8), QPointF(tip.x() - math.cos(ang + 0.45) * 8, tip.y() - math.sin(ang + 0.45) * 8)])
        now = time.perf_counter()
        for t in self.plan["tasks"]:
            pt = pos[t["id"]]
            if self._drag and self._drag.get("id") == t["id"] and self._drag.get("moved"):
                pt = self._drag["at"]
            born = self._born.get(t["id"])
            k = 1.0 if born is None else max(0.0, min(1.0, (now - born) / 0.5))
            st = self.status.get(t["id"]) or t.get("status", "proposed")
            mark, word = STATUS_MARK.get(st, ("○", st))
            col = QColor(STATUS_COLOUR.get(st, T.ACCENT if t["priority"] == "high" else T.HIGHLIGHT))
            r = (13 + (3 if t["priority"] == "high" else 0)) * (0.4 + 0.6 * k)
            selected = t["id"] == self.sel
            p.setBrush(QColor(T.SURFACE_ELEVATED))
            pen = QPen(col, 2.4 if selected else 1.4, Qt.PenStyle.DashLine if st == "proposed" else Qt.PenStyle.SolidLine)
            p.setPen(pen)
            p.drawEllipse(pt, r, r)
            if selected:
                p.setPen(QPen(QColor(T.FOCUS), 1.0))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(pt, r + 5, r + 5)
            p.setPen(col)
            p.drawText(QRectF(pt.x() - r, pt.y() - r, 2 * r, 2 * r), Qt.AlignmentFlag.AlignCenter, mark)
            title = t["title"] if len(t["title"]) <= 26 else t["title"][:25] + "…"
            p.setPen(QColor(T.TEXT if selected else T.TEXT_SECONDARY))
            tw = p.fontMetrics().horizontalAdvance(title) + 4
            # labels point away from the sun; they switch sides only when they would leave the canvas
            right = (pt.x() >= c.x() and pt.x() + r + 6 + tw < self.width()) or pt.x() - r - 6 - tw < 0
            box = QRectF(pt.x() + r + 6, pt.y() - 9, tw, 18) if right else QRectF(pt.x() - r - 6 - tw, pt.y() - 9, tw, 18)
            p.drawText(box, (Qt.AlignmentFlag.AlignLeft if right else Qt.AlignmentFlag.AlignRight) | Qt.AlignmentFlag.AlignVCenter, title)
        p.end()

    def _paint_provisional(self, p: QPainter, c: QPointF) -> None:
        tasks = self.provisional.get("tasks") or []
        if not tasks:
            return
        r = self.ring_radius(len(self.phases()) - 1) if self.phases() else min(self.width(), self.height()) * 0.36
        for k, title in enumerate(tasks):
            a = -math.pi / 2 + k * math.tau / max(6, len(tasks))
            pt = QPointF(c.x() + math.cos(a) * r, c.y() + math.sin(a) * r)
            p.setPen(QPen(QColor(T.HIGHLIGHT), 1.2, Qt.PenStyle.DashLine))
            p.setBrush(QColor(T.SURFACE_ELEVATED))
            p.drawEllipse(pt, 10, 10)
            p.setPen(QColor(T.TEXT_FAINT))
            p.drawText(QRectF(pt.x() + 14, pt.y() - 9, 200, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, (title[:25] + "…") if len(title) > 26 else title)
        p.drawText(QRectF(0, self.height() - 26, self.width(), 18), Qt.AlignmentFlag.AlignCenter, "Provisional: the plan is still arriving")

    # ----- interaction -----
    def _hit(self, pt: QPointF) -> str:
        for tid, q in self.positions().items():
            if (q.x() - pt.x()) ** 2 + (q.y() - pt.y()) ** 2 <= 20 ** 2:
                return tid
        return ""

    def _phase_at(self, pt: QPointF) -> str:
        c = self.centre()
        d = math.hypot(pt.x() - c.x(), pt.y() - c.y())
        ph = self.phases()
        if not ph:
            return ""
        best = min(range(len(ph)), key=lambda i: abs(self.ring_radius(i) - d))
        return ph[best]

    def mousePressEvent(self, e) -> None:
        self.setFocus()
        pt = e.position()
        tid = self._hit(pt)
        if tid:
            self.select(tid)
        self._drag = {"id": tid, "start": pt, "at": pt, "pan": QPointF(self.pan), "moved": False}

    def mouseMoveEvent(self, e) -> None:
        if not self._drag or not (e.buttons() & Qt.MouseButton.LeftButton):
            self.setCursor(Qt.CursorShape.PointingHandCursor if self._hit(e.position()) else Qt.CursorShape.ArrowCursor)
            return
        pt = e.position()
        delta = pt - self._drag["start"]
        if abs(delta.x()) + abs(delta.y()) > 4:
            self._drag["moved"] = True
        if self._drag["id"]:
            self._drag["at"] = pt
        else:
            self.pan = self._drag["pan"] + delta
        self.update()

    def mouseReleaseEvent(self, e) -> None:
        d, self._drag = self._drag, None
        if d and d["id"] and d["moved"]:
            ph = self._phase_at(e.position())
            cur = next((t["phase"] for t in self.plan["tasks"] if t["id"] == d["id"]), "") if self.plan else ""
            if ph and ph != cur:
                self.move_requested.emit(d["id"], ph)
        self.update()

    def mouseDoubleClickEvent(self, e) -> None:
        tid = self._hit(e.position())
        if tid:
            self.activated.emit(tid)

    def wheelEvent(self, e) -> None:
        self.set_zoom(self.zoom * (1.1 if e.angleDelta().y() > 0 else 1 / 1.1))

    def set_zoom(self, z: float) -> None:
        self.zoom = max(0.6, min(2.2, z))
        self.update()

    def select(self, tid: str) -> None:
        self.sel = tid
        self.update()
        self.selected.emit(tid)

    def keyPressEvent(self, e) -> None:
        ids = [t["id"] for t in (self.plan or {}).get("tasks", [])]
        k = e.key()
        if k in (Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Up) and ids:
            i = ids.index(self.sel) if self.sel in ids else -1
            i = (i + (1 if k in (Qt.Key.Key_Right, Qt.Key.Key_Down) else -1)) % len(ids)
            self.select(ids[i])
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.sel:
            self.activated.emit(self.sel)
        elif k == Qt.Key.Key_Delete and self.sel:
            self.remove_requested.emit(self.sel)
        elif k in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.set_zoom(self.zoom * 1.1)
        elif k == Qt.Key.Key_Minus:
            self.set_zoom(self.zoom / 1.1)
        elif k == Qt.Key.Key_Space:
            self.space_pressed.emit()
        elif k == Qt.Key.Key_0:
            self.zoom, self.pan = 1.0, QPointF(0, 0)
            self.update()
        else:
            super().keyPressEvent(e)


class OrbitPage(Page):
    title = "ORBIT"
    header = "none"
    margins = (20, 14, 20, 12)

    immersive_changed = pyqtSignal(bool)
    state_changed = pyqtSignal(str)

    def __init__(self, core, settings, conversations, notify=None, parent=None, speech=None):
        super().__init__(core, parent)
        import gui_markdown as md
        import gui_orb as g
        from gui_config import AppConfig

        from ...services.conversations import visible

        self.g, self.md, self.visible = g, md, visible
        self.settings, self.conversations = settings, conversations
        self.notify = notify or (lambda *a, **k: None)
        self.config = AppConfig()
        self.store = O.OrbitStore(core.paths()["data"])
        self.session: Dict[str, Any] = {}
        self.worker = None
        self.worker_kind = ""  # "talk" or a node id
        self.card = None
        self.immersive = False
        self.listening = False
        self.continuous = bool(settings.get("orbit_continuous"))
        self.turns = TurnTaker(silence=float(settings.get("orbit_silence")), sensitivity=float(settings.get("orbit_sensitivity")))
        self._stream = ""
        self._cancelling = False
        self.state = "IDLE"
        self._build()

        # voice: the one shared speech service (the same preferences as the Companion)
        if speech is None:
            from ..speech_bridge import SpeechBridge

            speech = SpeechBridge(core.paths()["data"], settings, parent=self)
        self.tts = speech
        self._speech_mine = False
        self.tts.level.connect(lambda lv: self._speech_mine and self._play_level(lv))
        self.tts.speaking.connect(self._speech_state)
        self.tts.error.connect(self._speech_error)
        self.voice = None
        self.refresh_voice()
        # after Prometheus finishes speaking, listen again (continuous conversation)
        self._speech_watch = QTimer(self)
        self._speech_watch.setInterval(250)
        self._speech_watch.timeout.connect(self._watch_speech)

        self.stage.space_pressed.connect(self._space)
        for seq, fn in (("Escape", self._escape), ("Ctrl+Return", self.approve_plan)):
            QShortcut(QKeySequence(seq), self, activated=fn, context=Qt.ShortcutContext.WidgetWithChildrenShortcut)

        sid = settings.get("orbit_session")
        s = self.store.get(sid) if sid else None
        self.open_session(s["id"] if s else "", quiet=True)

    # ----- layout -----
    def _build(self) -> None:
        top = QHBoxLayout()
        top.setSpacing(8)
        t = label("ORBIT", "h2", wrap=False)
        t.setStyleSheet(f"font-size: 14pt; letter-spacing: 3px; color: {T.HIGHLIGHT};")
        top.addWidget(t)
        self.session_box = QComboBox()
        self.session_box.setMinimumWidth(240)
        self.session_box.setAccessibleName("ORBIT session")
        self.session_box.activated.connect(lambda i: self.open_session(self.session_box.itemData(i) or ""))
        top.addWidget(self.session_box)
        b = QPushButton("New session")
        b.clicked.connect(lambda: self.new_session())
        top.addWidget(b)
        self.more_btn = QPushButton("Session ▾")
        self.more_btn.setMenu(self._session_menu())
        top.addWidget(self.more_btn)
        top.addStretch(1)
        top.addWidget(label("Autonomy", "faint", wrap=False))
        self.autonomy = QComboBox()
        for key, name in (("approval_first", "Approval-first"), ("balanced", "Balanced"), ("advanced", "Advanced")):
            self.autonomy.addItem(name, key)
        self.autonomy.setAccessibleName("Autonomy for this mission")
        self.autonomy.currentIndexChanged.connect(self._autonomy_changed)
        top.addWidget(self.autonomy)
        self.view_btn = QPushButton("Outline")
        self.view_btn.setToolTip("Switch between the spatial view and an outline list of the same plan")
        self.view_btn.clicked.connect(self.toggle_view)
        top.addWidget(self.view_btn)
        self.imm_btn = QPushButton("Immersive")
        self.imm_btn.setToolTip("Hide everything but ORBIT (Esc returns)")
        self.imm_btn.clicked.connect(lambda: self.set_immersive(not self.immersive))
        top.addWidget(self.imm_btn)
        self.content.addLayout(top)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(1)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(8)
        self.plan_line = label("", "sub")
        self.plan_line.setWordWrap(True)
        self.plan_line.setTextFormat(Qt.TextFormat.RichText)
        lv.addWidget(self.plan_line)
        self.views = QStackedWidget()
        self.stage = OrbitStage()
        self.stage.selected.connect(self.select_task)
        self.stage.activated.connect(lambda tid: (self.select_task(tid), self.tabs.setCurrentIndex(1)))
        self.stage.move_requested.connect(lambda tid, ph: self.apply_edit("move_to_phase", ref=tid, phase=ph))
        self.stage.remove_requested.connect(lambda tid: self.apply_edit("remove_task", ref=tid))
        self.outline = QTreeWidget()
        self.outline.setHeaderLabels(["Task", "Status", "Priority", "Done by"])
        self.outline.setAccessibleName("Plan outline")
        self.outline.itemSelectionChanged.connect(self._outline_selected)
        self.views.addWidget(self.stage)
        self.views.addWidget(self.outline)
        lv.addWidget(self.views, 1)
        # workflow controls: each enabled only when the workflow can really do it
        row = QHBoxLayout()
        row.setSpacing(6)
        self.wf_lbl = label("", "faint", wrap=False)
        row.addWidget(self.wf_lbl, 1)
        self.wf_buttons: Dict[str, QPushButton] = {}
        for key, text, fn, tip in (
            ("approve", "Approve plan", self.approve_plan, "Approve this version (Ctrl+Enter). Nothing runs until you start the workflow."),
            ("build", "Build workflow", self.build_workflow, "Turn the approved plan into steps mapped to real capabilities"),
            ("start", "Start", self.start_workflow, "Start the next ready step"),
            ("go", "Approve step", self.approve_step, "Let the step that is waiting for you run"),
            ("pause", "Pause", self.pause_workflow, "No new step starts; the running step finishes or can be cancelled"),
            ("resume", "Resume", self.resume_workflow, "Continue from where the workflow paused"),
            ("retry", "Retry step", self.retry_step, "Run the selected failed, cancelled or blocked step again"),
            ("cancel", "Cancel workflow", self.cancel_workflow, "Stop the running step and cancel the rest"),
        ):
            btn = QPushButton(text)
            btn.setToolTip(tip)
            btn.clicked.connect(fn)
            if key in ("approve", "go"):
                btn.setObjectName("primary")
            self.wf_buttons[key] = btn
            row.addWidget(btn)
        lv.addLayout(row)
        split.addWidget(left)

        right = QWidget()
        right.setMinimumWidth(380)
        right.setMaximumWidth(520)
        rv = QVBoxLayout(right)
        rv.setContentsMargins(12, 0, 0, 0)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._talk_tab(), "Conversation")
        self.tabs.addTab(self._step_tab(), "Step")
        self.tabs.addTab(self._versions_tab(), "Versions")
        rv.addWidget(self.tabs)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setSizes([900, 420])
        self.content.addWidget(split, 1)

    def _session_menu(self) -> QMenu:
        m = QMenu(self)
        m.addAction("Rename…", self.rename_session)
        m.addAction("Archive", self.archive_session)
        m.addAction("Delete…", self.delete_session)
        m.addSeparator()
        m.addAction("Voice options…", self.voice_options)
        return m

    def _talk_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(8)
        self.state_line = label("● Idle", wrap=False)
        lay.addWidget(self.state_line)
        self.transcript = QTextBrowser()
        self.transcript.setOpenExternalLinks(False)
        self.transcript.setAccessibleName("ORBIT conversation transcript")
        lay.addWidget(self.transcript, 1)
        self.level = QProgressBar()
        self.level.setRange(0, 100)
        self.level.setTextVisible(False)
        self.level.setFixedHeight(4)
        self.level.setAccessibleName("Microphone or speech level")
        lay.addWidget(self.level)
        vrow = QHBoxLayout()
        self.talk_btn = QPushButton("Talk")
        self.talk_btn.setCheckable(True)
        self.talk_btn.setObjectName("primary")
        self.talk_btn.toggled.connect(self._talk_toggled)
        vrow.addWidget(self.talk_btn)
        self.cont_box = QCheckBox("Continuous")
        self.cont_box.setChecked(self.continuous)
        self.cont_box.setToolTip("On: ORBIT listens again after each reply and ends your turn when you pause. Off: press Talk, speak, press again.")
        self.cont_box.toggled.connect(self._continuous_toggled)
        vrow.addWidget(self.cont_box)
        vrow.addStretch(1)
        lay.addLayout(vrow)
        vrow = QHBoxLayout()
        self.hush_btn = QPushButton("Stop speaking")
        self.hush_btn.setToolTip("Silence Prometheus now (Space or Esc). The workflow is not affected.")
        self.hush_btn.clicked.connect(self.stop_speaking)
        vrow.addWidget(self.hush_btn)
        self.end_btn = QPushButton("End conversation")
        self.end_btn.setToolTip("Stop listening and speaking, and stop the current reply. The plan and workflow stay as they are.")
        self.end_btn.clicked.connect(self.end_conversation)
        vrow.addWidget(self.end_btn)
        lay.addLayout(vrow)
        crow = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Describe what you want to do, or edit the plan: “add task Write tests to Build”…")
        self.input.setAccessibleName("Message to Prometheus")
        self.input.returnPressed.connect(lambda: self.say(self.input.text()))
        crow.addWidget(self.input, 1)
        send = QPushButton("Send")
        send.clicked.connect(lambda: self.say(self.input.text()))
        crow.addWidget(send)
        lay.addLayout(crow)
        self.voice_info = label("", "faint")
        lay.addWidget(self.voice_info)
        return w

    def _step_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(8)
        self.step_title = label("Select a task on the canvas or in the outline.", "h3")
        lay.addWidget(self.step_title)
        self.step_meta = label("", "faint")
        lay.addWidget(self.step_meta)
        self.step_detail = QTextBrowser()
        self.step_detail.setAccessibleName("Selected step details")
        lay.addWidget(self.step_detail, 1)
        self.card_slot = QVBoxLayout()
        lay.addLayout(self.card_slot)
        from PyQt6.QtWidgets import QGridLayout

        grid = QGridLayout()
        grid.setSpacing(6)
        self.step_buttons: Dict[str, QPushButton] = {}
        for key, text, fn in (("rename", "Rename", self._rename_selected), ("phase", "Move to…", self._move_selected), ("prio", "Priority…", self._prio_selected), ("op", "Done by…", self._op_selected), ("dep", "Waits for…", self._dep_selected), ("remove", "Remove", lambda: self.apply_edit("remove_task", ref=self.stage.sel))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            self.step_buttons[key] = b
            grid.addWidget(b, (len(self.step_buttons) - 1) // 3, (len(self.step_buttons) - 1) % 3)
        lay.addLayout(grid)
        arow = QHBoxLayout()
        add = QPushButton("Add task…")
        add.clicked.connect(self._add_task)
        arow.addWidget(add)
        self.undo_btn = QPushButton("Undo last change")
        self.undo_btn.clicked.connect(self.undo)
        arow.addWidget(self.undo_btn)
        arow.addStretch(1)
        lay.addLayout(arow)
        return w

    def _versions_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 8, 0, 0)
        self.versions = QListWidget()
        self.versions.setAccessibleName("Plan versions")
        self.versions.currentRowChanged.connect(self._version_selected)
        lay.addWidget(self.versions, 1)
        self.diff = QTextBrowser()
        self.diff.setMaximumHeight(170)
        lay.addWidget(self.diff)
        row = QHBoxLayout()
        self.restore_btn = QPushButton("Restore this version")
        self.restore_btn.clicked.connect(self.restore_version)
        row.addWidget(self.restore_btn)
        row.addStretch(1)
        lay.addLayout(row)
        self.events = QTextBrowser()
        self.events.setMaximumHeight(140)
        self.events.setAccessibleName("Session activity")
        lay.addWidget(label("ACTIVITY", "eyebrow"))
        lay.addWidget(self.events)
        return w

    # ----- sessions -----
    def new_session(self, objective: str = "", context: Optional[Dict[str, Any]] = None) -> None:
        if self.worker_busy():
            self.notify("Finish or cancel the current work first", "", "warn")
            return
        self._save()
        s = O.new_session(objective[:60] if objective else "", context)
        s["autonomy"] = self.settings.get("orbit_autonomy") if self.settings.get("orbit_autonomy") in O.AUTONOMY else "approval_first"
        conv = self.conversations.create([], title=f"ORBIT · {s['title']}"[:80])
        conv["orbit"] = s["id"]
        self.conversations.save(conv)
        s["conversation_id"] = conv["id"]
        O.log(s, "session.created", objective)
        self.store.save(s)
        self.open_session(s["id"], quiet=True)
        if objective:
            self.say(objective)

    def open_session(self, sid: str, quiet: bool = False) -> None:
        if self.worker_busy():
            self.notify("Finish or cancel the current work first", "", "warn")
            self._fill_sessions()
            return
        self._save()
        s = self.store.get(sid) if sid else None
        if s is None:
            s = O.new_session()
            s["autonomy"] = self.settings.get("orbit_autonomy") if self.settings.get("orbit_autonomy") in O.AUTONOMY else "approval_first"
            self._fresh = True
        else:
            self._fresh = False
        self.session = s
        if s.get("events") and s["events"][-1]["kind"] == "session.restored" and not quiet:
            self.notify("Session restored", s["events"][-1]["detail"], "warn")
        self.settings.set("orbit_session", s["id"] if not self._fresh else "")
        i = self.autonomy.findData(s.get("autonomy", "approval_first"))
        self.autonomy.blockSignals(True)
        self.autonomy.setCurrentIndex(max(0, i))
        self.autonomy.blockSignals(False)
        self._render_transcript()
        self.render_all()
        self._fill_sessions()

    def _ensure_saved_session(self) -> None:
        """A blank session is saved (and gets its conversation) on its first real use."""
        if getattr(self, "_fresh", False):
            conv = self.conversations.create([], title="ORBIT · New session")
            conv["orbit"] = self.session["id"]
            self.conversations.save(conv)
            self.session["conversation_id"] = conv["id"]
            O.log(self.session, "session.created")
            self._fresh = False
            self.store.save(self.session)
            self.settings.set("orbit_session", self.session["id"])
            self._fill_sessions()

    def _fill_sessions(self) -> None:
        self.session_box.blockSignals(True)
        self.session_box.clear()
        rows = self.store.list()
        if getattr(self, "_fresh", False):
            self.session_box.addItem("New session (not saved yet)", "")
        for r in rows:
            wf = f" · {WF_WORDS.get(r['workflow'], r['workflow'])}" if r["workflow"] else ""
            self.session_box.addItem(f"{r['title']}{wf}", r["id"])
        idx = self.session_box.findData(self.session.get("id")) if not getattr(self, "_fresh", False) else 0
        self.session_box.setCurrentIndex(max(0, idx))
        self.session_box.blockSignals(False)

    def rename_session(self) -> None:
        name, ok = QInputDialog.getText(self, "Rename session", "Name:", text=self.session.get("title", ""))
        if ok and name.strip():
            self._ensure_saved_session()
            self.session["title"] = name.strip()[:80]
            self._save()
            self._fill_sessions()

    def archive_session(self) -> None:
        if self._fresh or self.worker_busy():
            return
        self.session["archived"] = True
        O.log(self.session, "session.archived")
        self._save()
        self.notify("Session archived", "It is kept on disk; it no longer appears in the list.", "ok")
        self.open_session("")

    def delete_session(self) -> None:
        if self._fresh or self.worker_busy():
            return
        if QMessageBox.question(self, "Delete session", f"Delete “{self.session['title']}”, its plan versions and workflow record? Its conversation stays in the Companion.") != QMessageBox.StandardButton.Yes:
            return
        self.store.delete(self.session["id"])
        self.notify("Session deleted", self.session["title"], "ok")
        self.session = {}
        self.open_session("")

    def _save(self) -> None:
        if self.session and not getattr(self, "_fresh", False):
            self.store.save(self.session)

    # ----- rendering -----
    def plan(self) -> Optional[Dict[str, Any]]:
        return O.current_plan(self.session) if self.session else None

    def render_all(self) -> None:
        plan = self.plan()
        wf = self.session.get("workflow")
        status = {n["id"]: n["status"] for n in wf["nodes"]} if wf else {}
        self.stage.set_plan(plan, status)
        v, a = self.session.get("active_version", 0), self.session.get("approved_version", 0)
        if plan:
            approved = "approved" if a == v else f"draft (approved: v{a})" if a else "draft, not approved"
            obj = f" — {plan['objective']}" if plan["objective"] else ""
            self.plan_line.setText(f"<b>{plan['title']}</b>{obj}<br><span style='color:{T.TEXT_FAINT}'>Version {v} · {approved} · {len(plan['tasks'])} tasks in {len(plan['phases'])} phases · {len(plan['questions'])} open questions</span>")
        else:
            self.plan_line.setText("Tell Prometheus what you want to achieve. As you talk, the plan forms around the sun; you shape it, approve it, then run it.")
        self._fill_outline(plan, status)
        self._fill_versions()
        self._update_controls()
        self.select_task(self.stage.sel)
        ev = self.session.get("events", [])[-40:]
        self.events.setHtml("<br>".join(f"<span style='color:{T.TEXT_FAINT}'>{e['ts'][11:16]}</span> {e['kind']} {e['detail']}" for e in reversed(ev)))

    def _fill_outline(self, plan, status) -> None:
        self.outline.blockSignals(True)
        self.outline.clear()
        if plan:
            for ph in plan["phases"]:
                top = QTreeWidgetItem([ph, "", "", ""])
                top.setFlags(top.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                self.outline.addTopLevelItem(top)
                for t in [t for t in plan["tasks"] if t["phase"] == ph]:
                    st = status.get(t["id"]) or t["status"]
                    mark, word = STATUS_MARK.get(st, ("", st))
                    it = QTreeWidgetItem([t["title"], f"{mark} {word}", t["priority"], O.OPERATIONS[t["operation"]]["name"]])
                    it.setData(0, Qt.ItemDataRole.UserRole, t["id"])
                    top.addChild(it)
                    if t["id"] == self.stage.sel:
                        it.setSelected(True)
                top.setExpanded(True)
            for i in range(4):
                self.outline.resizeColumnToContents(i)
        self.outline.blockSignals(False)

    def _outline_selected(self) -> None:
        items = self.outline.selectedItems()
        if items and items[0].data(0, Qt.ItemDataRole.UserRole):
            self.stage.select(items[0].data(0, Qt.ItemDataRole.UserRole))

    def _fill_versions(self) -> None:
        self.versions.blockSignals(True)
        self.versions.clear()
        for pv in reversed(self.session.get("plan_versions", [])):
            flags = []
            if pv["version"] == self.session.get("active_version"):
                flags.append("active")
            if pv["version"] == self.session.get("approved_version"):
                flags.append("approved")
            who = "You" if pv["author"] == "you" else "Prometheus"
            it = QListWidgetItem(f"v{pv['version']} · {who} · {pv['ts'][11:16]}{' · ' + ', '.join(flags) if flags else ''}\n{pv['why']}")
            it.setData(Qt.ItemDataRole.UserRole, pv["version"])
            self.versions.addItem(it)
        self.versions.blockSignals(False)
        self.diff.setPlainText("Select a version to compare it with the active one.")
        self.restore_btn.setEnabled(False)

    def _version_selected(self, row: int) -> None:
        it = self.versions.item(row)
        if it is None:
            return
        v = it.data(Qt.ItemDataRole.UserRole)
        act = self.session.get("active_version", 0)
        self.restore_btn.setEnabled(v != act and not self._running())
        if v == act:
            self.diff.setPlainText("This is the active version.")
            return
        a = self.session["plan_versions"][v - 1]["plan"]
        b = self.session["plan_versions"][act - 1]["plan"]
        changes = O.compare(a, b)
        self.diff.setPlainText(f"From v{v} to the active v{act}:\n" + ("\n".join(changes) if changes else "No differences."))

    def select_task(self, tid: str) -> None:
        plan = self.plan()
        t = O.task(plan, tid) if plan and tid else None
        for b in self.step_buttons.values():
            b.setEnabled(t is not None and not self._running())
        self.undo_btn.setEnabled(self.session.get("active_version", 0) > 1 and not self._running())
        if t is None:
            self.step_title.setText("Select a task on the canvas or in the outline." if plan else "No plan yet.")
            self.step_meta.setText("")
            self.step_detail.setHtml(f"<p style='color:{T.TEXT_SECONDARY}'>" + ("<br>".join(f"? {q}" for q in plan["questions"]) if plan and plan["questions"] else "") + "</p>")
            return
        wf = self.session.get("workflow")
        node = next((n for n in wf["nodes"] if n["id"] == t["id"]), None) if wf else None
        st = node["status"] if node else t["status"]
        mark, word = STATUS_MARK.get(st, ("", st))
        self.step_title.setText(t["title"])
        deps = [O.task(plan, d["from"]) for d in plan["deps"] if d["to"] == t["id"]]
        op = O.OPERATIONS[t["operation"]]
        self.step_meta.setText(f"{mark} {word} · {t['phase']} · {t['priority']} priority" + (f" · estimate {t['estimate']}" if t["estimate"] else "") + f"\nDone by: {op['name']} — {op['runs']}" + (f"\nWaits for: {', '.join(d['title'] for d in deps if d)}" if deps else ""))
        html = f"<p>{t['detail'] or '<i>No detail.</i>'}</p>"
        if node:
            if node.get("output"):
                html += f"<h4>Result</h4><p>{self._html(node['output'])}</p>"
            if node.get("error"):
                html += f"<p style='color:{T.ERR}'>Error: {node['error']}</p>"
            html += "<h4>History</h4>" + "<br>".join(f"<span style='color:{T.TEXT_FAINT}'>{h['ts'][11:19]}</span> {h['event']}" + (f" — {h['detail']}" if h.get("detail") else "") for h in node["history"])
        self.step_detail.setHtml(html)

    def _update_controls(self) -> None:
        wf = self.session.get("workflow")
        plan = self.plan()
        v, a = self.session.get("active_version", 0), self.session.get("approved_version", 0)
        running = self._running()
        state = wf["state"] if wf else ""
        waiting_node = next((n for n in wf["nodes"] if n["status"] == "awaiting_approval"), None) if wf else None
        en = {
            "approve": bool(plan and plan["tasks"]) and v != a and not running,
            "build": bool(plan and plan["tasks"]) and a == v and a > 0 and not running and (not wf or state in ("completed", "cancelled") or wf["plan_version"] != a),
            "start": bool(wf) and not running and not wf.get("paused") and O.next_node(wf) is not None and waiting_node is None,
            "go": waiting_node is not None and self.card is None and not self.worker_busy(),
            "pause": bool(wf) and not wf.get("paused") and state not in ("completed", "cancelled"),
            "resume": bool(wf) and bool(wf.get("paused")),
            "retry": bool(wf) and not running and self._selected_node_status() in ("failed", "cancelled", "blocked"),
            "cancel": bool(wf) and state not in ("completed", "cancelled"),
        }
        # only what can be done now is shown; Pause and Cancel stay visible while a workflow exists
        for k, b in self.wf_buttons.items():
            b.setEnabled(en[k])
            b.setVisible(en[k] or (k in ("pause", "cancel") and bool(wf) and state not in ("completed", "cancelled")))
        if wf:
            done = sum(1 for n in wf["nodes"] if n["status"] == "completed")
            self.wf_lbl.setText(f"Workflow (from v{wf['plan_version']}): {WF_WORDS.get(state, state)}{' · paused' if wf.get('paused') and state != 'paused' else ''} · {done}/{len(wf['nodes'])} steps done")
        elif plan:
            self.wf_lbl.setText("Approve the plan, then build its workflow." if a != v else "Approved. Build the workflow when you are ready.")
        else:
            self.wf_lbl.setText("")

    def _selected_node_status(self) -> str:
        wf = self.session.get("workflow")
        n = next((n for n in wf["nodes"] if n["id"] == self.stage.sel), None) if wf else None
        return n["status"] if n else ""

    def toggle_view(self) -> None:
        outline = self.views.currentWidget() is self.stage
        self.views.setCurrentWidget(self.outline if outline else self.stage)
        self.view_btn.setText("Orbit view" if outline else "Outline")

    def set_immersive(self, on: bool) -> None:
        self.immersive = on
        self.imm_btn.setText("Exit immersive" if on else "Immersive")
        self.immersive_changed.emit(on)

    def set_reduced_motion(self, reduced: bool) -> None:
        self.stage.set_reduced_motion(reduced)

    # ----- avatar and state -----
    def set_state(self, state: str) -> None:
        """Avatar states come only from real events: listening (mic open), thinking (a reply is being made),
        planning (a plan is arriving), speaking (audio playing), running (a workflow step executes)."""
        from .companion import ORB_STATES

        self.state = state
        wf = self.session.get("workflow")
        progress = (sum(1 for n in wf["nodes"] if n["status"] == "completed") / len(wf["nodes"])) if wf and wf["nodes"] else 0.0
        avatar = {"RUNNING": "EXECUTING"}.get(state, state)
        self.stage.set_state(avatar, progress)
        _, text, colour = ORB_STATES.get(state, ORB_STATES["IDLE"])
        self.state_line.setText(f"● {text}" + ("  ·  microphone on" if state == "LISTENING" else ""))
        self.state_line.setStyleSheet(f"color: {colour};")
        self.state_line.setAccessibleName(f"Prometheus is {text.lower()}")
        self.state_changed.emit(state)

    # ----- the conversation -----
    def worker_busy(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def _running(self) -> bool:
        return self.worker_busy() and self.worker_kind != "talk"

    def _render_transcript(self) -> None:
        conv = self.conversations.get(self.session.get("conversation_id", "")) if self.session.get("conversation_id") else None
        msgs = self.visible(conv["messages"]) if conv else []
        self._lines = []
        for m in msgs[-60:]:
            self._line("You" if m["role"] == "user" else "Prometheus", O.strip_plan_blocks(m["content"]))
        if not msgs:
            self._line("ORBIT", "Say or type what you want to achieve. Prometheus asks what it needs to know, then proposes a plan you can change by voice or by hand. Nothing runs until you approve.", T.TEXT_FAINT)
        self._flush()

    def _line(self, who: str, text: str, colour: str = "") -> None:
        colour = colour or (T.HIGHLIGHT if who == "You" else T.ACCENT if who == "Prometheus" else T.TEXT_SECONDARY)
        body = self._html(text)
        self._lines.append(f"<p><b style='color:{colour}'>{who}</b><br>{body}</p>")

    def _html(self, text: str) -> str:
        try:
            return self.md.render_markdown(text)
        except Exception:
            return self.md.esc(text).replace("\n", "<br>")

    def _flush(self, streaming: str = "") -> None:
        extra = f"<p><b style='color:{T.ACCENT}'>Prometheus</b><br>{streaming.replace('<', '&lt;')}</p>" if streaming else ""
        self.transcript.setHtml("".join(self._lines[-80:]) + extra)
        sb = self.transcript.verticalScrollBar()
        sb.setValue(sb.maximum())

    def say(self, text: str) -> None:
        """What you said or typed: a direct plan edit or control word is handled here; anything else goes to Prometheus."""
        text = (text or "").strip()
        if not text:
            return
        self.input.clear()
        cmd = O.parse_command(text, self.plan())
        if cmd and "control" in cmd:
            self._line("You", text)
            self._flush()
            {"stop_speaking": self.stop_speaking, "pause": self.pause_workflow, "resume": self.resume_workflow, "cancel": self.cancel_workflow}[cmd["control"]]()
            return
        if cmd and cmd.get("undo"):
            self._line("You", text)
            self.undo()
            return
        if cmd and "op" in cmd:
            self._line("You", text)
            op = cmd.pop("op")
            self.apply_edit(op, why=text, **cmd)
            return
        if self.worker_busy():
            self._line("ORBIT", "Prometheus is still working. Stop it first, or wait.", T.WARN)
            self._flush()
            return
        if not self.core.router.configured:
            self._line("ORBIT", "No model provider is configured, so nothing was sent. Add a key in Settings → Providers, or start Ollama. Plan edits like “add task …” still work.", T.WARN)
            self._flush()
            self.set_state("OFFLINE")
            return
        self._ensure_saved_session()
        conv = self.conversations.get(self.session["conversation_id"])
        if conv is None:
            conv = self.conversations.create([], title=f"ORBIT · {self.session['title']}"[:80])
            self.session["conversation_id"] = conv["id"]
        if self.session["title"] == "New ORBIT session":
            self.session["title"] = text[:60]
            self._fill_sessions()
        conv["messages"].append({"role": "user", "content": text})
        self.conversations.save(conv)
        self._conv = conv
        self._line("You", text)
        self._flush()
        plan = self.plan()
        context = O.INSTRUCTION + ("Current plan (version %d): %s" % (self.session["active_version"], json.dumps(plan, ensure_ascii=False)[:6000]) if plan else "There is no plan yet.")
        self._talk_msgs = [{"role": "system", "content": context}] + conv["messages"]
        self._stream = ""
        self._start_worker(self._talk_msgs, "talk")
        self.set_state("THINKING")

    def _start_worker(self, msgs: List[dict], kind: str) -> None:
        w = self.g.PrometheusWorker(self.core.router, msgs, auto_approve=False, fallback_models=self.config.get("fallback_models"))
        w.text_delta.connect(self._delta)
        w.status_updated.connect(self._status)
        w.confirmation_requested.connect(self._confirm)
        w.tool_executed.connect(self._tool_done)
        w.finished.connect(self._finished)
        self.worker, self.worker_kind, self.last_error = w, kind, ""
        self._cancelling = False
        w.start()
        self._update_controls()

    def _delta(self, raw: str) -> None:
        self._stream = raw
        if self.worker_kind != "talk":
            return
        partial = O.partial_plan(raw)
        if partial["tasks"] or partial["phases"]:
            if self.state != "PLANNING":
                self.set_state("PLANNING")
            if not self.plan():
                self.stage.set_provisional(partial)
        self._flush(O.strip_plan_blocks(raw))

    def _status(self, text: str, _c: str = "") -> None:
        t = (text or "").strip()
        if t.startswith("CORE ERROR:"):
            self.last_error = t.split(":", 1)[1].strip()
        elif t.startswith("ADAPTING SYSTEM LOGIC:") and self.worker_kind == "talk":
            self.set_state("WORKING")

    def _tool_done(self, tool: str, _args: str, result: str) -> None:
        try:
            status = json.loads(result).get("status", "done")
        except Exception:
            status = "done"
        if self.worker_kind == "talk":
            self._line("Tool", f"{tool} — {status}", T.TEXT_SECONDARY)
            self._flush(O.strip_plan_blocks(self._stream))
        else:
            self._node_event(self.worker_kind, f"tool {tool}: {status}")

    def _confirm(self, tool: str, args_json: str) -> None:
        """A tool with real-world effects asks, every time, whatever the autonomy level."""
        from ...services import forge_missions as F
        from .companion import ApprovalCard

        node = self._node(self.worker_kind) if self.worker_kind != "talk" else None
        if node and node["operation"].startswith("forge:"):
            try:
                args = json.loads(args_json)
            except Exception:
                args = {}
            ok, reason = F.decide(node["operation"].split(":", 1)[1], tool, args if isinstance(args, dict) else {}, self.core.paths()["workspace"])
            if not ok:
                self.worker.provide_confirmation(False)
                self.core.p.audit_log.record(tool, args, "refused", f"ORBIT step ({node['operation']}): {reason}")
                self._node_event(node["id"], f"refused {tool}: {reason}")
                return
        if node:
            self._transition(node["id"], "awaiting_approval", f"asks to use {tool}")
        self.set_state("WARNING")
        self._clear_card()
        self.card = ApprovalCard(tool, args_json, workspace=self.core.paths()["workspace"], reason=self._stream[-600:])
        self.card.answered.connect(lambda ok, t=tool: self._answer(t, ok))
        self.card_slot.addWidget(self.card)
        if node:
            self.stage.select(node["id"])
        self.tabs.setCurrentIndex(1)
        self.speak(f"I need your approval to use {tool.replace('_', ' ')}.")
        self._update_controls()

    def _answer(self, tool: str, ok: bool) -> None:
        self._clear_card()
        if self.worker is not None:
            self.worker.provide_confirmation(ok)
        node = self._node(self.worker_kind) if self.worker_kind != "talk" else None
        if node and node["status"] == "awaiting_approval":
            self._transition(node["id"], "running", f"you {'approved' if ok else 'denied'} {tool}")
        self.set_state("RUNNING" if node else "THINKING")
        self._update_controls()

    def _clear_card(self) -> None:
        if self.card is not None:
            self.card.setParent(None)
            self.card.deleteLater()
            self.card = None

    def _finished(self) -> None:
        kind, self.worker_kind = self.worker_kind, ""
        self._clear_card()
        if kind == "talk":
            self._finish_talk()
        elif kind:
            self._finish_node(kind)
        self._save()
        self.render_all()

    def _finish_talk(self) -> None:
        conv = self._conv
        conv["messages"] = [m for m in self._talk_msgs if m.get("role") != "system"]
        self.g.trim_messages(conv["messages"], self.g.MAX_SESSION_MESSAGES)
        self.conversations.save(conv)
        reply = next((m.get("content") or "" for m in reversed(conv["messages"]) if m.get("role") == "assistant" and isinstance(m.get("content"), str) and m["content"].strip()), "")
        if self.last_error:
            self._line("ORBIT", f"Something went wrong: {self.last_error}", T.ERR)
            self.set_state("ERROR")
        elif reply:
            self._line("Prometheus", O.strip_plan_blocks(reply))
            plan = O.extract_plan(reply)
            if plan and plan["tasks"]:
                prev = self.plan()
                v = O.add_version(self.session, plan, "prometheus", "Proposed in conversation" if not prev else "Revised in conversation")
                if prev:
                    self._line("ORBIT", f"Plan updated to version {v}: " + ("; ".join(O.compare(prev, self.plan())[:6]) or "no structural change") + ". Review it, then approve.", T.TEXT_SECONDARY)
                else:
                    self._line("ORBIT", f"Plan version {v} is a draft: {len(plan['tasks'])} tasks. Change anything, then approve it.", T.TEXT_SECONDARY)
            self.speak(O.strip_plan_blocks(reply))
        else:
            self.set_state("IDLE")
        self._flush()

    # ----- plan editing -----
    def apply_edit(self, op: str, why: str = "", **a) -> bool:
        plan = self.plan()
        if plan is None and op == "add_task":
            plan = O.empty_plan(self.session.get("title", ""), "")
        if plan is None:
            self._line("ORBIT", "There is no plan to change yet.", T.WARN)
            self._flush()
            return False
        if self._running():
            self.notify("The workflow is running", "Pause or cancel it before changing the plan.", "warn")
            return False
        try:
            new, desc = O.edit(plan, op, **a)
        except O.PlanError as e:
            self._line("ORBIT", str(e), T.WARN)
            self._flush()
            return False
        self._ensure_saved_session()
        O.add_version(self.session, new, "you", why or desc)
        self._line("ORBIT", desc + " (new version; undo restores the previous one)", T.TEXT_SECONDARY)
        self._flush()
        self._save()
        self.render_all()
        return True

    def undo(self) -> None:
        v = self.session.get("active_version", 0)
        if v <= 1 or self._running():
            return
        prev = self.session["plan_versions"][v - 2]["plan"]
        O.add_version(self.session, prev, "you", f"Undo: back to the plan of version {v - 1}")
        self._line("ORBIT", f"Undone: the plan is back to version {v - 1}'s content (kept as a new version).", T.TEXT_SECONDARY)
        self._flush()
        self._save()
        self.render_all()

    def restore_version(self) -> None:
        it = self.versions.currentItem()
        if it is None or self._running():
            return
        v = it.data(Qt.ItemDataRole.UserRole)
        O.add_version(self.session, self.session["plan_versions"][v - 1]["plan"], "you", f"Restored version {v}")
        self._save()
        self.render_all()
        self.notify(f"Version {v} restored", "It is now the active version, as a new version.", "ok")

    def _pick(self, title: str, label_: str, items: List[str], current: int = 0) -> Optional[str]:
        v, ok = QInputDialog.getItem(self, title, label_, items, current, False)
        return v if ok else None

    def _rename_selected(self) -> None:
        t = O.task(self.plan(), self.stage.sel)
        if t:
            name, ok = QInputDialog.getText(self, "Rename task", "Name:", text=t["title"])
            if ok:
                self.apply_edit("rename_task", ref=t["id"], title=name)

    def _move_selected(self) -> None:
        plan, t = self.plan(), O.task(self.plan(), self.stage.sel)
        if t:
            names = [p for p in plan["phases"]] + ["New phase…"]
            ph = self._pick("Move task", "Phase:", names, names.index(t["phase"]))
            if ph == "New phase…":
                ph, ok = QInputDialog.getText(self, "New phase", "Phase name:")
                ph = ph if ok else None
            if ph:
                self.apply_edit("move_to_phase", ref=t["id"], phase=ph)

    def _prio_selected(self) -> None:
        t = O.task(self.plan(), self.stage.sel)
        if t:
            p = self._pick("Priority", "Priority:", ["high", "normal", "low"], ["high", "normal", "low"].index(t["priority"]))
            if p:
                self.apply_edit("set_priority", ref=t["id"], priority=p)

    def _op_selected(self) -> None:
        t = O.task(self.plan(), self.stage.sel)
        if t:
            keys = list(O.OPERATIONS)
            names = [f"{O.OPERATIONS[k]['name']} — {O.OPERATIONS[k]['runs']}" for k in keys]
            p = self._pick("Done by", "Which capability does this step:", names, keys.index(t["operation"]))
            if p:
                self.apply_edit("set_operation", ref=t["id"], operation=keys[names.index(p)])

    def _dep_selected(self) -> None:
        plan, t = self.plan(), O.task(self.plan(), self.stage.sel)
        if t:
            others = [x["title"] for x in plan["tasks"] if x["id"] != t["id"]]
            if not others:
                return
            linked = {d["from"] for d in plan["deps"] if d["to"] == t["id"]}
            names = [f"{'✓ ' if x['id'] in linked else ''}{x['title']}" for x in plan["tasks"] if x["id"] != t["id"]]
            p = self._pick("Waits for", f"“{t['title']}” waits for (choose a ticked one to unlink):", names)
            if p:
                other = others[names.index(p)]
                self.apply_edit("remove_dep" if p.startswith("✓ ") else "add_dep", before=other, after=t["id"])

    def _add_task(self) -> None:
        name, ok = QInputDialog.getText(self, "Add task", "Task:")
        if ok and name.strip():
            plan = self.plan()
            phase = ""
            if plan and plan["phases"]:
                phase = self._pick("Add task", "Phase:", plan["phases"], len(plan["phases"]) - 1) or ""
            self.apply_edit("add_task", title=name, phase=phase)

    def _autonomy_changed(self) -> None:
        key = self.autonomy.currentData()
        if not self.session or key == self.session.get("autonomy"):
            return
        self.session["autonomy"] = key
        if self.session.get("workflow"):
            self.session["workflow"]["autonomy"] = key
        self.settings.set("orbit_autonomy", key)
        O.log(self.session, "autonomy.changed", key)
        self._save()
        self.autonomy.setToolTip(O.AUTONOMY_TEXT[key])
        self.notify(f"Autonomy: {self.autonomy.currentText()}", O.AUTONOMY_TEXT[key], "ok")
        if key == "advanced":
            self._choose_allowed()

    def _choose_allowed(self) -> None:
        current = set(self.session.get("allowed") or [])
        box = QMessageBox(self)
        box.setWindowTitle("Advanced autonomy")
        box.setText("Which kinds of step may start without you? Tools with real-world effects still ask every time.")
        checks = {}
        w = QWidget()
        v = QVBoxLayout(w)
        for c, text in (("think", "Thinking and writing"), ("read", "Reading and investigating (Architect)"), ("organise", "Scheduling reminders"), ("change", "Changing files (Builder, Debugger, Reconstructor)")):
            cb = QCheckBox(text)
            cb.setChecked(c in current)
            checks[c] = cb
            v.addWidget(cb)
        box.layout().addWidget(w, 1, 1)
        box.exec()
        self.session["allowed"] = [c for c, cb in checks.items() if cb.isChecked()]
        if self.session.get("workflow"):
            self.session["workflow"]["allowed"] = list(self.session["allowed"])
        O.log(self.session, "autonomy.allowed", ", ".join(self.session["allowed"]) or "none")
        self._save()

    # ----- plan approval and the workflow -----
    def approve_plan(self) -> None:
        v = self.session.get("active_version", 0)
        plan = self.plan()
        if not plan or not plan["tasks"] or v == self.session.get("approved_version") or self._running():
            return
        self.session["approved_version"] = v
        for t in self.session["plan_versions"][v - 1]["plan"]["tasks"]:
            t["status"] = "confirmed"
        O.log(self.session, "plan.approved", f"version {v} approved by you")
        self._save()
        self.render_all()
        self.notify(f"Plan version {v} approved", "Build the workflow to see how it will be done.", "ok")

    def build_workflow(self) -> None:
        a = self.session.get("approved_version", 0)
        if not a or a != self.session.get("active_version") or self._running():
            return
        plan = self.session["plan_versions"][a - 1]["plan"]
        self.session["workflow"] = O.make_workflow(plan, a, self.session.get("autonomy", "approval_first"), self.session.get("allowed"))
        O.log(self.session, "workflow.built", f"{len(plan['tasks'])} steps from version {a}")
        self._save()
        self.render_all()

    def _node(self, nid: str) -> Optional[Dict[str, Any]]:
        wf = self.session.get("workflow")
        return next((n for n in wf["nodes"] if n["id"] == nid), None) if wf else None

    def _transition(self, nid: str, new: str, detail: str = "") -> bool:
        try:
            O.transition(self.session["workflow"], nid, new, detail)
        except ValueError as e:
            self._node_event(nid, f"(not applied: {e})")
            return False
        O.log(self.session, f"step.{new}", f"{self._node(nid)['title']}" + (f": {detail}" if detail else ""))
        self._save()
        return True

    def _node_event(self, nid: str, detail: str) -> None:
        n = self._node(nid)
        if n:
            n["history"].append({"ts": O.now(), "event": detail, "status": n["status"]})

    def start_workflow(self) -> None:
        wf = self.session.get("workflow")
        if not wf or self.worker_busy():
            return
        node = O.next_node(wf)
        if node is None:
            return
        if O.needs_go_ahead(wf, node):
            self._transition(node["id"], "awaiting_approval", "waiting for your go-ahead (autonomy: %s)" % wf["autonomy"])
            self.stage.select(node["id"])
            self.tabs.setCurrentIndex(1)
            self.set_state("WARNING")
            self.speak(f"Ready for the next step: {node['title']}. Approve it when you are ready.")
            self.render_all()
            return
        self._run_node(node)

    def approve_step(self) -> None:
        wf = self.session.get("workflow")
        node = next((n for n in wf["nodes"] if n["status"] == "awaiting_approval"), None) if wf else None
        if node is None or self.worker_busy():
            return
        if node["operation"] == "manual":
            self._transition(node["id"], "running", "you are doing it")
            self._transition(node["id"], "completed", "marked done by you")
            self.render_all()
            self._advance()
            return
        self._transition(node["id"], "running", "you gave the go-ahead")
        self._run_node(node, already_running=True)

    def _run_node(self, node: Dict[str, Any], already_running: bool = False) -> None:
        from ...services import forge_missions as F

        if not self.core.router.configured:
            self.notify("No model provider", "Add a key in Settings → Providers, or start Ollama.", "warn")
            if already_running:
                self._transition(node["id"], "failed", "no model provider configured")
            self.render_all()
            return
        if not already_running and not self._transition(node["id"], "running", "started automatically (autonomy: %s)" % self.session["workflow"]["autonomy"]):
            return
        plan = self.session["plan_versions"][self.session["workflow"]["plan_version"] - 1]["plan"]
        task = f"{node['title']}." + (f" {node['detail']}" if node["detail"] else "")
        op = node["operation"]
        if op.startswith("forge:"):
            text = F.prompt(op.split(":", 1)[1], "the current workspace", task)
        elif op == "reminder":
            text = f"Schedule this reminder with the schedule_task tool, then confirm what was scheduled: {task}"
        else:
            text = f"This is one step of the approved plan “{plan['title']}” (objective: {plan['objective'] or 'not stated'}). Do this step and only this step: {task}\nReport plainly what you did, what you found and anything left open."
        conv = self.conversations.create([{"role": "user", "content": text}], title=f"ORBIT step · {node['title']}"[:80])
        conv["orbit"] = self.session["id"]
        if op.startswith("forge:"):
            conv["mission"] = {"id": "", "discipline": op.split(":", 1)[1], "project": "workspace"}
        self.conversations.save(conv)
        node["conversation_id"] = conv["id"]
        self._node_conv = conv
        self.stage.select(node["id"])
        self._start_worker(conv["messages"], node["id"])
        self.set_state("RUNNING")
        self.render_all()

    def _finish_node(self, nid: str) -> None:
        conv = self._node_conv
        self.g.trim_messages(conv["messages"], self.g.MAX_SESSION_MESSAGES)
        self.conversations.save(conv)
        node = self._node(nid)
        if node is None:
            return
        reply = next((m.get("content") or "" for m in reversed(conv["messages"]) if m.get("role") == "assistant" and isinstance(m.get("content"), str) and m["content"].strip()), "")
        if node["status"] == "awaiting_approval":
            self._transition(nid, "running", "approval closed")
        if self._cancelling:
            if node["status"] == "running":
                self._transition(nid, "cancelled", "you cancelled the workflow")
            self.set_state("IDLE")
            return
        if self.last_error:
            node["error"] = self.last_error[:400]
            self._transition(nid, "failed", self.last_error[:200])
            self.set_state("ERROR")
            self.speak(f"The step {node['title']} failed. You can retry it or change the plan.")
            self.notify("A workflow step failed", node["title"], "err")
            return
        node["output"] = reply[:4000]
        self._transition(nid, "completed", "finished")
        self.set_state("RUNNING")
        self._advance()

    def _advance(self) -> None:
        wf = self.session.get("workflow")
        self.render_all()
        if not wf:
            return
        if wf["state"] == "completed":
            self.set_state("SUCCESS")
            self.speak("The workflow is complete.")
            self.notify("Workflow complete", self.session["title"], "ok")
            return
        if wf.get("paused"):
            self.set_state("PAUSED")
            return
        if O.next_node(wf) is not None:
            QTimer.singleShot(300, self.start_workflow)
        else:
            self.set_state("IDLE")

    def pause_workflow(self) -> None:
        wf = self.session.get("workflow")
        if not wf or wf.get("paused"):
            return
        wf["paused"] = True
        for n in wf["nodes"]:
            if n["status"] in ("ready", "awaiting_approval") and not (self._running() and n["id"] == self.worker_kind):
                O.transition(wf, n["id"], "paused", "workflow paused")
        wf["state"] = O.workflow_state(wf)
        O.log(self.session, "workflow.paused", "the running step, if any, finishes; nothing new starts")
        self._save()
        self.render_all()
        self.notify("Workflow paused", "The running step finishes or can be cancelled; nothing new starts." if self._running() else "Nothing new starts until you resume.", "ok")

    def resume_workflow(self) -> None:
        wf = self.session.get("workflow")
        if not wf or not wf.get("paused"):
            return
        wf["paused"] = False
        for n in wf["nodes"]:
            if n["status"] == "paused":
                deps_done = all(self._node(d)["status"] == "completed" for d in n["deps"])
                O.transition(wf, n["id"], "ready", "resumed")
                if not deps_done:
                    n["status"] = "waiting"
        wf["state"] = O.workflow_state(wf)
        O.log(self.session, "workflow.resumed")
        self._save()
        self.render_all()
        if not self.worker_busy():
            self.start_workflow()

    def retry_step(self) -> None:
        wf = self.session.get("workflow")
        n = self._node(self.stage.sel)
        if not wf or not n or n["status"] not in ("failed", "cancelled", "blocked") or self.worker_busy():
            return
        n["error"] = ""
        self._transition(n["id"], "ready", "retry requested by you")
        if not all(self._node(d)["status"] == "completed" for d in n["deps"]):
            n["status"] = "waiting"
        wf["paused"] = False
        wf["state"] = O.workflow_state(wf)
        self.render_all()
        self.start_workflow()

    def cancel_workflow(self) -> None:
        wf = self.session.get("workflow")
        if not wf or wf["state"] in ("completed", "cancelled"):
            return
        if QMessageBox.question(self, "Cancel workflow", "Stop the running step and cancel every step that has not finished? Completed steps stay completed; nothing is undone.") != QMessageBox.StandardButton.Yes:
            return
        if self._running():
            self._cancelling = True
            if self.card is not None:
                self._answer("the pending tool", False)
            self.worker.request_stop()
        for n in wf["nodes"]:
            if n["status"] in ("draft", "ready", "waiting", "awaiting_approval", "paused", "blocked") or (n["status"] == "running" and not self._running()):
                O.transition(wf, n["id"], "cancelled", "you cancelled the workflow")
        wf["paused"] = False
        wf["state"] = O.workflow_state(wf)
        O.log(self.session, "workflow.cancelled")
        self._save()
        self.render_all()

    # ----- voice -----
    def refresh_voice(self) -> None:
        """Pick up voice input set up (or removed) in Settings → Voice, without a restart."""
        from ..voice_setup import make_voice_input

        if self.voice is not None and self.voice.isRunning():
            return
        self.voice = make_voice_input(self.core.paths()["data"])
        if self.voice is not None:
            self.voice.transcription_done.connect(self._heard)
            self.voice.audio_level_signal.connect(self._mic_level)
            self.voice.status_signal.connect(self._voice_status)
            self.voice.finished.connect(self._voice_finished)
        self.talk_btn.setEnabled(self.voice is not None)
        self.talk_btn.setToolTip("Talk (Ctrl+Shift+Space). Speech is transcribed on this computer." if self.voice else "Voice input is not set up: Settings → Voice → Set up voice input. You can type meanwhile.")
        self.voice_info.setText(self._voice_text())

    def _voice_text(self) -> str:
        from ..voice_setup import voice_input_text

        parts = [voice_input_text(self.voice)]
        parts.append(self.tts.describe())
        return " · ".join(parts)

    def voice_options(self) -> None:
        silence, ok = QInputDialog.getDouble(self, "Voice options", "Seconds of quiet that end your turn:", float(self.settings.get("orbit_silence")), 0.6, 4.0, 1)
        if not ok:
            return
        sens, ok = QInputDialog.getDouble(self, "Voice options", "Sensitivity (0 needs loud speech, 1 picks up quiet speech):", float(self.settings.get("orbit_sensitivity")), 0.0, 1.0, 2)
        if not ok:
            return
        self.settings.set("orbit_silence", float(silence))
        self.settings.set("orbit_sensitivity", float(sens))
        self.turns.silence, self.turns.sensitivity = float(silence), float(sens)
        QMessageBox.information(self, "About ORBIT's voice", "\n\n".join(LIMITS))

    def _continuous_toggled(self, on: bool) -> None:
        self.continuous = on
        self.settings.set("orbit_continuous", on)

    def _talk_toggled(self, on: bool) -> None:
        if on:
            self.listen()
        elif self.listening:
            self._stop_listening()

    def listen(self) -> None:
        """Open the microphone (only on your action, or after a reply in continuous mode)."""
        if self.voice is None:
            self.talk_btn.setChecked(False)
            return
        self.stop_speaking()
        if self.voice.isRunning():
            return
        if self.voice.start_recording():
            self.listening = True
            self.turns.reset(time.monotonic())
            self.talk_btn.blockSignals(True)
            self.talk_btn.setChecked(True)
            self.talk_btn.blockSignals(False)
            self.talk_btn.setText("Listening… (press to send)")
            self.set_state("LISTENING")
        else:
            self.talk_btn.setChecked(False)

    def _stop_listening(self) -> None:
        self.listening = False
        if self.voice is not None:
            self.voice.stop_recording()
        self.talk_btn.blockSignals(True)
        self.talk_btn.setChecked(False)
        self.talk_btn.blockSignals(False)
        self.talk_btn.setText("Talk")
        self.level.setValue(0)
        if self.state == "LISTENING":
            self.set_state("THINKING")

    def _mic_level(self, level: float) -> None:
        self.level.setValue(int(level * 100))
        self.stage.set_level(level)
        if not self.listening or not self.continuous:
            return
        ev = self.turns.feed(level, time.monotonic())
        if ev == "end":
            self._stop_listening()
        elif ev == "idle":
            self._stop_listening()
            self.set_state("IDLE")
            self._line("ORBIT", "Stopped listening after a long silence. Press Talk to continue.", T.TEXT_FAINT)
            self._flush()

    def _voice_status(self, s: str) -> None:
        s = (s or "").strip()
        if s.startswith(("MICROPHONE ERROR", "SPEECH MODEL ERROR", "STT ERROR")):
            self.listening = False
            self._line("ORBIT", s.capitalize(), T.ERR)
            self._flush()
            self.set_state("ERROR")
        elif s.startswith("RECORDING TOO SHORT"):
            self.set_state("IDLE")
            if self.continuous:
                QTimer.singleShot(200, self.listen)

    def _voice_finished(self) -> None:
        if self.listening:  # stopped on its own (error)
            self._stop_listening()

    def _heard(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            self.set_state("IDLE")
            if self.continuous:
                QTimer.singleShot(200, self.listen)
            return
        self.say(text)
        if self.state not in ("THINKING", "PLANNING") and self.continuous:  # a local edit: listen again
            QTimer.singleShot(400, self.listen)

    def _play_level(self, level: float) -> None:
        # called from the playback thread; Qt widgets are updated on the next frame by the avatar itself
        try:
            (self.stage.avatar or self.stage.glyph).set_audio_level(level)
        except RuntimeError:
            pass

    def speak(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            if self.state in ("THINKING", "PLANNING"):
                self.set_state("IDLE")
            return
        if self.tts.enabled and self.tts.speak(text):
            self._speech_mine = True  # SPEAKING is shown when audio really starts (_speech_state)
            self._speech_watch.start()
        else:
            if self.state in ("THINKING", "PLANNING", "SPEAKING"):
                self.set_state("IDLE")
            if self.continuous and self.voice is not None and self._spoke_back_ok():
                QTimer.singleShot(400, self.listen)

    def _spoke_back_ok(self) -> bool:
        return not self._running() and self.card is None

    def _watch_speech(self) -> None:
        if self.tts.is_busy:
            return
        self._speech_watch.stop()
        if not self._speech_mine:
            return  # stopped or failed: _speech_error / stop_speaking already decided what happens next
        self._speech_mine = False
        if self.state == "SPEAKING":
            self.set_state("IDLE")
        if self.continuous and self.voice is not None and self._spoke_back_ok() and self._was_conversing():
            self.listen()

    def _was_conversing(self) -> bool:
        return getattr(self, "_conversing", True)

    def _speech_state(self, playing: bool) -> None:
        """The sun speaks only while audio really plays."""
        if not self._speech_mine:
            return
        if playing:
            if self.state not in ("RUNNING", "WARNING"):
                self.set_state("SPEAKING")
        elif self.state == "SPEAKING":
            self.set_state("IDLE")

    def _speech_error(self, msg: str) -> None:
        if not self._speech_mine:
            return
        self._speech_mine = False
        self._line("ORBIT", f"Not spoken: {msg}", T.WARN)
        self._flush()
        self._speech_watch.stop()
        if self.state == "SPEAKING":
            self.set_state("IDLE")
        # continuous conversation goes on without speech: listen again as if the reply had been spoken
        if self.continuous and self.voice is not None and self._spoke_back_ok() and self._was_conversing():
            QTimer.singleShot(400, self.listen)

    def stop_speaking(self) -> None:
        if self._speech_mine or self.tts.is_busy:
            self.tts.stop()
        self._speech_mine = False
        self._speech_watch.stop()
        if self.state == "SPEAKING":
            self.set_state("IDLE")

    def end_conversation(self) -> None:
        self._conversing = False
        self.stop_speaking()
        if self.listening:
            self._stop_listening()
        if self.worker_busy() and self.worker_kind == "talk":
            self.worker.request_stop()
        self.set_state("IDLE")
        self._line("ORBIT", "Conversation ended. The plan and any workflow are unchanged. Press Talk or type to continue.", T.TEXT_FAINT)
        self._flush()
        self._save()
        QTimer.singleShot(1500, lambda: setattr(self, "_conversing", True))

    def talk_shortcut(self) -> None:
        """Ctrl+Shift+Space: start talking, or send what you said."""
        if self.listening:
            self._stop_listening()
        else:
            self.listen()

    def _space(self) -> None:
        """Space on the canvas: stop Prometheus speaking, otherwise start or finish talking."""
        if self.tts.is_busy:
            self.stop_speaking()
        else:
            self.talk_shortcut()

    def _escape(self) -> None:
        if self.tts.is_busy:
            self.stop_speaking()
        elif self.listening:
            self._stop_listening()
            self.set_state("IDLE")
        elif self.immersive:
            self.set_immersive(False)

    # ----- page -----
    def refresh(self) -> None:
        if not self.core.router.configured and not self.worker_busy():
            self.set_state("OFFLINE")
        elif self.state == "OFFLINE":
            self.set_state("IDLE")
        self._fill_sessions()

    def shutdown(self) -> None:
        if self.worker_busy():
            if self.worker_kind != "talk":
                self._node_event(self.worker_kind, "Prometheus was closing; the step was stopped")
            self.worker.request_stop()
            self.worker.wait(3000)
        if self.voice is not None:
            self.voice.stop_recording()
            self.voice.wait(1500)
        self._save()
