"""Small shared pieces: page header, cards, a background runner that keeps the window responsive."""

from __future__ import annotations

import traceback
from typing import Any, Callable, Optional

from PyQt6.QtCore import QObject, QRunnable, Qt, QThreadPool, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


def label(text: str = "", name: str = "", wrap: bool = True, selectable: bool = False) -> QLabel:
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    # Model- and file-derived text is shown as plain text, never as HTML.
    lab.setTextFormat(Qt.TextFormat.PlainText)
    if selectable:
        lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lab


class Card(QFrame):
    def __init__(self, title: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(16, 14, 16, 14)
        self.body.setSpacing(8)
        if title:
            t = label(title)
            t.setStyleSheet("font-weight: 600; font-size: 11pt;")
            self.body.addWidget(t)


class Page(QWidget):
    """A navigable section: title, subtitle, then content. `refresh()` reloads its data."""

    title = ""
    subtitle = ""

    def __init__(self, core, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.core = core
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 18)
        outer.setSpacing(12)
        head = QHBoxLayout()
        col = QVBoxLayout()
        col.addWidget(label(self.title, "h1"))
        if self.subtitle:
            col.addWidget(label(self.subtitle, "sub"))
        head.addLayout(col, 1)
        self.actions = QHBoxLayout()
        head.addLayout(self.actions)
        outer.addLayout(head)
        self.content = QVBoxLayout()
        self.content.setSpacing(12)
        outer.addLayout(self.content, 1)

    def refresh(self) -> None:  # pages override
        pass


class _Signals(QObject):
    done = pyqtSignal(object)
    failed = pyqtSignal(str)


class _Job(QRunnable):
    def __init__(self, fn: Callable[[], Any]):
        super().__init__()
        self.fn = fn
        self.signals = _Signals()

    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as e:  # reported to the page, never swallowed
            self.signals.failed.emit(f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}")
            return
        self.signals.done.emit(result)


_alive = []  # keep job objects alive until they report back


def run_bg(fn: Callable[[], Any], on_done: Callable[[Any], None], on_error: Optional[Callable[[str], None]] = None, owner: Optional[QObject] = None) -> None:
    """Run `fn` on the thread pool; call back on the GUI thread. Callbacks are dropped if `owner` is gone."""
    job = _Job(fn)
    _alive.append(job)

    def finish(cb, value):
        if job in _alive:
            _alive.remove(job)
        if owner is not None:
            try:
                owner.objectName()  # raises if the C++ object was destroyed
            except RuntimeError:
                return
        if cb:
            cb(value)

    job.signals.done.connect(lambda v: finish(on_done, v))
    job.signals.failed.connect(lambda m: finish(on_error, m))
    QThreadPool.globalInstance().start(job)


def tidy_table(table, stretch_col: int = -1) -> None:
    """Common table look: no row numbers, columns sized to their contents, one column stretching."""
    from PyQt6.QtWidgets import QAbstractItemView, QHeaderView

    table.verticalHeader().setVisible(False)
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    h = table.horizontalHeader()
    h.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    col = stretch_col if stretch_col >= 0 else table.columnCount() - 1
    h.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
