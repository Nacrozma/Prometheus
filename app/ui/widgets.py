"""Small shared pieces: page header, cards, a background runner that keeps the window responsive."""

from __future__ import annotations

import traceback
from typing import Any, Callable, Optional

from PyQt6.QtCore import QObject, QRunnable, Qt, QThreadPool, pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget


def display_path(path: str) -> str:
    """A path as people read it: the home folder shown as ~ (the full path stays selectable elsewhere)."""
    import os

    home = os.path.expanduser("~")
    p = str(path or "")
    return "~" + p[len(home):] if home and home != "/" and (p == home or p.startswith(home + os.sep)) else p


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
    """A surface with an optional title row. `interactive=True` lights its border on hover."""

    def __init__(self, title: str = "", parent: Optional[QWidget] = None, interactive: bool = False, icon_name: str = ""):
        super().__init__(parent)
        self.setObjectName("cardInteractive" if interactive else "card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(18, 16, 18, 16)
        self.body.setSpacing(10)
        self.title_row = QHBoxLayout()
        self.title_row.setSpacing(8)
        if title:
            if icon_name:
                from . import icons, theme as T

                ic = QLabel()
                ic.setPixmap(icons.pixmap(icon_name, T.ACCENT, 16))
                self.title_row.addWidget(ic)
            t = label(title, "h2")
            self.title_row.addWidget(t, 1)
            self.body.addLayout(self.title_row)


def pill(text: str, tone: str = "neutral") -> QLabel:
    """A small status label. Tones: ok, warn, err, info, accent, neutral."""
    from . import theme as T

    lab = label(text, "pill", wrap=False)
    lab.setStyleSheet(T.pill_style(tone))
    lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lab.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
    return lab


def divider() -> QFrame:
    f = QFrame()
    f.setObjectName("divider")
    return f


def stat_tile(value: str, caption: str, tone: str = "") -> QFrame:
    """A number with a caption, for summaries."""
    from . import theme as T

    card = Card()
    card.body.setSpacing(2)
    v = label(value, "stat", wrap=False)
    if tone:
        v.setStyleSheet(f"color: {T.TONES.get(tone, T.TEXT)};")
    card.body.addWidget(v)
    card.body.addWidget(label(caption, "faint"))
    card.value_label = v  # type: ignore[attr-defined]
    return card


class EmptyState(QWidget):
    """What to show when there is nothing yet: an icon, a sentence and an optional action."""

    def __init__(self, icon_name: str, title: str, body: str = "", action_text: str = "", on_action: Optional[Callable[[], None]] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        from PyQt6.QtWidgets import QPushButton

        from . import icons, theme as T

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 28, 24, 28)
        lay.setSpacing(6)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic = QLabel()
        ic.setPixmap(icons.pixmap(icon_name, T.BRONZE, 28))
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(ic)
        t = label(title, "h2")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(t)
        if body:
            b = label(body, "sub")
            b.setAlignment(Qt.AlignmentFlag.AlignCenter)
            b.setMaximumWidth(460)
            lay.addWidget(b, 0, Qt.AlignmentFlag.AlignCenter)
        if action_text and on_action:
            btn = QPushButton(action_text)
            btn.clicked.connect(on_action)
            lay.addWidget(btn, 0, Qt.AlignmentFlag.AlignCenter)


def icon_button(icon_name: str, tip: str, on_click: Optional[Callable[[], None]] = None, color: str = "") -> "QToolButton":
    from PyQt6.QtWidgets import QToolButton

    from . import icons, theme as T

    b = QToolButton()
    b.setIcon(icons.icon(icon_name, color or T.TEXT_SECONDARY, active=T.ACCENT, disabled=T.TEXT_FAINT))
    b.setIconSize(icons.ICON_SIZE)
    b.setToolTip(tip)
    b.setAccessibleName(tip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if on_click:
        b.clicked.connect(lambda _=False: on_click())
    return b


class Page(QWidget):
    """A navigable section: eyebrow (its group), title, subtitle, actions, then content.
    `refresh()` reloads its data. Set `scroll = True` for pages taller than the window."""

    title = ""
    subtitle = ""
    eyebrow = ""
    scroll = False
    #: "full" (eyebrow, title, subtitle), "compact" (one quiet line: title and actions) or "none" (the
    #: page composes its own top area). Screens differ on purpose; see RENAISSANCE_UX_SPECIFICATIONS.md.
    header = "full"
    margins = (32, 24, 32, 20)

    def __init__(self, core, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.core = core
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(*self.margins)
        lay.setSpacing(14)
        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(3)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        if self.header == "full":
            if self.eyebrow:
                col.addWidget(label(self.eyebrow.upper(), "eyebrow"))
            col.addWidget(label(self.title, "h1"))
            if self.subtitle:
                col.addWidget(label(self.subtitle, "sub"))
        elif self.header == "compact":
            t = label(self.title, "h2", wrap=False)
            t.setStyleSheet("font-size: 13pt;")
            col.addWidget(t)
        head.addLayout(col, 1)
        head.addLayout(self.actions)
        if self.header != "none":
            lay.addLayout(head)
        else:
            self._head = head  # pages that compose their own top area may add it where they like
        self.content = QVBoxLayout()
        self.content.setSpacing(14)
        lay.addLayout(self.content, 1)
        if self.scroll:
            from PyQt6.QtWidgets import QScrollArea

            sa = QScrollArea()
            sa.setWidgetResizable(True)
            sa.setFrameShape(QFrame.Shape.NoFrame)
            sa.setWidget(inner)
            outer.addWidget(sa)
        else:
            outer.addWidget(inner)

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
