"""The main window: grouped navigation (collapsible), a top bar with universal search and
notifications, the pages, a status bar, the command palette and the tray."""

from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional, Tuple

from PyQt6.QtCore import QEvent, QSize, Qt, QTimer
from PyQt6.QtGui import QAction, QCloseEvent, QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QSystemTrayIcon,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME
from ..services.conversations import ConversationStore
from . import icons
from . import theme as T
from .pages.arm import ArmPage
from .pages.companion import CompanionPage
from .pages.engineering import EngineeringPage
from .pages.forge import ForgePage
from .pages.home import HomePage
from .pages.memory import MemoryPage
from .pages.obsidian import ObsidianPage
from .pages.orbit import OrbitPage
from .pages.reflection import ReflectionPage
from .pages.settings import SettingsPage
from .pages.tasks import TasksPage
from .pages.trust import TrustPage
from .pages.workspace import WorkspacePage
from .widgets import label, run_bg

#: How often due reminders are checked (the core's scheduler marks them due; we deliver them).
REMINDER_POLL_MS = 15_000

#: The sections, in groups. Names are stable identifiers (settings, tests and the palette use them).
NAV: List[Tuple[str, List[Tuple[str, str]]]] = [
    ("Overview", [("Home", "home")]),
    ("Conversation", [("Companion", "chat"), ("ORBIT", "orbit")]),
    ("Knowledge", [("Memory", "memory"), ("Obsidian", "obsidian")]),
    ("Creation", [("Engineering", "engineering"), ("Forge", "forge"), ("Workspace", "workspace")]),
    ("Organisation", [("Reminders & tasks", "tasks")]),
    ("Laboratory", [("Robot arm (simulation)", "robot"), ("Reflection", "reflection")]),
    ("System", [("Trust & safety", "shield"), ("Settings", "settings")]),
]
SECTION_ICON = {name: ic for _, items in NAV for name, ic in items}
SECTION_GROUP = {name: g for g, items in NAV for name, _ in items}
KIND_ICON = {"section": "chevron-right", "command": "bolt", "conversation": "chat", "memory": "memory", "reminder": "clock", "file": "file", "activity": "shield"}
KIND_LABEL = {"section": "Go to", "command": "Command", "conversation": "Conversation", "memory": "Memory", "reminder": "Reminder", "file": "File", "activity": "Activity"}


class Notifications:
    """What happened while you were elsewhere: reminders, failures, results. Kept for this session."""

    def __init__(self):
        self.items: List[Dict[str, str]] = []
        self.unread = 0
        self.listeners: List[Callable[[], None]] = []

    def add(self, title: str, body: str = "", tone: str = "info", source: str = "") -> None:
        self.items.insert(0, {"title": title, "body": body, "tone": tone, "time": time.strftime("%H:%M"), "source": source})
        del self.items[100:]
        self.unread += 1
        for fn in self.listeners:
            fn()

    def read_all(self) -> None:
        self.unread = 0
        for fn in self.listeners:
            fn()


class CommandPalette(QDialog):
    """Ctrl+K: go to a section, run a command, or search conversations, memory, reminders, files and
    activity. Every entry runs real application code."""

    def __init__(self, entries: List[tuple], search_fn: Optional[Callable[[str], list]] = None, open_result: Optional[Callable[[dict], None]] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Search and commands")
        self.setModal(True)
        self.resize(680, 520)
        self.entries = entries  # (label, callable, kind)
        self.search_fn, self.open_result = search_fn, open_result
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search conversations, memory, files, reminders… or type a command")
        self.search.setAccessibleName("Command search")
        self.list = QListWidget()
        self.list.setObjectName("plain")
        self.list.setIconSize(QSize(16, 16))
        self.hint = label("Enter to open · Esc to close", "faint")
        lay.addWidget(self.search)
        lay.addWidget(self.list, 1)
        lay.addWidget(self.hint)
        self._found: list = []
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(180)
        self._debounce.timeout.connect(self._run_search)
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._run_current)
        self.list.itemActivated.connect(lambda _: self._run_current())
        self._filter("")

    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up) and self.search.hasFocus():
            step = 1 if e.key() == Qt.Key.Key_Down else -1
            row = self.list.currentRow() + step
            while 0 <= row < self.list.count() and not (self.list.item(row).flags() & Qt.ItemFlag.ItemIsEnabled):
                row += step
            if 0 <= row < self.list.count():
                self.list.setCurrentRow(row)
            return
        super().keyPressEvent(e)

    def _add(self, kind: str, title: str, detail: str, data, q: str = "") -> None:
        import html as _h

        def mark(text: str) -> str:
            t = _h.escape(text)
            if q and len(q) >= 2:
                i = text.lower().find(q.lower())
                if i >= 0:
                    t = _h.escape(text[:i]) + f'<b style="color:{T.HIGHLIGHT};">' + _h.escape(text[i:i + len(q)]) + "</b>" + _h.escape(text[i + len(q):])
            return t

        item = QListWidgetItem(icons.icon(KIND_ICON.get(kind, "bolt"), T.TEXT_SECONDARY), "")
        item.setData(Qt.ItemDataRole.UserRole, data)
        item.setToolTip(f"{title} — {detail}" if detail else title)
        item.setSizeHint(QSize(0, 50 if detail else 32))
        self.list.addItem(item)
        lab = QLabel(f'<span style="color:{T.TEXT};">{mark(title)}</span>' + (f'<br/><span style="color:{T.TEXT_FAINT}; font-size:8pt;">{mark(detail)}</span>' if detail else ""))
        lab.setTextFormat(Qt.TextFormat.RichText)
        lab.setContentsMargins(26, 2, 6, 2)
        lab.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.list.setItemWidget(item, lab)

    def _header(self, text: str) -> None:
        h = QListWidgetItem(text.upper())
        h.setFlags(Qt.ItemFlag.NoItemFlags)
        f = h.font()
        f.setPointSizeF(8)
        f.setBold(True)
        h.setFont(f)
        h.setForeground(__import__("PyQt6.QtGui", fromlist=["QColor"]).QColor(T.ACCENT))
        self.list.addItem(h)

    def _render(self, q: str) -> None:
        row = self.list.currentRow()
        self.list.clear()
        t = q.lower().strip()
        sections = [e for e in self.entries if e[2] == "section" and (not t or t in e[0].lower())]
        commands = [e for e in self.entries if e[2] == "command" and (not t or t in e[0].lower())]
        if sections:
            self._header("Go to")
            for name, fn, kind in sections:
                self._add(kind, name, "", ("run", fn), t)
        if commands:
            self._header("Commands")
            for name, fn, kind in commands:
                self._add(kind, name, "", ("run", fn), t)
        if t:
            for kind in ("conversation", "memory", "reminder", "file", "activity"):
                found = [r for r in self._found if r["kind"] == kind]
                if found:
                    self._header({"conversation": "Conversations", "memory": "Memory", "reminder": "Reminders", "file": "Workspace files", "activity": "Activity"}[kind])
                    for r in found:
                        self._add(r["kind"], r["title"], r.get("detail", ""), ("open", r), t)
        selectable = [i for i in range(self.list.count()) if self.list.item(i).flags() & Qt.ItemFlag.ItemIsEnabled]
        if selectable:
            self.list.setCurrentRow(row if row in selectable else selectable[0])

    def _filter(self, text: str) -> None:
        if not text.strip():
            self._found = []
        self._render(text)
        if self.search_fn and len(text.strip()) >= 2:
            self._debounce.start()
        else:
            self.hint.setText("Type to search conversations, memory, reminders, workspace files and activity · Enter opens · Esc closes")

    def _run_search(self) -> None:
        q = self.search.text()
        self.hint.setText("Searching your data…")

        def done(results):
            if self.search.text() != q:
                return
            self._found = results or []
            n = len(self._found)
            self.hint.setText(f"{n} result{'s' if n != 1 else ''} in your data · Enter opens · Esc closes" if n else "Nothing in conversations, memory, reminders, workspace files or activity matches. Try fewer or different words.")
            self._render(q)

        run_bg(lambda: self.search_fn(q), done, lambda m: self.hint.setText(f"Search failed: {m.splitlines()[0]}"), owner=self)

    def _run_current(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        payload = item.data(Qt.ItemDataRole.UserRole)
        if not payload:
            return
        how, data = payload
        self.accept()
        if how == "run":
            data()
        elif self.open_result:
            self.open_result(data)


class NavBar(QWidget):
    """Grouped, collapsible navigation. Each section is a checkable button with an icon and a tooltip."""

    def __init__(self, names: List[str], on_select: Callable[[str], None], collapsed: bool, on_collapse: Callable[[bool], None]):
        super().__init__()
        self.setObjectName("sidebar")
        self.on_select, self.on_collapse = on_select, on_collapse
        self.buttons: Dict[str, QToolButton] = {}
        self.group_labels: List[QLabel] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 16, 10, 10)
        lay.setSpacing(2)
        top = QHBoxLayout()
        self.mark = QLabel()
        self.mark.setPixmap(icons.pixmap("sun", T.ACCENT, 22))
        self.brand = QLabel(APP_NAME.upper())
        self.brand.setObjectName("brand")
        top.addWidget(self.mark)
        top.addWidget(self.brand, 1)
        lay.addLayout(top)
        lay.addSpacing(10)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        for gname, items in NAV:
            gl = label(gname.upper(), "navGroup", wrap=False)
            self.group_labels.append(gl)
            lay.addWidget(gl)
            for name, ic in items:
                if name not in names:
                    continue
                b = QToolButton()
                b.setObjectName("navItem")
                b.setText(name.replace("&", "&&"))  # '&' would otherwise become a keyboard mnemonic
                b.setIcon(icons.icon(ic, T.TEXT_SECONDARY, active=T.ACCENT))
                b.setIconSize(QSize(18, 18))
                b.setCheckable(True)
                b.setToolTip(name)
                b.setAccessibleName(name)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.setSizePolicy(b.sizePolicy().horizontalPolicy().Expanding, b.sizePolicy().verticalPolicy())
                b.clicked.connect(lambda _=False, n=name: self.on_select(n))
                self.group.addButton(b)
                self.buttons[name] = b
                lay.addWidget(b)
        lay.addStretch(1)
        self.hint = label("Ctrl+K search · Esc stop", "faint", wrap=False)
        lay.addWidget(self.hint)
        self.toggle = QToolButton()
        self.toggle.setObjectName("collapse")
        self.toggle.setAccessibleName("Collapse navigation")
        self.toggle.clicked.connect(lambda: self.set_collapsed(not self.collapsed, notify=True))
        lay.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.collapsed = False
        self.set_collapsed(collapsed)

    def set_collapsed(self, collapsed: bool, notify: bool = False) -> None:
        self.collapsed = collapsed
        style = Qt.ToolButtonStyle.ToolButtonIconOnly if collapsed else Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        for b in self.buttons.values():
            b.setToolButtonStyle(style)
        for w in (self.brand, self.hint, *self.group_labels):
            w.setVisible(not collapsed)
        self.setFixedWidth(64 if collapsed else 232)
        self.toggle.setIcon(icons.icon("chevron-right" if collapsed else "chevron-left", T.TEXT_FAINT))
        self.toggle.setToolTip("Expand navigation" if collapsed else "Collapse navigation")
        self.toggle.setAccessibleName(self.toggle.toolTip())
        if notify:
            self.on_collapse(collapsed)

    def select(self, name: str) -> None:
        b = self.buttons.get(name)
        if b is not None and not b.isChecked():
            b.setChecked(True)


class MainWindow(QMainWindow):
    def __init__(self, core, settings, creds, platform, paths, frozen: bool, icon: QIcon):
        super().__init__()
        self.core, self.settings, self.creds, self.platform, self.paths = core, settings, creds, platform, paths
        self._quitting = False
        self.after_launch: list = []
        self.launch = None
        self.notifications = Notifications()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(icon)
        self.setMinimumSize(QSize(1040, 680))
        self.resize(1360, 860)

        self.conversations = ConversationStore(paths.data_dir)
        # each page shows its navigation group as an eyebrow above the title
        for name, cls in (("Home", HomePage), ("Companion", CompanionPage), ("ORBIT", OrbitPage), ("Memory", MemoryPage), ("Engineering", EngineeringPage), ("Forge", ForgePage), ("Workspace", WorkspacePage), ("Reminders & tasks", TasksPage), ("Obsidian", ObsidianPage), ("Robot arm (simulation)", ArmPage), ("Reflection", ReflectionPage), ("Trust & safety", TrustPage), ("Settings", SettingsPage)):
            cls.eyebrow = SECTION_GROUP[name]
        self.companion = CompanionPage(core, settings, self.conversations)
        self.orbit = OrbitPage(core, settings, self.conversations, notify=lambda text, detail="", tone="ok": self.notify(text, tone, detail, "ORBIT"))
        self.pages: Dict[str, QWidget] = {
            "Home": HomePage(core, settings, self.conversations, self),
            "Companion": self.companion,
            "ORBIT": self.orbit,
            "Memory": MemoryPage(core),
            "Obsidian": ObsidianPage(core, self.companion),
            "Engineering": EngineeringPage(core),
            "Forge": ForgePage(core, frozen),
            "Workspace": WorkspacePage(core),
            "Reminders & tasks": TasksPage(core),
            "Robot arm (simulation)": ArmPage(core),
            "Reflection": ReflectionPage(core),
            "Trust & safety": TrustPage(core, settings),
            "Settings": SettingsPage(core, settings, creds, platform, paths),
        }
        self.settings_page: SettingsPage = self.pages["Settings"]  # type: ignore[assignment]

        central = QWidget()
        central.setObjectName("root")
        row = QHBoxLayout(central)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.nav = NavBar(list(self.pages), self.go, bool(settings.get("nav_collapsed")), lambda c: settings.set("nav_collapsed", c))
        row.addWidget(self.nav)

        main = QWidget()
        main.setObjectName("workspace")
        mv = QVBoxLayout(main)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.setSpacing(0)
        self.topbar = self._topbar()
        mv.addWidget(self.topbar)
        self.stack = QStackedWidget()
        for page in self.pages.values():
            self.stack.addWidget(page)
        mv.addWidget(self.stack, 1)
        row.addWidget(main, 1)
        self.setCentralWidget(central)
        from .feedback import ActivityDrawer, ToastHost

        self.toasts = ToastHost(self, lambda: bool(self.settings.get("reduced_motion")))
        self.activity = ActivityDrawer(self, self.go)
        self.activity.clear_btn.clicked.connect(lambda: (self.notifications.items.clear(), self.notifications.read_all(), self.activity.hide()))

        # status bar: provider, background activity, orb state
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.sb_provider = QLabel()
        self.sb_state = QLabel()
        self.sb_busy = QLabel()
        sb.addWidget(self.sb_provider, 1)
        sb.addPermanentWidget(self.sb_busy)
        sb.addPermanentWidget(self.sb_state)
        self.companion.state_changed.connect(self._state)
        self.companion.busy_changed.connect(lambda b: self.sb_busy.setText("Working…" if b else ""))
        self._state("IDLE")
        self._update_provider()

        # settings → behaviour
        self.settings_page.behaviour_changed.connect(self._apply_behaviour)
        self.settings_page.restart_requested.connect(self._restart_needed)

        # shortcuts
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self.open_palette)
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self._new_conversation)
        QShortcut(QKeySequence("Ctrl+,"), self, activated=lambda: self.go("Settings"))
        QShortcut(QKeySequence("Ctrl+Q"), self, activated=self.quit)
        QShortcut(QKeySequence("Ctrl+Shift+O"), self, activated=lambda: self.go("ORBIT"))
        QShortcut(QKeySequence("Ctrl+Shift+Space"), self, activated=self._orbit_talk)
        self.orbit.immersive_changed.connect(self._immersive)
        QShortcut(QKeySequence("Ctrl+B"), self, activated=lambda: self.nav.set_collapsed(not self.nav.collapsed, notify=True))
        for i, name in enumerate(list(self.pages)[:9]):
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self, activated=lambda n=name: self.go(n))

        # tray
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(icon, self)
            self.tray.setToolTip(APP_NAME)
            menu = QMenu()
            for text, fn in (("Show Prometheus", self.show_and_raise), ("New conversation", self._new_conversation), ("Stop current request", self.companion.stop)):
                a = QAction(text, menu)
                a.triggered.connect(fn)
                menu.addAction(a)
            menu.addSeparator()
            q = QAction("Quit Prometheus", menu)
            q.triggered.connect(self.quit)
            menu.addAction(q)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(lambda r: self.show_and_raise() if r in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick) else None)
            self.tray.show()
            self._tray_menu = menu

        # due reminders: delivered to the window (and a notification) while the app runs
        self.reminder_timer = QTimer(self)
        self.reminder_timer.timeout.connect(self.check_reminders)
        self.reminder_timer.start(REMINDER_POLL_MS)

        self._apply_behaviour()
        geo = settings.get("window_geometry")
        if isinstance(geo, list) and len(geo) == 4 and all(isinstance(v, int) for v in geo) and geo[2] >= 800 and geo[3] >= 500:
            self.setGeometry(*geo)
        start = settings.get("last_section") if settings.get("last_section") in self.pages else "Home"
        self.go(start)

    # ----- launch -----
    def play_launch(self) -> None:
        """The birth of the sun, once per application start (never on tray restore or navigation)."""
        callbacks, self.after_launch = self.after_launch, []
        run_after = lambda: [QTimer.singleShot(150, cb) for cb in callbacks]  # noqa: E731
        if not self.settings.get("launch_animation") or self.settings.get("reduced_motion"):
            run_after()
            return
        try:
            from .launch import LaunchOverlay
            from .pages.companion import _gl_available

            self.launch = LaunchOverlay(self, _gl_available())
            self.launch.done.connect(run_after)
            self.launch.start()
        except Exception as e:  # the app is already usable; never let the animation block it
            self.statusBar().showMessage(f"Launch animation skipped: {e}", 6000)
            run_after()

    # ----- top bar -----
    def _topbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("topbar")
        bar.setFixedHeight(56)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(24, 10, 18, 10)
        lay.setSpacing(10)
        self.crumb = label("", "faint", wrap=False)
        lay.addWidget(self.crumb)
        lay.addStretch(1)
        search = QPushButton(icons.icon("search", T.TEXT_FAINT), "  Search everything…        Ctrl+K")
        search.setObjectName("searchField")
        search.setAccessibleName("Search everything")
        search.setCursor(Qt.CursorShape.PointingHandCursor)
        search.clicked.connect(self.open_palette)
        lay.addWidget(search)
        self.route_pill = label("", "pill", wrap=False)
        lay.addWidget(self.route_pill)
        self.auto_pill = label("AUTO-APPROVE ON", "pill", wrap=False)
        self.auto_pill.setStyleSheet(T.pill_style("err"))
        self.auto_pill.setToolTip("Tools with real-world effects run without asking. Turn it off in Settings.")
        lay.addWidget(self.auto_pill)
        self.bell = QToolButton()
        self.bell.setIconSize(QSize(18, 18))
        self.bell.setAccessibleName("Notifications")
        self.bell.clicked.connect(self.toggle_activity)
        lay.addWidget(self.bell)
        self.notifications.listeners.append(self._bell_badge)
        self._bell_badge()
        return bar

    def _bell_badge(self) -> None:
        n = self.notifications.unread
        self.bell.setIcon(icons.icon("bell", T.ACCENT if n else T.TEXT_SECONDARY))
        self.bell.setText(str(n) if n else "")
        self.bell.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon if n else Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.bell.setToolTip(f"{n} new notifications" if n else "Notifications")

    def toggle_activity(self) -> None:
        d = self.activity
        if d.isVisible():
            d.hide()
            return
        try:
            audit = list(reversed(self.core.audit_tail(60)))
        except Exception:
            audit = []
        d.fill(self.notifications.items, audit)
        self._place_overlays()
        d.show()
        d.raise_()
        self.notifications.read_all()

    def notify(self, text: str, tone: str = "ok", detail: str = "", source: str = "") -> None:
        """A toast for the result of an action; kept in the activity centre; announced to screen readers."""
        self.toasts.show(text, tone, detail)
        self.notifications.add(text, detail, tone, source or self.current_section())
        self.setAccessibleDescription(f"{text}. {detail}".strip())

    def _place_overlays(self) -> None:
        w = min(420, max(320, self.width() // 3))
        top = 56
        self.activity.setGeometry(self.width() - w, top, w, self.height() - top - (self.statusBar().height() if self.statusBar() else 0))
        self.toasts.place()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        if hasattr(self, "activity"):
            self._place_overlays()
        if getattr(self, "launch", None) is not None:
            try:
                self.launch.setGeometry(self.rect())
            except RuntimeError:
                self.launch = None

    # ----- navigation -----
    def go(self, name: str) -> None:
        if name not in self.pages:
            return
        if name != "ORBIT" and getattr(self, "orbit", None) is not None and self.orbit.immersive:
            self.orbit.set_immersive(False)
        page = self.pages[name]
        self.stack.setCurrentWidget(page)
        self.nav.select(name)
        self.crumb.setText(f"{SECTION_GROUP.get(name, '')}  /  {name}")
        self.settings.set("last_section", name)
        try:
            page.refresh()
        except Exception as e:
            self.statusBar().showMessage(f"Could not refresh {getattr(page, 'title', name)}: {e}", 8000)
            self.notify(f"Could not load {name}", str(e), "err")

    def current_section(self) -> str:
        w = self.stack.currentWidget()
        return next((n for n, p in self.pages.items() if p is w), "")

    def open_palette(self) -> None:
        entries = [(f"Go to {n}", (lambda n=n: self.go(n)), "section") for n in self.pages]
        entries += [
            ("New conversation", self._new_conversation, "command"),
            ("Open ORBIT", lambda: self.go("ORBIT"), "command"),
            ("Talk in ORBIT", self._orbit_talk, "command"),
            ("Plan this conversation in ORBIT", self.plan_in_orbit, "command"),
            ("New ORBIT session", lambda: (self.go("ORBIT"), self.orbit.new_session()), "command"),
            ("Stop current request", self.companion.stop, "command"),
            ("Reconnect providers", self._reconnect, "command"),
            ("Toggle navigation", lambda: self.nav.set_collapsed(not self.nav.collapsed, notify=True), "command"),
            ("Quit Prometheus", self.quit, "command"),
        ]
        from ..services import search

        ws = self.core.paths().get("workspace", "")
        CommandPalette(entries, lambda q: search.search(self.core, self.conversations, q, ws), self.open_result, self).exec()

    def open_result(self, r: dict) -> None:
        kind = r.get("kind")
        if kind == "conversation":
            self.go("Companion")
            self.companion.open_conversation(r["target"])
        elif kind == "memory":
            self.go("Memory")
            page = self.pages["Memory"]
            if hasattr(page, "show_query"):
                page.show_query(r["title"][:60])
        elif kind == "reminder":
            self.go("Reminders & tasks")
        elif kind == "file":
            self.go("Workspace")
            page = self.pages["Workspace"]
            if hasattr(page, "reveal"):
                page.reveal(r["target"])
        elif kind == "activity":
            self.go("Trust & safety")

    # ----- ORBIT -----
    def _orbit_talk(self) -> None:
        self.go("ORBIT")
        self.orbit.talk_shortcut()

    def plan_in_orbit(self, objective: str = "") -> None:
        """Contextual entry: start an ORBIT session from what you were doing (the open conversation's
        last message, a Forge objective, a workspace folder). Only text you already wrote is carried over."""
        if not objective:
            msgs = [m for m in self.companion.messages if m.get("role") == "user" and isinstance(m.get("content"), str)]
            objective = msgs[-1]["content"].strip() if msgs else ""
        self.go("ORBIT")
        self.orbit.new_session(objective[:600], {"from": self.current_section()})

    def _immersive(self, on: bool) -> None:
        """Immersive ORBIT: only the stage and its panels; Esc or Exit immersive brings the window back."""
        self.nav.setVisible(not on)
        self.topbar.setVisible(not on)
        self.statusBar().setVisible(not on)
        if on and self.current_section() != "ORBIT":
            self.go("ORBIT")

    def _new_conversation(self) -> None:
        self.go("Companion")
        self.companion.new_conversation()

    def _reconnect(self) -> None:
        ok = self.core.reload_router()
        self._update_provider()
        self.companion.refresh()
        self.notify("Providers reconnected" if ok else "No provider could be configured", "" if ok else "Add a key in Settings, or start Ollama.", "ok" if ok else "warn")

    # ----- status -----
    def _state(self, state: str) -> None:
        from .pages.companion import ORB_STATES

        _, text, colour = ORB_STATES.get(state, ORB_STATES["IDLE"])
        self.sb_state.setText(f"● {text}")
        self.sb_state.setStyleSheet(f"color: {colour};")
        if state in ("SUCCESS", "IDLE", "ERROR"):
            self._update_provider()

    def _update_provider(self) -> None:
        r = self.core.router
        auto = bool(self.settings.get("auto_approve"))
        self.auto_pill.setVisible(auto)
        if not r.configured:
            self.sb_provider.setText(f"No provider: {r.error}")
            self.route_pill.setText("No provider")
            self.route_pill.setStyleSheet(T.pill_style("warn"))
            self.route_pill.setToolTip("Add a key in Settings → Providers, or start Ollama.")
            return
        used = r.last_used_provider or r.provider
        model = r.last_used_model or r.default_model
        self.sb_provider.setText(f"{used} · {model}" + ("  ·  AUTO-APPROVE ON" if auto else ""))
        self.route_pill.setText(f"{used} · {model}")
        self.route_pill.setStyleSheet(T.pill_style("ok" if r.last_used_provider else "neutral"))
        self.route_pill.setToolTip("Last provider and model used" if r.last_used_provider else "Configured; not used yet in this session")

    # ----- behaviour -----
    def _apply_behaviour(self) -> None:
        reduced = bool(self.settings.get("reduced_motion"))
        self.companion.set_reduced_motion(reduced)
        self.orbit.set_reduced_motion(reduced)
        home = self.pages.get("Home")
        if hasattr(home, "set_reduced_motion"):
            home.set_reduced_motion(reduced)
        self._update_provider()

    def _restart_needed(self) -> None:
        self.statusBar().showMessage("The new workspace applies the next time Prometheus starts. Quit and reopen it.", 0)
        self.settings_page.ws_lbl.setText(f"{self.settings.get('workspace')}  (applies after restart)")

    def check_reminders(self) -> None:
        try:
            due = self.core.drain_due()
        except Exception as e:
            self.statusBar().showMessage(f"Reminder check failed: {e}", 8000)
            return
        for job in due:
            text = str(job.get("text") or job.get("task") or "Reminder")
            self.companion.add("Reminder", text, T.AMBER)
            self.notify("Reminder", text, "accent", "Reminders & tasks")
            if self.tray is not None and self.settings.get("show_notifications"):
                self.tray.showMessage(f"{APP_NAME} reminder", text, QSystemTrayIcon.MessageIcon.Information, 10_000)

    # ----- window lifecycle -----
    def show_and_raise(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def changeEvent(self, e: QEvent) -> None:
        if e.type() == QEvent.Type.WindowStateChange:
            self.companion.pause_animation(self.isMinimized())
        elif e.type() == QEvent.Type.ActivationChange:
            self.companion.set_window_active(self.isActiveWindow())
        super().changeEvent(e)

    def hideEvent(self, e) -> None:
        self.companion.pause_animation(True)
        super().hideEvent(e)

    def showEvent(self, e) -> None:
        self.companion.pause_animation(False)
        super().showEvent(e)

    def closeEvent(self, e: QCloseEvent) -> None:
        if not self._quitting and self.tray is not None and self.settings.get("close_to_tray"):
            e.ignore()
            self.hide()
            self.tray.showMessage(APP_NAME, "Still running in the tray. Quit from the tray menu.", QSystemTrayIcon.MessageIcon.Information, 4000)
            return
        self._shutdown()
        e.accept()
        QApplication.instance().quit()

    def quit(self) -> None:
        self._quitting = True
        self.close()

    def _shutdown(self) -> None:
        self.reminder_timer.stop()
        try:
            g = self.geometry()
            self.settings.set("window_geometry", [g.x(), g.y(), g.width(), g.height()])
        except Exception:
            pass
        self.companion.shutdown()
        self.orbit.shutdown()
        if self.tray is not None:
            self.tray.hide()
