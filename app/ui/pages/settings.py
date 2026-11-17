"""Settings: providers and keys, workspace, desktop behaviour, voice, data, about."""

from __future__ import annotations

import os
import sys

from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QCheckBox, QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QLineEdit, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget

from ... import APP_NAME, __version__
from ...credentials import KNOWN_KEYS, CredentialError
from .. import theme as T
from .. import icons
from ..widgets import Card, Page, label, pill, run_bg


class SettingsPage(Page):
    title = "Settings"
    header = "none"
    margins = (0, 0, 0, 0)
    subtitle = "Providers and models, workspace, desktop behaviour, voice, data and backups."
    restart_requested = pyqtSignal()
    behaviour_changed = pyqtSignal()

    def __init__(self, core, settings, creds, platform, paths, parent=None):
        super().__init__(core, parent)
        self.settings, self.creds, self.platform, self.paths = settings, creds, platform, paths
        from PyQt6.QtCore import QSize, Qt
        from PyQt6.QtWidgets import QFrame, QListWidget, QListWidgetItem, QSplitter, QStackedWidget

        split = QSplitter()
        split.setHandleWidth(1)
        split.setChildrenCollapsible(False)
        rail = QFrame()
        rail.setObjectName("rail")
        rail.setMinimumWidth(210)
        rail.setMaximumWidth(260)
        rl = QVBoxLayout(rail)
        rl.setContentsMargins(16, 22, 12, 16)
        rl.addWidget(label("Settings", "h1"))
        rl.addWidget(label("Grouped by what you want to do. Changes save as you make them.", "faint"))
        self.rail = QListWidget()
        self.rail.setObjectName("rail")
        self.rail.setIconSize(QSize(16, 16))
        self.rail.setAccessibleName("Settings sections")
        rl.addWidget(self.rail, 1)
        split.addWidget(rail)
        self.sections = QStackedWidget()
        split.addWidget(self.sections)
        split.setStretchFactor(1, 1)
        split.setSizes([230, 900])
        self.content.addWidget(split, 1)
        self.rail.currentRowChanged.connect(self.sections.setCurrentIndex)

        def add(name: str, icon_name: str, intro: str, card) -> None:
            page = QScrollArea()
            page.setWidgetResizable(True)
            page.setFrameShape(QFrame.Shape.NoFrame)
            host = QWidget()
            v = QVBoxLayout(host)
            v.setContentsMargins(32, 24, 32, 20)
            v.setSpacing(10)
            v.addWidget(label(name, "h1"))
            v.addWidget(label(intro, "sub"))
            card.setObjectName("plainCard")
            v.addWidget(card)
            v.addStretch(1)
            page.setWidget(host)
            self.sections.addWidget(page)
            self.rail.addItem(QListWidgetItem(icons.icon(icon_name, T.TEXT_SECONDARY), name))
            if self.rail.count() == 1:
                self.rail.setCurrentRow(0)

        col = None  # sections are added with add()

        # ---- providers ----
        prov = Card("")
        store = f"Keys are stored in {platform.credential_backend()}" if creds.available else f"Secure key storage is unavailable: {creds.error}. Keys in your environment or a .env file still work; Prometheus will not write keys to a plain file."
        prov.body.addWidget(label(store, "faint" if creds.available else "warn"))
        grid = QGridLayout()
        self.key_rows = {}
        for r, (name, title) in enumerate(KNOWN_KEYS.items()):
            status = label("")
            edit = QLineEdit()
            edit.setEchoMode(QLineEdit.EchoMode.Password)
            edit.setPlaceholderText("Paste a key to save it")
            edit.setAccessibleName(f"{title} key")
            save = QPushButton("Save")
            save.clicked.connect(lambda _=False, n=name, e=edit: self._save_key(n, e))
            remove = QPushButton("Remove")
            remove.clicked.connect(lambda _=False, n=name: self._remove_key(n))
            for w in (save, remove, edit):
                w.setEnabled(creds.available)
            grid.addWidget(label(title), r, 0)
            grid.addWidget(status, r, 1)
            grid.addWidget(edit, r, 2)
            grid.addWidget(save, r, 3)
            grid.addWidget(remove, r, 4)
            self.key_rows[name] = status
        grid.setColumnStretch(2, 1)
        prov.body.addLayout(grid)
        prov.body.addWidget(label("Local Ollama needs no key: start it with “ollama serve” and Prometheus uses it as a provider.", "faint"))
        row = QHBoxLayout()
        self.router_lbl = label("", "sub")
        row.addWidget(self.router_lbl, 1)
        reload_btn = QPushButton("Reconnect providers")
        reload_btn.clicked.connect(self._reload)
        row.addWidget(reload_btn)
        self.test_btn = QPushButton(icons.icon("plug", T.TEXT_SECONDARY), " Test connections")
        self.test_btn.setToolTip("Asks each configured provider for its model list (no tokens are used) and measures the response time")
        self.test_btn.clicked.connect(self._test)
        row.addWidget(self.test_btn)
        prov.body.addLayout(row)
        self.health = QGridLayout()
        self.health.setHorizontalSpacing(12)
        prov.body.addLayout(self.health)
        self.health_msg = label("Test connections to check each provider and choose its model.", "faint")
        prov.body.addWidget(self.health_msg)
        add('Models & providers', 'plug', "Where Prometheus thinks. Keys are stored in your operating system's credential store; test a connection and choose each provider's model.", prov)

        # ---- workspace ----
        ws = Card("")
        self.ws_lbl = label(f"{paths.workspace}  ({paths.workspace_reason})", "sub", selectable=True)
        ws.body.addWidget(self.ws_lbl)
        ws.body.addWidget(label("The file and shell tools can only touch this folder. A new choice applies the next time Prometheus starts.", "faint"))
        pick = QPushButton("Choose workspace folder…")
        pick.clicked.connect(self._pick_workspace)
        ws.body.addWidget(pick)
        add('Workspace', 'workspace', "The one folder Prometheus's file and shell tools may use.", ws)

        # ---- desktop behaviour ----
        dk = Card("")
        caps = platform.capabilities()
        self.close_to_tray = QCheckBox("Keep running in the tray when the window is closed (Quit from the tray menu)")
        self.notify = QCheckBox("Show system notifications for due reminders")
        self.login = QCheckBox("Start Prometheus when I sign in")
        self.reduced = QCheckBox("Reduce motion (a still orb)")
        for box, key in ((self.close_to_tray, "close_to_tray"), (self.notify, "show_notifications"), (self.reduced, "reduced_motion")):
            box.setChecked(bool(settings.get(key)))
            box.toggled.connect(lambda v, k=key: self._set(k, v))
            dk.body.addWidget(box)
        self.login.setChecked(settings.get("launch_at_login"))
        self.login.setEnabled(caps.get("launch_at_login", False))
        self.login.toggled.connect(self._login)
        dk.body.addWidget(self.login)
        self.login_msg = label("", "faint")
        dk.body.addWidget(self.login_msg)
        for note in platform.notes():
            dk.body.addWidget(label(note, "faint"))
        add('Desktop', 'home', 'How Prometheus behaves on your desktop.', dk)

        # ---- autonomy ----
        au = Card("")
        self.auto = QCheckBox("Auto-approve tools with real-world effects (not recommended)")
        self.auto.setChecked(settings.get("auto_approve"))
        self.auto.toggled.connect(self._auto)
        au.body.addWidget(self.auto)
        au.body.addWidget(label("With this off, every write, shell command, code run, patch or hardware action shows an approval card first. Denied tools in permissions.json stay denied either way.", "faint"))
        ap = Card("")
        self.nav_box = QCheckBox("Keep the navigation collapsed to icons (Ctrl+B toggles it any time)")
        self.nav_box.setChecked(bool(settings.get("nav_collapsed")))
        self.nav_box.toggled.connect(self._nav)
        ap.body.addWidget(self.nav_box)
        ap.body.addWidget(label("Reduce motion is under Desktop. Home sections are chosen with Customize on Home. Conversation and context panels are toggled in the Companion and remembered.", "faint"))
        add('Appearance', 'sun', 'How Prometheus looks and how much it moves.', ap)
        add('Privacy & autonomy', 'shield', 'How much Prometheus may do without asking you.', au)

        # ---- voice ----
        vc = Card("")
        import gui_orb as g

        status = ["Voice input (Whisper): " + ("ready" if g.VOICE_INPUT_AVAILABLE else "not installed"), "Speech output (edge-tts): " + ("ready" if g.VOICE_OUTPUT_AVAILABLE else "not available")]
        vc.body.addWidget(label(" · ".join(status)))
        for why in g.VOICE_MISSING.values():
            vc.body.addWidget(label(why, "faint"))
        vc.body.addWidget(label("Whisper needs PyTorch (a large download), so it is optional. Speech output uses Microsoft's online edge-tts service: the text being spoken is sent to it. Recordings are transcribed in memory and never saved.", "faint"))
        add('Voice', 'mic', 'Speaking and listening, and where the audio goes.', vc)

        # ---- data ----
        dt = Card("")
        dt.body.addWidget(label(f"Data folder: {paths.data_dir}  ({paths.data_reason})", "sub", selectable=True))
        for n in paths.notes:
            dt.body.addWidget(label(n, "faint"))
        open_btn = QPushButton("Open data folder")
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(paths.data_dir)))
        dt.body.addWidget(open_btn)
        dt.body.addWidget(label("Back up by copying this folder while Prometheus is closed. Keys are not in it (they are in the credential store).", "faint"))
        exp = QPushButton(icons.icon("export", T.TEXT_SECONDARY), " Export a backup (.zip)…")
        exp.setToolTip("Everything in the data folder except .env files, logs and anything named like a key or secret")
        exp.clicked.connect(self._export)
        dt.body.addWidget(exp)
        imp = QPushButton("Import data from another Prometheus folder…")
        imp.clicked.connect(self._import)
        dt.body.addWidget(imp)
        self.import_lbl = label("", "faint")
        dt.body.addWidget(self.import_lbl)
        if settings.get("pending_import"):
            self.import_lbl.setText(f"Import from {settings.get('pending_import')} will run the next time Prometheus starts.")
        add('Data & backups', 'export', 'Where Prometheus keeps its memory and history, and how to back it up or bring it from another computer.', dt)

        ab = Card("")
        ab.body.addWidget(label(f"{APP_NAME} Desktop {__version__} · Python {sys.version.split()[0]} · {platform.name}" + ("" if platform.validated else " (desktop integration not yet validated on a real machine)"), "faint", selectable=True))
        add('About', 'sun', 'Version and platform.', ab)

    # ----- providers -----
    def refresh(self) -> None:
        for name, info in self.creds.status().items():
            lab = self.key_rows[name]
            lab.setText(f"{info['source']}{' · ' + info['hint'] if info['hint'] else ''}")
            lab.setStyleSheet(f"color: {T.OK if info['source'] != 'not set' else T.TEXT_FAINT};")
        st = self.core.router_status()
        active = st.get("active_providers", [])
        order = st.get("current_priority_order") or []
        cool = st.get("providers_on_cooldown") or {}
        text = ("Active: " + ", ".join(active)) if active else "No provider is active."
        if order:
            text += " · Order tried: " + " → ".join(str(o[0] if isinstance(o, (list, tuple)) else o) for o in order)
        if cool:
            text += " · Cooling down: " + ", ".join(f"{k} ({int(v)} s)" for k, v in cool.items())
        self.router_lbl.setText(text)

    def _test(self) -> None:
        from ...services import providers

        self.test_btn.setEnabled(False)
        self.health_msg.setText("Testing… (up to 8 seconds per provider)")
        run_bg(lambda: providers.test_all(self.core), self._show_health, lambda m: (self.health_msg.setText("Test failed: " + m.splitlines()[0]), self.test_btn.setEnabled(True)), owner=self)

    def _show_health(self, results) -> None:
        from ...services import providers

        self.test_btn.setEnabled(True)
        while self.health.count():
            w = self.health.takeAt(0).widget()
            if w is not None:
                w.setParent(None)
        if not results:
            self.health_msg.setText("No provider is configured: add a key above, or start Ollama and reconnect.")
            return
        for r, res in enumerate(results):
            self.health.addWidget(label(res["provider"]), r, 0)
            if res["ok"]:
                self.health.addWidget(pill(f"ok · {res['ms']} ms", "ok"), r, 1)
                combo = QComboBox()
                combo.setAccessibleName(f"{res['provider']} model")
                combo.addItem(f"{res['default_model']} (current)", res["default_model"])
                for m in res.get("models", []):
                    if m != res["default_model"]:
                        combo.addItem(m, m)
                combo.setMaximumWidth(380)
                self.health.addWidget(combo, r, 2)
                use = QPushButton("Use")
                use.clicked.connect(lambda _=False, n=res["provider"], c=combo: self._use_model(n, c.currentData()))
                self.health.addWidget(use, r, 3)
                note = f"{res['model_count']} models" + ("" if res.get("default_offered") in (True, None) else " · the current model is not in the provider's list")
                self.health.addWidget(label(note, "faint" if res.get("default_offered") in (True, None) else "warn"), r, 4)
            else:
                self.health.addWidget(pill("unreachable", "err"), r, 1)
                self.health.addWidget(label(res["error"], "faint"), r, 2, 1, 3)
        self.health_msg.setText("Changing a model applies to new requests and is saved with Prometheus's settings. Prometheus never switches you to a different provider or model on its own beyond the fallback order you can see above.")

    def _use_model(self, name: str, model: str) -> None:
        from ...services import providers

        notes = providers.set_model(name, model)
        self.health_msg.setText(f"{name} now uses {model}." + (" " + " ".join(notes) if notes else ""))
        self.refresh()

    def _export(self) -> None:
        from ...services import export as E

        path, _ = QFileDialog.getSaveFileName(self, "Save a backup", os.path.join(os.path.expanduser("~"), f"prometheus-backup-{__import__('time').strftime('%Y%m%d')}.zip"), "Zip archive (*.zip)")
        if not path:
            return
        try:
            res = E.export(self.paths.data_dir, path)
        except Exception as e:
            QMessageBox.warning(self, "Backup not saved", str(e))
            return
        self.import_lbl.setText(f"Backup saved to {res['path']}: {res['files']} files ({res['skipped']} left out: keys, logs, temporary files).")

    def _save_key(self, name: str, edit: QLineEdit) -> None:
        try:
            self.creds.set(name, edit.text())
        except CredentialError as e:
            QMessageBox.warning(self, "Key not saved", str(e))
            return
        edit.clear()
        self._reload()

    def _remove_key(self, name: str) -> None:
        if QMessageBox.question(self, "Remove key", f"Remove the {KNOWN_KEYS[name]} key from the credential store?") != QMessageBox.StandardButton.Yes:
            return
        self.creds.delete(name)
        self._reload()

    def _reload(self) -> None:
        self.core.reload_router()
        self.refresh()

    # ----- behaviour -----
    def _set(self, key: str, value) -> None:
        from ..feedback import notify

        self.settings.set(key, value)
        self.behaviour_changed.emit()
        notify(self, "Setting saved", "ok", {"close_to_tray": "Closing the window keeps Prometheus in the tray" if value else "Closing the window quits Prometheus", "show_notifications": "System notifications for reminders are on" if value else "System notifications are off", "reduced_motion": "Motion reduced: the sun holds still" if value else "Motion restored", "auto_approve": "Auto-approve is ON" if value else "Auto-approve is off: tools ask first"}.get(key, ""))

    def _nav(self, on: bool) -> None:
        win = self.window()
        if hasattr(win, "nav"):
            win.nav.set_collapsed(on, notify=True)
        else:
            self.settings.set("nav_collapsed", on)

    def _login(self, on: bool) -> None:
        if getattr(sys, "frozen", False):
            command = f'"{sys.executable}"'
        else:
            launcher = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "launcher.py")
            command = f'"{sys.executable}" "{launcher}"'
        try:
            self.platform.set_launch_at_login(on, command)
            self.settings.set("launch_at_login", on)
            self.login_msg.setText("Prometheus will start when you sign in." if on else "Prometheus will not start by itself.")
        except Exception as e:
            self.login_msg.setText(f"Could not change start-up registration: {e}")
            self.login.blockSignals(True)
            self.login.setChecked(not on)
            self.login.blockSignals(False)

    def _auto(self, on: bool) -> None:
        if on:
            ok = QMessageBox.warning(
                self,
                "Turn on auto-approve?",
                "Tools that write files, run shell commands, run code, apply patches or control hardware will run WITHOUT asking you first.\n\n"
                "The safety policy and denied tools still apply, but you will not see each action before it happens.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ok != QMessageBox.StandardButton.Yes:
                self.auto.blockSignals(True)
                self.auto.setChecked(False)
                self.auto.blockSignals(False)
                return
        self._set("auto_approve", on)

    def _import(self) -> None:
        from ...migration import MigrationError, plan

        d = QFileDialog.getExistingDirectory(self, "Folder that holds your existing Prometheus data")
        if not d:
            return
        try:
            p = plan(d, self.paths.data_dir)
        except MigrationError as e:
            QMessageBox.warning(self, "Nothing to import", str(e))
            return
        msg = p.summary() + "\n\nThe other folder is only read, never changed. The import runs the next time Prometheus starts, before it loads its memory. Queue it?"
        if QMessageBox.question(self, "Import data", msg) != QMessageBox.StandardButton.Yes:
            return
        self.settings.set("pending_import", os.path.realpath(d))
        self.import_lbl.setText(f"Import from {os.path.realpath(d)} will run the next time Prometheus starts. Quit and reopen Prometheus to import.")

    def _pick_workspace(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose the workspace folder")
        if not d:
            return
        real = os.path.realpath(d)
        if real in (os.path.realpath(os.path.expanduser("~")), os.path.realpath(os.path.abspath(os.sep))):
            QMessageBox.warning(self, "Too broad", "Choose a dedicated folder, not your whole home folder or a drive root.")
            return
        self.settings.set("workspace", real)
        self.restart_requested.emit()
