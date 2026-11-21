"""Feedback the person can't miss: toasts for action results, and the activity centre.

* `notify(widget, text, tone, detail)` from any page: a toast appears at the bottom right of the window
  (icon + words, never colour alone), is announced to assistive technology through the window's
  accessible description, and is kept in the activity centre. "Acknowledged" toasts (tone "info") are
  for work that continues in the background; "ok" means it is actually done.
* The activity centre (the bell) is a drawer listing this session's notifications and the latest real
  events from the audit log, each with a way back to where it came from.
"""

from __future__ import annotations

import time
from typing import Callable, List, Optional

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, QTimer
from PyQt6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget

from . import icons
from . import theme as T

TONE_ICON = {"ok": "check", "warn": "alert", "err": "alert", "info": "bolt", "accent": "sun"}
TONE_WORD = {"ok": "Done", "warn": "Attention", "err": "Problem", "info": "Working", "accent": "Prometheus"}


def notify(widget: QWidget, text: str, tone: str = "ok", detail: str = "") -> None:
    """Show a toast in the widget's main window (no-op outside one)."""
    win = widget.window() if widget is not None else None
    fn = getattr(win, "notify", None)
    if callable(fn):
        fn(text, tone, detail)


class Toast(QFrame):
    def __init__(self, parent: QWidget, text: str, tone: str, detail: str = "", reduced_motion: bool = False):
        super().__init__(parent)
        self.setObjectName("toast")
        c = T.TONES.get(tone, T.TEXT_SECONDARY)
        self.setStyleSheet(f"QFrame#toast {{ background: {T.SURFACE_RAISED}; border: 1px solid {T.BORDER_STRONG}; border-left: 3px solid {c}; border-radius: 10px; }}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 10, 14, 10)
        lay.setSpacing(10)
        ic = QLabel()
        ic.setPixmap(icons.pixmap(TONE_ICON.get(tone, "bell"), c, 18))
        lay.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        head = QLabel(f"<b>{TONE_WORD.get(tone, '')}</b> · {_esc(text)}")
        head.setWordWrap(True)
        head.setMaximumWidth(360)
        col.addWidget(head)
        if detail:
            d = QLabel(_esc(detail))
            d.setWordWrap(True)
            d.setMaximumWidth(360)
            d.setStyleSheet(f"color: {T.TEXT_SECONDARY}; font-size: 9pt;")
            col.addWidget(d)
        lay.addLayout(col)
        self.setAccessibleName(f"{TONE_WORD.get(tone, '')}: {text}")
        self.adjustSize()
        self._fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._fx)
        self._fx.setOpacity(1.0)
        self._reduced = reduced_motion
        QTimer.singleShot(4200 if tone in ("ok", "info") else 7000, self.dismiss)

    def mousePressEvent(self, e) -> None:
        self.dismiss()

    def dismiss(self) -> None:
        if self._reduced:
            self.deleteLater()
            return
        a = QPropertyAnimation(self._fx, b"opacity", self)
        a.setDuration(220)
        a.setStartValue(1.0)
        a.setEndValue(0.0)
        a.setEasingCurve(QEasingCurve.Type.OutCubic)
        a.finished.connect(self.deleteLater)
        a.start()


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class ToastHost:
    """Stacks toasts at the bottom right of a window."""

    def __init__(self, window: QWidget, reduced: Callable[[], bool]):
        self.window, self.reduced = window, reduced
        self.toasts: List[Toast] = []

    def show(self, text: str, tone: str, detail: str = "") -> None:
        t = Toast(self.window, text, tone, detail, self.reduced())
        t.destroyed.connect(lambda *_: self._forget(t))
        self.toasts.append(t)
        del self.toasts[:-4]
        t.show()
        t.raise_()
        self.place()

    def _forget(self, t) -> None:
        if t in self.toasts:
            self.toasts.remove(t)
        self.place()

    def place(self) -> None:
        try:
            y = self.window.height() - 40
        except RuntimeError:                      # the window is already gone (application shutting down)
            return
        for t in reversed(self.toasts):
            try:
                t.adjustSize()
                y -= t.height() + 8
                t.move(self.window.width() - t.width() - 22, y)
            except RuntimeError:
                pass


class ActivityDrawer(QFrame):
    """The bell: this session's notifications, then the latest real audit events."""

    def __init__(self, parent: QWidget, open_source: Callable[[str], None]):
        super().__init__(parent)
        self.setObjectName("drawer")
        self.setStyleSheet(f"QFrame#drawer {{ background: {T.SURFACE}; border-left: 1px solid {T.BORDER_STRONG}; }}")
        self.open_source = open_source
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 14, 14)
        head = QHBoxLayout()
        t = QLabel("Activity")
        t.setObjectName("h2")
        head.addWidget(t, 1)
        close = QPushButton("Close")
        close.setObjectName("ghost")
        close.clicked.connect(self.hide)
        head.addWidget(close)
        lay.addLayout(head)
        sub = QLabel("What happened in this session, and the latest actions from the audit log. Select one to go to it.")
        sub.setObjectName("faint")
        sub.setWordWrap(True)
        lay.addWidget(sub)
        self.list = QListWidget()
        self.list.setObjectName("plain")
        self.list.setIconSize(QSize(16, 16))
        self.list.setWordWrap(True)
        self.list.setAccessibleName("Activity")
        self.list.itemActivated.connect(self._open)
        self.list.itemClicked.connect(self._open)
        lay.addWidget(self.list, 1)
        self.clear_btn = QPushButton("Clear session notifications")
        self.clear_btn.setObjectName("ghost")
        lay.addWidget(self.clear_btn)
        self.hide()

    def fill(self, notes: list, audit: list) -> None:
        self.list.clear()

        def section(name: str) -> None:
            it = QListWidgetItem(name.upper())
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            f = it.font()
            f.setBold(True)
            f.setPointSizeF(8)
            it.setFont(f)
            it.setForeground(__import__("PyQt6.QtGui", fromlist=["QColor"]).QColor(T.TEXT_FAINT))
            self.list.addItem(it)

        section("This session")
        if not notes:
            it = QListWidgetItem("Nothing yet. Reminders, results and problems appear here.")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(it)
        for n in notes[:40]:
            c = T.TONES.get(n["tone"], T.TEXT_SECONDARY)
            it = QListWidgetItem(icons.icon(TONE_ICON.get(n["tone"], "bell"), c), f"{n['time']}  {TONE_WORD.get(n['tone'], '')}: {n['title']}" + (f"\n{n['body']}" if n.get("body") else ""))
            it.setData(Qt.ItemDataRole.UserRole, n.get("source", ""))
            self.list.addItem(it)
        section("Recent actions (audit log)")
        for e in audit[:40]:
            outcome = str(e.get("outcome", ""))
            tone = "ok" if outcome == "success" else "warn" if outcome in ("refused", "declined", "denied", "cancelled") else "err" if "error" in outcome else "info"
            it = QListWidgetItem(icons.icon(TONE_ICON[tone], T.TONES[tone]), f"{str(e.get('ts', ''))[11:16]}  {e.get('tool', '')} — {outcome}")
            it.setData(Qt.ItemDataRole.UserRole, "Trust & safety")
            self.list.addItem(it)

    def _open(self, item) -> None:
        src = item.data(Qt.ItemDataRole.UserRole)
        if src:
            self.hide()
            self.open_source(src)


def stamp() -> str:
    return time.strftime("%H:%M")
