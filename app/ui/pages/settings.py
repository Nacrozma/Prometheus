"""Settings: providers and keys, workspace, desktop behaviour, voice, data, about."""

from __future__ import annotations

import json
import os
import sys

from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QCheckBox, QFileDialog, QGridLayout, QHBoxLayout, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget

from ... import APP_NAME, __version__
from ...credentials import KNOWN_KEYS, CredentialError
from .. import theme as T
from ..widgets import Card, Page, label


class SettingsPage(Page):
    title = "Settings"
    subtitle = "Providers, workspace, desktop behaviour and data."
    restart_requested = pyqtSignal()
    behaviour_changed = pyqtSignal()

    def __init__(self, core, settings, creds, platform, paths, parent=None):
        super().__init__(core, parent)
        self.settings, self.creds, self.platform, self.paths = settings, creds, platform, paths
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        col = QVBoxLayout(host)
        col.setSpacing(12)
        scroll.setWidget(host)
        self.content.addWidget(scroll, 1)

        # ---- providers ----
        prov = Card("Providers and keys")
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
        prov.body.addLayout(row)
        self.router_detail = QPlainTextEdit()
        self.router_detail.setReadOnly(True)
        self.router_detail.setMaximumHeight(120)
        prov.body.addWidget(self.router_detail)
        col.addWidget(prov)

        # ---- workspace ----
        ws = Card("Workspace")
        self.ws_lbl = label(f"{paths.workspace}  ({paths.workspace_reason})", "sub", selectable=True)
        ws.body.addWidget(self.ws_lbl)
        ws.body.addWidget(label("The file and shell tools can only touch this folder. A new choice applies the next time Prometheus starts.", "faint"))
        pick = QPushButton("Choose workspace folder…")
        pick.clicked.connect(self._pick_workspace)
        ws.body.addWidget(pick)
        col.addWidget(ws)

        # ---- desktop behaviour ----
        dk = Card("Desktop")
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
        col.addWidget(dk)

        # ---- autonomy ----
        au = Card("Autonomy")
        self.auto = QCheckBox("Auto-approve tools with real-world effects (not recommended)")
        self.auto.setChecked(settings.get("auto_approve"))
        self.auto.toggled.connect(self._auto)
        au.body.addWidget(self.auto)
        au.body.addWidget(label("With this off, every write, shell command, code run, patch or hardware action shows an approval card first. Denied tools in permissions.json stay denied either way.", "faint"))
        col.addWidget(au)

        # ---- voice ----
        vc = Card("Voice")
        import gui_orb as g

        status = ["Voice input (Whisper): " + ("ready" if g.VOICE_INPUT_AVAILABLE else "not installed"), "Speech output (edge-tts): " + ("ready" if g.VOICE_OUTPUT_AVAILABLE else "not available")]
        vc.body.addWidget(label(" · ".join(status)))
        for why in g.VOICE_MISSING.values():
            vc.body.addWidget(label(why, "faint"))
        vc.body.addWidget(label("Whisper needs PyTorch (a large download), so it is optional. Speech output uses Microsoft's online edge-tts service: the text being spoken is sent to it. Recordings are transcribed in memory and never saved.", "faint"))
        col.addWidget(vc)

        # ---- data ----
        dt = Card("Data")
        dt.body.addWidget(label(f"Data folder: {paths.data_dir}  ({paths.data_reason})", "sub", selectable=True))
        for n in paths.notes:
            dt.body.addWidget(label(n, "faint"))
        open_btn = QPushButton("Open data folder")
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(paths.data_dir)))
        dt.body.addWidget(open_btn)
        dt.body.addWidget(label("Back up by copying this folder while Prometheus is closed. Keys are not in it (they are in the credential store).", "faint"))
        col.addWidget(dt)

        ab = Card("About")
        ab.body.addWidget(label(f"{APP_NAME} Desktop {__version__} · Python {sys.version.split()[0]} · {platform.name}" + ("" if platform.validated else " (desktop integration not yet validated on a real machine)"), "faint", selectable=True))
        col.addWidget(ab)
        col.addStretch(1)

    # ----- providers -----
    def refresh(self) -> None:
        for name, info in self.creds.status().items():
            lab = self.key_rows[name]
            lab.setText(f"{info['source']}{' · ' + info['hint'] if info['hint'] else ''}")
            lab.setStyleSheet(f"color: {T.OK if info['source'] != 'not set' else T.TEXT_FAINT};")
        st = self.core.router_status()
        active = st.get("active_providers", [])
        self.router_lbl.setText(("Active: " + ", ".join(active)) if active else "No provider is active.")
        self.router_detail.setPlainText(json.dumps({k: v for k, v in st.items() if k != "status"}, indent=2, default=str))

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
        self.settings.set(key, value)
        self.behaviour_changed.emit()

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
