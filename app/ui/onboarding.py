"""First launch: a short welcome that introduces Prometheus and helps connect a model provider.

Three steps (skippable at any point): what Prometheus is, connect a provider (paste a key into the OS
credential store, or use Ollama on this computer), and where Prometheus may work (the workspace).
Nothing is sent anywhere during onboarding; the connection test runs only if you press it.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLineEdit, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from .. import APP_NAME
from ..credentials import KNOWN_KEYS, CredentialError
from . import theme as T
from .sun import SolarGlyph
from .widgets import label, run_bg


class Onboarding(QDialog):
    def __init__(self, core, creds, paths, parent=None):
        super().__init__(parent)
        self.core, self.creds, self.paths = core, creds, paths
        self.setWindowTitle(f"Welcome to {APP_NAME}")
        self.setModal(True)
        self.resize(640, 470)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)
        self.stack.addWidget(self._welcome())
        self.stack.addWidget(self._provider())
        self.stack.addWidget(self._workspace())
        nav = QHBoxLayout()
        self.step = label("", "faint")
        nav.addWidget(self.step, 1)
        self.skip = QPushButton("Skip for now")
        self.skip.setObjectName("ghost")
        self.skip.clicked.connect(self.accept)
        self.back = QPushButton("Back")
        self.back.clicked.connect(lambda: self._go(self.stack.currentIndex() - 1))
        self.next = QPushButton("Next")
        self.next.setObjectName("primary")
        self.next.clicked.connect(self._next)
        for b in (self.skip, self.back, self.next):
            nav.addWidget(b)
        lay.addLayout(nav)
        self._go(0)

    def _page(self, title: str, body: str) -> tuple:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(10)
        v.addWidget(label(title, "h1"))
        v.addWidget(label(body, "sub"))
        return w, v

    def _welcome(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(12)
        sun = SolarGlyph(150)
        v.addWidget(sun, 0, Qt.AlignmentFlag.AlignHCenter)
        t = label(f"I am {APP_NAME}.", "h1")
        t.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        v.addWidget(t)
        b = label("An engineering companion that runs on your computer. I can talk things through, research, calculate, plan, remember what matters to you, and build inside a workspace folder you choose. Anything with real-world effects (writing files, running code or commands) asks you first, and every action is recorded where you can see it.", "sub")
        b.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        v.addWidget(b)
        v.addStretch(1)
        return w

    def _provider(self) -> QWidget:
        w, v = self._page("Connect a model", "I think with a language model. Use a cloud provider with your own key, or Ollama running on this computer (nothing leaves it).")
        row = QHBoxLayout()
        self.prov = QComboBox()
        self.prov.setAccessibleName("Provider")
        for name, title in KNOWN_KEYS.items():
            self.prov.addItem(title, name)
        row.addWidget(self.prov)
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setPlaceholderText("Paste the API key")
        self.key.setAccessibleName("API key")
        row.addWidget(self.key, 1)
        save = QPushButton("Save key")
        save.clicked.connect(self._save_key)
        save.setEnabled(self.creds.available)
        row.addWidget(save)
        v.addLayout(row)
        v.addWidget(label("Keys go to your operating system's credential store, never to a settings file." if self.creds.available else f"Secure key storage is unavailable ({self.creds.error}); put keys in a .env file in the data folder instead.", "faint"))
        v.addWidget(label("Or use Ollama: install it from ollama.com, run “ollama serve” and pull a model (for example “ollama pull llama3.2”). I use it automatically.", "faint"))
        trow = QHBoxLayout()
        self.test_btn = QPushButton("Test the connection")
        self.test_btn.clicked.connect(self._test)
        trow.addWidget(self.test_btn)
        self.test_msg = label("", "sub")
        trow.addWidget(self.test_msg, 1)
        v.addLayout(trow)
        v.addStretch(1)
        return w

    def _workspace(self) -> QWidget:
        w, v = self._page("Where I may work", "My file and shell tools only touch one folder: the workspace. Everything outside it is refused.")
        v.addWidget(label(f"Workspace now: {self.paths.workspace}", "accent"))
        v.addWidget(label("You can choose another folder in Settings → Workspace at any time (it applies after a restart). My own memory, conversations and logs stay in the data folder:", "faint"))
        v.addWidget(label(self.paths.data_dir, "mono"))
        v.addWidget(label("Press Ctrl+K anywhere to search conversations, memory, files and reminders, or to jump to a section.", "sub"))
        v.addStretch(1)
        return w

    def _go(self, i: int) -> None:
        i = max(0, min(self.stack.count() - 1, i))
        self.stack.setCurrentIndex(i)
        self.back.setEnabled(i > 0)
        self.next.setText("Start" if i == self.stack.count() - 1 else "Next")
        self.step.setText(f"Step {i + 1} of {self.stack.count()}")

    def _next(self) -> None:
        if self.stack.currentIndex() == self.stack.count() - 1:
            self.accept()
        else:
            self._go(self.stack.currentIndex() + 1)

    def _save_key(self) -> None:
        try:
            self.creds.set(self.prov.currentData(), self.key.text())
        except CredentialError as e:
            self.test_msg.setText(str(e))
            self.test_msg.setStyleSheet(f"color: {T.ERR};")
            return
        self.key.clear()
        self.core.reload_router()
        self.test_msg.setText("Saved. Press Test the connection to check it.")
        self.test_msg.setStyleSheet(f"color: {T.OK};")

    def _test(self) -> None:
        from ..services import providers

        self.core.reload_router()
        self.test_btn.setEnabled(False)
        self.test_msg.setText("Testing…")

        def done(results):
            self.test_btn.setEnabled(True)
            ok = [r for r in results if r["ok"]]
            if ok:
                self.test_msg.setText("Connected: " + ", ".join(f"{r['provider']} ({r['ms']} ms)" for r in ok))
                self.test_msg.setStyleSheet(f"color: {T.OK};")
            else:
                self.test_msg.setText("No provider answered. " + (results[0]["error"] if results else "Add a key or start Ollama."))
                self.test_msg.setStyleSheet(f"color: {T.WARN};")

        run_bg(lambda: providers.test_all(self.core), done, lambda m: (self.test_btn.setEnabled(True), self.test_msg.setText(m.splitlines()[0])), owner=self)
