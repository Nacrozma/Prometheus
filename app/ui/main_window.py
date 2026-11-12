"""The main window: sidebar navigation, the pages, a status bar, the command palette and the tray."""

from __future__ import annotations

from typing import Dict, List

from PyQt6.QtCore import QEvent, QSize, Qt, QTimer
from PyQt6.QtGui import QAction, QCloseEvent, QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QStackedWidget,
    QStatusBar,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME
from . import theme as T
from .pages.arm import ArmPage
from .pages.companion import CompanionPage
from .pages.engineering import EngineeringPage
from .pages.forge import ForgePage
from .pages.memory import MemoryPage
from .pages.obsidian import ObsidianPage
from .pages.reflection import ReflectionPage
from .pages.settings import SettingsPage
from .pages.tasks import TasksPage
from .pages.trust import TrustPage
from .pages.workspace import WorkspacePage
from .widgets import label

#: How often due reminders are checked (the core's scheduler marks them due; we deliver them).
REMINDER_POLL_MS = 15_000


class CommandPalette(QDialog):
    """Ctrl+K: type to jump to a section or run a command."""

    def __init__(self, entries: List[tuple], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Go to…")
        self.setModal(True)
        self.resize(460, 360)
        self.entries = entries  # (label, callable)
        lay = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Type a section or command…")
        self.search.setAccessibleName("Command search")
        self.list = QListWidget()
        lay.addWidget(self.search)
        lay.addWidget(self.list, 1)
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._run_current)
        self.list.itemActivated.connect(lambda _: self._run_current())
        self._filter("")

    def _filter(self, text: str) -> None:
        self.list.clear()
        t = text.lower().strip()
        for name, fn in self.entries:
            if not t or t in name.lower():
                item = QListWidgetItem(name)
                item.setData(Qt.ItemDataRole.UserRole, fn)
                self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _run_current(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        fn = item.data(Qt.ItemDataRole.UserRole)
        self.accept()
        fn()


class MainWindow(QMainWindow):
    def __init__(self, core, settings, creds, platform, paths, frozen: bool, icon: QIcon):
        super().__init__()
        self.core, self.settings, self.creds, self.platform, self.paths = core, settings, creds, platform, paths
        self._quitting = False
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(icon)
        self.setMinimumSize(QSize(1040, 680))
        self.resize(1280, 820)

        self.companion = CompanionPage(core, settings)
        self.pages: Dict[str, QWidget] = {
            "Companion": self.companion,
            "Memory": MemoryPage(core),
            "Engineering": EngineeringPage(core),
            "Forge": ForgePage(core, frozen),
            "Workspace": WorkspacePage(core),
            "Reminders & tasks": TasksPage(core),
            "Obsidian": ObsidianPage(core, self.companion),
            "Robot arm (simulation)": ArmPage(core),
            "Reflection": ReflectionPage(core),
            "Trust & safety": TrustPage(core, settings),
            "Settings": SettingsPage(core, settings, creds, platform, paths),
        }
        self.settings_page: SettingsPage = self.pages["Settings"]  # type: ignore[assignment]

        central = QWidget()
        row = QHBoxLayout(central)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(220)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(12, 18, 12, 12)
        brand = QLabel(APP_NAME.upper())
        brand.setObjectName("brand")
        sv.addWidget(brand)
        sv.addWidget(label("Desktop", "faint"))
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setAccessibleName("Sections")
        for name in self.pages:
            self.nav.addItem(name)
        sv.addWidget(self.nav, 1)
        sv.addWidget(label("Ctrl+K: go to · Esc: stop", "faint"))
        row.addWidget(side)

        self.stack = QStackedWidget()
        for page in self.pages.values():
            self.stack.addWidget(page)
        row.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.nav.currentRowChanged.connect(self._show)

        # status bar: provider, orb state, background activity
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
        self.nav.setCurrentRow(0)

    # ----- navigation -----
    def _show(self, row: int) -> None:
        if row < 0:
            return
        self.stack.setCurrentIndex(row)
        page = self.stack.currentWidget()
        try:
            page.refresh()
        except Exception as e:
            self.statusBar().showMessage(f"Could not refresh {page.title}: {e}", 8000)

    def go(self, name: str) -> None:
        names = list(self.pages)
        if name in names:
            self.nav.setCurrentRow(names.index(name))

    def open_palette(self) -> None:
        entries = [(f"Go to {n}", (lambda n=n: self.go(n))) for n in self.pages]
        entries += [("New conversation", self._new_conversation), ("Stop current request", self.companion.stop), ("Reconnect providers", self._reconnect), ("Quit Prometheus", self.quit)]
        CommandPalette(entries, self).exec()

    def _new_conversation(self) -> None:
        self.go("Companion")
        self.companion.new_conversation()

    def _reconnect(self) -> None:
        self.core.reload_router()
        self._update_provider()
        self.companion.refresh()

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
        if not r.configured:
            self.sb_provider.setText(f"No provider: {r.error}")
            return
        used = r.last_used_provider or r.provider
        model = r.last_used_model or r.default_model
        auto = "  ·  AUTO-APPROVE ON" if self.settings.get("auto_approve") else ""
        self.sb_provider.setText(f"{used} · {model}{auto}")

    # ----- behaviour -----
    def _apply_behaviour(self) -> None:
        self.companion.set_reduced_motion(bool(self.settings.get("reduced_motion")))
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
        if self.tray is not None:
            self.tray.hide()
