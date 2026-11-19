"""Companion: conversations with Prometheus, with the living sun beside them.

Reuses the HUD's real pieces instead of re-implementing them: `PrometheusWorker` (streaming, the
tool loop, the conscience check, fallbacks), the safe Markdown renderer, the speech pipeline and the
OpenGL sun. Conversations are kept in `ConversationStore` (many conversations: search, rename,
delete). Tool approvals are shown inline as cards with the exact tool and arguments as plain text;
the worker blocks until the operator answers. Deny is the default.
"""

from __future__ import annotations

import json
import time
from typing import Dict, List, Optional

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .. import icons
from .. import theme as T
from ..widgets import Page, icon_button, label

# Semantic states, each set by a real event: (shader mode for older callers, text, colour).
ORB_STATES = {
    "IDLE": (0, "Idle", T.TEXT_SECONDARY),
    "LISTENING": (2, "Listening", T.HIGHLIGHT),
    "THINKING": (1, "Thinking", T.ACCENT),
    "WORKING": (1, "Running a tool", T.SECONDARY_ACCENT),
    "RESEARCHING": (1, "Researching", T.HIGHLIGHT),
    "BUILDING": (1, "Building", T.SECONDARY_ACCENT),
    "EXECUTING": (1, "Running a tool", T.SECONDARY_ACCENT),
    "SPEAKING": (2, "Speaking", T.ACCENT),
    "SUCCESS": (0, "Done", T.OK),
    "WARNING": (0, "Waiting for your approval", T.HIGHLIGHT),
    "PAUSED": (0, "Waiting for your approval", T.HIGHLIGHT),
    "ERROR": (0, "Something went wrong", T.ERR),
    "ADAPTING": (3, "Adapting", T.SECONDARY_ACCENT),
    "PLANNING": (1, "Planning", T.HIGHLIGHT),
    "RUNNING": (1, "Running the workflow", T.SECONDARY_ACCENT),
    "OFFLINE": (0, "No provider", T.TEXT_FAINT),
}

#: Which avatar state a running tool shows.
BUILD_TOOLS = {"write_file", "edit_file", "run_code_forge", "synthesize_dynamic_tool", "apply_pending_patch", "sculpt_workspace", "propose_code_change", "run_skill"}
RESEARCH_TOOLS = {"web_search", "recall_memory", "memory_graph_view", "read_file", "read_source_code", "synthetic_council", "usage_history"}


def tool_state(tool: str) -> str:
    return "BUILDING" if tool in BUILD_TOOLS else "RESEARCHING" if tool in RESEARCH_TOOLS else "WORKING"


def calm_status(text: str) -> str:
    """The worker's HUD-style status lines, said plainly."""
    t = (text or "").strip()
    if t.startswith("PROMETHEUS SYNTHESIZING"):
        return "Thinking…"
    if t.startswith("ADAPTING SYSTEM LOGIC:"):
        return f"Running {t.split(':', 1)[1].strip()}…"
    if t.startswith("CORE ERROR:"):
        return "Error: " + t.split(":", 1)[1].strip()
    if t.startswith("STOPPED BY OPERATOR"):
        return "Stopped."
    return t[:1] + t[1:].lower() if t.isupper() else t


MD_THEME = {
    "text": T.TEXT, "dim": T.TEXT_FAINT, "amber": T.ACCENT, "cyan": T.HIGHLIGHT,
    "code_bg": "#0B0D13", "code_head": "#141722", "inline_bg": "#1B1F2B", "border": T.BORDER,
    "kw": "#F2A65A", "str": "#C9D98B", "com": "#6B7080", "num": "#F7D98B", "fn": "#8CC4FF", "deco": "#F4B52C", "builtin": "#E8C9A0",
}


class ApprovalCard(QFrame):
    """A deliberate approval: what Prometheus wants to do and why, what it affects, whether it can be
    undone, what leaves the computer, what happens if you deny — then the real diff or content, and the
    exact arguments on request. Approve and Deny carry equal visual weight; nothing is preselected."""

    answered = pyqtSignal(bool)

    def __init__(self, tool: str, args_json: str, parent: Optional[QWidget] = None, workspace: str = "", reason: str = ""):
        super().__init__(parent)
        from ...services.approval import describe
        import gui_markdown as md

        self.setObjectName("approval")
        self.setAccessibleName(f"Approval needed: {tool}")
        try:
            args = json.loads(args_json)
            pretty = json.dumps(args, indent=2, ensure_ascii=False)
        except Exception:
            args, pretty = {}, args_json
        d = describe(tool, args if isinstance(args, dict) else {}, workspace)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(8)
        head = QHBoxLayout()
        ic = label()
        ic.setPixmap(icons.pixmap("shield", T.HIGHLIGHT, 20))
        head.addWidget(ic)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(label("PROMETHEUS ASKS YOUR PERMISSION", "eyebrow"))
        t = label(d["title"], "h2")
        t.setStyleSheet("font-size: 13pt;")
        col.addWidget(t)
        head.addLayout(col, 1)
        tl = label(tool, "mono", wrap=False)
        head.addWidget(tl, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(head)
        if reason.strip():
            r = label("Why: " + " ".join(reason.split())[:320], "sub")
            lay.addWidget(r)
        lay.addWidget(label(d["what"]))
        if d["diff"]:
            view = QTextBrowser()
            view.setAccessibleName("Changes")
            view.setMaximumHeight(200)
            rows = []
            for ln in d["diff"]:
                colr = T.OK if ln.startswith("+") and not ln.startswith("+++") else T.ERR if ln.startswith("-") and not ln.startswith("---") else T.INFO if ln.startswith("@@") else T.TEXT_SECONDARY
                rows.append(f'<span style="color:{colr};">{md.esc(ln)}</span>')
            view.setHtml('<pre style="font-family:Consolas,monospace; font-size:9pt; margin:0;">' + "\n".join(rows) + "</pre>")
            lay.addWidget(view)
        elif d["preview"]:
            box = QPlainTextEdit(d["preview"])
            box.setReadOnly(True)
            box.setMaximumHeight(160)
            box.setAccessibleName("Content")
            box.setStyleSheet(f"font-family: {T.FONT_MONO}; font-size: 9pt;")
            lay.addWidget(box)
        facts = QGridLayout()
        facts.setHorizontalSpacing(14)
        facts.setVerticalSpacing(3)
        for r_, (k, v) in enumerate((("Affects", ", ".join(d["affects"]) or "—"), ("Undo", d["reversible"]), ("Your data", d["leaves"]), ("If you deny", d["if_denied"]))):
            kl = label(k, "faint", wrap=False)
            facts.addWidget(kl, r_, 0, Qt.AlignmentFlag.AlignTop)
            facts.addWidget(label(v, "sub"), r_, 1)
        facts.setColumnStretch(1, 1)
        lay.addLayout(facts)
        self.details = QPlainTextEdit(pretty)
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(150)
        self.details.setAccessibleName("Tool arguments")
        self.details.setStyleSheet(f"font-family: {T.FONT_MONO}; font-size: 9pt;")
        self.details.setVisible(False)
        row = QHBoxLayout()
        more = QPushButton("Show the exact arguments")
        more.setObjectName("link")
        more.setCheckable(True)
        more.toggled.connect(lambda on: (self.details.setVisible(on), more.setText("Hide the exact arguments" if on else "Show the exact arguments")))
        row.addWidget(more)
        row.addStretch(1)
        row.addWidget(label("Nothing runs until you choose. The core checks the call again and records it in the audit log.", "faint"), 0)
        lay.addLayout(row)
        lay.addWidget(self.details)
        btns = QHBoxLayout()
        btns.addStretch(1)
        deny = QPushButton(icons.icon("stop", T.TEXT), "  Deny")
        allow = QPushButton(icons.icon("check", T.TEXT), "  Approve")
        for b in (deny, allow):
            b.setObjectName("decision")
            b.setMinimumWidth(130)
        deny.setDefault(True)
        deny.setAccessibleName(f"Deny {d['title']}")
        allow.setAccessibleName(f"Approve {d['title']}")
        deny.clicked.connect(lambda: self.answered.emit(False))
        allow.clicked.connect(lambda: self.answered.emit(True))
        btns.addWidget(deny)
        btns.addWidget(allow)
        lay.addLayout(btns)


class Composer(QPlainTextEdit):
    """Multiline input: Enter sends, Shift+Enter starts a new line."""

    submitted = pyqtSignal()

    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (e.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.submitted.emit()
            return
        super().keyPressEvent(e)

    def text(self) -> str:  # QLineEdit-compatible helpers used by voice input and tests
        return self.toPlainText()

    def setText(self, t: str) -> None:
        self.setPlainText(t)
        c = self.textCursor()
        c.movePosition(c.MoveOperation.End)
        self.setTextCursor(c)


def _gl_available() -> bool:
    """True when an OpenGL 3.3 context can be created here (the shader sun needs one)."""
    try:
        from PyQt6.QtGui import QGuiApplication, QOffscreenSurface, QOpenGLContext

        if QGuiApplication.platformName() in ("offscreen", "minimal"):
            return False
        ctx = QOpenGLContext()
        if not ctx.create():
            return False
        surf = QOffscreenSurface()
        surf.create()
        ok = ctx.makeCurrent(surf) and ctx.format().majorVersion() * 10 + ctx.format().minorVersion() >= 33
        ctx.doneCurrent()
        return bool(ok)
    except Exception:
        return False


STARTERS = [
    ("Think something through", "Help me think through "),
    ("Calculate", "Calculate "),
    ("Plan work", "Break this into steps: "),
    ("Look at a project", "Look at the project in my workspace called "),
]


def list_items(text: str) -> list:
    """Bulleted or numbered items in a reply (for 'use as task steps'); empty if there are fewer than 2."""
    import re

    items = [m.group(2).strip() for m in re.finditer(r"^\s*([-*•]|\d+[.)])\s+(.+)$", text or "", re.M)]
    items = [re.sub(r"[*_`]", "", i)[:200] for i in items if i]
    return items[:20] if len(items) >= 2 else []


class CompanionPage(Page):
    title = "Companion"
    subtitle = ""
    header = "none"
    margins = (20, 14, 20, 12)
    state_changed = pyqtSignal(str)
    busy_changed = pyqtSignal(bool)

    def __init__(self, core, settings, conversations=None, parent=None):
        super().__init__(core, parent)
        import gui_orb as g
        import gui_markdown as md
        from gui_config import AppConfig

        from ...services.conversations import ConversationStore, visible

        self.g, self.md, self.visible = g, md, visible
        self.settings = settings
        self.config = AppConfig()
        try:
            g.apply_router_settings(self.config)
        except Exception:
            pass
        self.store = conversations or ConversationStore(core.paths()["data"])
        self.conv = self.store.open_current(g._load_session())
        self.messages: List[dict] = self.conv["messages"]
        self.worker = None
        self.card: Optional[ApprovalCard] = None
        self.entries: List[str] = []
        self.raw: Dict[int, str] = {}
        self.code: dict = {}
        self.streaming: Optional[int] = None
        self._stream_html = ""
        self.seq = 0
        self.state = "IDLE"
        self.spoke = False
        self.last_error = ""
        self._prefix_cache = ("", 0)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(1)
        self.history_panel = self._history_panel()
        conversation = self._conversation_panel()
        self.context_panel = self._presence_panel()
        split.addWidget(self.history_panel)
        split.addWidget(conversation)
        split.addWidget(self.context_panel)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 0)
        split.setSizes([250, 900, 280])
        self.content.addWidget(split, 1)
        self.history_panel.setVisible(bool(settings.get("companion_history")))
        self.context_panel.setVisible(bool(settings.get("companion_context")))
        self.hist_btn.setChecked(self.history_panel.isVisible())
        self.ctx_btn.setChecked(self.context_panel.isVisible())

        # Speech: the existing pipeline, used only where its packages are installed.
        self.tts = None
        if g.VOICE_OUTPUT_AVAILABLE:
            try:
                self.tts = g.TTSManager(voice=self.config.get("voice"), audio_callback=self._audio_level, rate_percent=self.config.get("speech_rate", 0))
                self.tts.set_muted(not self.config.get("speech_enabled", True))
            except Exception:
                self.tts = None
        self.voice = None
        self.refresh_voice()

        QShortcut(QKeySequence("Escape"), self, activated=self.stop, context=Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(lambda: self.set_state("IDLE"))
        # streamed text is re-rendered at most ~20 times a second, not on every token
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(50)
        self._render_timer.timeout.connect(self._render)
        self._render_history()
        self._reload_list()
        self.set_state("IDLE")
        self.refresh()

    # ----- layout -----
    def _history_panel(self) -> QWidget:
        w = QWidget()
        w.setMinimumWidth(200)
        w.setMaximumWidth(360)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 10, 0)
        lay.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(label("Conversations", "h2"), 1)
        top.addWidget(icon_button("plus", "New conversation (Ctrl+N)", self.new_conversation))
        lay.addLayout(top)
        self.conv_search = QLineEdit()
        self.conv_search.setPlaceholderText("Search conversations")
        self.conv_search.setAccessibleName("Search conversations")
        self.conv_search.setClearButtonEnabled(True)
        self.conv_search.textChanged.connect(lambda _: self._reload_list())
        lay.addWidget(self.conv_search)
        self.conv_list = QListWidget()
        self.conv_list.setObjectName("plain")
        self.conv_list.setAccessibleName("Conversations")
        self.conv_list.setWordWrap(False)
        self.conv_list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.conv_list.itemActivated.connect(lambda it: self.open_conversation(it.data(Qt.ItemDataRole.UserRole)))
        self.conv_list.itemClicked.connect(lambda it: self.open_conversation(it.data(Qt.ItemDataRole.UserRole)))
        self.conv_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.conv_list.customContextMenuRequested.connect(self._conv_menu)
        lay.addWidget(self.conv_list, 1)
        return w

    def _conversation_panel(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 0, 6, 0)
        lay.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(10)
        self.hist_btn = icon_button("chat", "Show or hide your conversations")
        self.hist_btn.setCheckable(True)
        self.hist_btn.toggled.connect(lambda on: self._toggle_panel("companion_history", self.history_panel, on))
        head.addWidget(self.hist_btn)
        self.presence = QHBoxLayout()
        self.presence.setSpacing(10)
        head.addLayout(self.presence)
        tcol = QVBoxLayout()
        tcol.setSpacing(0)
        self.conv_title = label("", "h2", wrap=False)
        tcol.addWidget(self.conv_title)
        self.state_line = label("", "faint", wrap=False)
        tcol.addWidget(self.state_line)
        head.addLayout(tcol, 1)
        self.mission_pill = label("", "pill", wrap=False)
        self.mission_pill.setVisible(False)
        head.addWidget(self.mission_pill)
        head.addWidget(icon_button("edit", "Rename this conversation", lambda: self.rename_conversation(self.conv["id"])))
        head.addWidget(icon_button("copy", "Copy the whole conversation", self._copy_all))
        head.addWidget(icon_button("plus", "New conversation (Ctrl+N)", self.new_conversation))
        self.ctx_btn = icon_button("reflection", "Show or hide context: provider, voice, what is sent")
        self.ctx_btn.setCheckable(True)
        self.ctx_btn.toggled.connect(lambda on: self._toggle_panel("companion_context", self.context_panel, on))
        head.addWidget(self.ctx_btn)
        lay.addLayout(head)
        frame = QFrame()
        fl = QHBoxLayout(frame)
        fl.setContentsMargins(0, 0, 0, 0)
        self.view = QTextBrowser()
        self.view.setObjectName("conversation")
        self.view.setOpenLinks(False)
        self.view.anchorClicked.connect(self._link)
        self.view.setAccessibleName("Conversation")
        self.view.setMaximumWidth(880)
        fl.addStretch(1)
        fl.addWidget(self.view, 20)
        fl.addStretch(1)
        lay.addWidget(frame, 1)
        self.card_slot = QVBoxLayout()
        lay.addLayout(self.card_slot)

        box = QFrame()
        box.setObjectName("composerBox")
        box.setMaximumWidth(880)
        bl = QVBoxLayout(box)
        bl.setContentsMargins(12, 8, 10, 8)
        bl.setSpacing(4)
        self.input = Composer()
        self.input.setObjectName("composer")
        self.input.setPlaceholderText("Message Prometheus…  (Enter to send · Shift+Enter for a new line · / for commands)")
        self.input.setAccessibleName("Message")
        self.input.setFixedHeight(64)
        self.input.submitted.connect(self.send)
        bl.addWidget(self.input)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.mic = QPushButton(icons.icon("mic", T.TEXT_SECONDARY, active=T.HIGHLIGHT, disabled=T.TEXT_FAINT), " Talk")
        self.mic.setObjectName("ghost")
        self.mic.setAccessibleName("Voice input")
        self.mic.setCheckable(True)
        self.mic.toggled.connect(self._mic_toggled)
        row.addWidget(self.mic)
        self.composer_route = label("", "faint", wrap=False)
        row.addWidget(self.composer_route, 1)
        self.stop_btn = QPushButton(icons.icon("stop", T.TEXT, disabled=T.TEXT_FAINT), " Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setToolTip("Stop (Esc)")
        self.stop_btn.clicked.connect(self.stop)
        row.addWidget(self.stop_btn)
        self.send_btn = QPushButton(icons.icon("send", T.ON_ACCENT), " Send")
        self.send_btn.setObjectName("primary")
        self.send_btn.clicked.connect(self.send)
        row.addWidget(self.send_btn)
        bl.addLayout(row)
        crow = QHBoxLayout()
        crow.addStretch(1)
        crow.addWidget(box, 20)
        crow.addStretch(1)
        lay.addLayout(crow)
        return w

    def _presence_panel(self) -> QWidget:
        w = QWidget()
        w.setMinimumWidth(230)
        w.setMaximumWidth(340)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 0, 0, 0)
        lay.setSpacing(8)
        self.orb = None
        self.glyph = None
        if _gl_available():
            try:
                from ..solar import SolarAvatar

                self.orb = SolarAvatar()
                self.orb.setFixedSize(64, 64)
                self.presence.addWidget(self.orb)
            except Exception:
                self.orb = None
        if self.orb is None:
            from ..sun import SolarGlyph

            self.glyph = SolarGlyph(64)
            self.glyph.setFixedSize(64, 64)
            self.glyph.setToolTip("Painted sun: OpenGL 3.3 is not available here.")
            self.presence.addWidget(self.glyph)
        lay.addWidget(label("CONTEXT", "eyebrow"))
        self.state_lbl = label("Idle", wrap=False)
        lay.addWidget(self.state_lbl)
        self.route_lbl = label("", "faint")
        lay.addWidget(self.route_lbl)
        self.voice_lbl = label("", "faint")
        lay.addWidget(self.voice_lbl)
        self.context_lbl = label("", "faint")
        lay.addWidget(self.context_lbl)
        lay.addStretch(1)
        return w

    def _toggle_panel(self, key: str, panel, on: bool) -> None:
        panel.setVisible(on)
        self.settings.set(key, bool(on))

    # ----- conversation list -----
    def _reload_list(self) -> None:
        self.conv_list.clear()
        for c in self.store.list(self.conv_search.text()):
            if not c["messages"] and c["id"] != self.conv["id"]:
                continue  # empty conversations are not listed (except the open one)
            it = QListWidgetItem(f"{c['title']}\n{c['updated'][5:16].replace('T', ' ')} · {c['messages']} messages")
            it.setData(Qt.ItemDataRole.UserRole, c["id"])
            it.setToolTip(c["preview"] or c["title"])
            it.setSizeHint(QSize(0, 50))
            self.conv_list.addItem(it)
            if c["id"] == self.conv["id"]:
                it.setSelected(True)
                self.conv_list.setCurrentItem(it)
        if not self.conv_list.count():
            it = QListWidgetItem("No matches" if self.conv_search.text() else "No conversations yet")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.conv_list.addItem(it)
        self.conv_title.setText(self.conv.get("title") or "New conversation")
        m = self.conv.get("mission")
        if m:
            from ...services.forge_missions import DISCIPLINES

            d = DISCIPLINES.get(m.get("discipline"), {})
            self.mission_pill.setText(f"Forge · {d.get('name', m.get('discipline'))} · {m.get('project')}")
            self.mission_pill.setStyleSheet(T.pill_style("accent"))
            self.mission_pill.setToolTip(d.get("boundary", ""))
        self.mission_pill.setVisible(bool(m))

    def _conv_menu(self, pos) -> None:
        it = self.conv_list.itemAt(pos)
        cid = it.data(Qt.ItemDataRole.UserRole) if it else None
        if not cid:
            return
        m = QMenu(self)
        m.addAction(icons.icon("chat", T.TEXT_SECONDARY), "Open", lambda: self.open_conversation(cid))
        m.addAction(icons.icon("edit", T.TEXT_SECONDARY), "Rename…", lambda: self.rename_conversation(cid))
        m.addSeparator()
        m.addAction(icons.icon("trash", T.ERR), "Delete…", lambda: self.delete_conversation(cid))
        m.exec(self.conv_list.mapToGlobal(pos))

    def open_conversation(self, cid: str) -> None:
        if not cid or cid == self.conv.get("id"):
            return
        if self.busy():
            self.add("System", "Stop the current request before switching conversations.", T.WARN)
            return
        c = self.store.get(cid)
        if c is None:
            self.add("System", "That conversation no longer exists.", T.WARN)
            self._reload_list()
            return
        self._save()
        self.conv, self.messages = c, c["messages"]
        self.store.set_current(cid)
        self._reset_view()
        self._render_history()
        self._reload_list()

    def rename_conversation(self, cid: str) -> None:
        c = self.store.get(cid)
        if c is None:
            return
        title, ok = QInputDialog.getText(self, "Rename conversation", "Title:", text=c.get("title", ""))
        if ok and title.strip():
            self.store.rename(cid, title)
            if cid == self.conv["id"]:
                self.conv = self.store.get(cid) or self.conv
                self.messages = self.conv["messages"]
            self._reload_list()

    def delete_conversation(self, cid: str, confirm: bool = True) -> bool:
        c = self.store.get(cid)
        if c is None:
            return False
        if cid == self.conv["id"] and self.busy():
            self.add("System", "Stop the current request before deleting this conversation.", T.WARN)
            return False
        if confirm:
            ans = QMessageBox.question(self, "Delete conversation", f"Delete “{c.get('title', '')}”? Its messages are removed from this computer. This cannot be undone.", QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.Cancel)
            if ans != QMessageBox.StandardButton.Yes:
                return False
        self.store.delete(cid)
        if cid == self.conv["id"]:
            rest = self.store.list()
            self.conv = self.store.get(rest[0]["id"]) if rest else self.store.create([])
            self.store.set_current(self.conv["id"])
            self.messages = self.conv["messages"]
            self._reset_view()
            self._render_history()
        self._reload_list()
        return True

    # ----- display -----
    def refresh_voice(self) -> None:
        """Pick up voice input set up (or removed) in Settings → Voice, without a restart."""
        from ..voice_setup import make_voice_input

        if self.voice is not None and self.voice.isRunning():
            return
        self.voice = make_voice_input(self.core.paths()["data"])
        if self.voice is not None:
            self.voice.transcription_done.connect(self._transcribed)
            self.voice.status_signal.connect(lambda s: self.state_lbl.setText(s.capitalize()))
            self.voice.audio_level_signal.connect(self._audio_level)
            self.voice.finished.connect(lambda: self.mic.setChecked(False))
        self.mic.setEnabled(self.voice is not None)
        self.mic.setToolTip("Talk (speech is transcribed on this computer; the text is put in the box for you to check)" if self.voice else "Voice input is not set up: Settings → Voice → Set up voice input.")
        self.voice_lbl.setText(self._voice_text())

    def _voice_text(self) -> str:
        speech = "Speech: " + ("on (edge-tts, sends the reply text to Microsoft's speech service)" if self.tts and self.config.get("speech_enabled", True) else "ready, muted" if self.tts else "not available")
        from ..voice_setup import voice_input_text

        return voice_input_text(self.voice) + "\n" + speech

    def refresh(self) -> None:
        r = self.core.router
        used = r.last_used_provider or r.provider
        model = r.last_used_model or r.default_model
        if r.configured and used and used != "none":
            self.route_lbl.setText(f"Provider: {used} · {model}")
            self.composer_route.setText(f"{used} · {model}")
            if self.state == "OFFLINE":
                self.set_state("IDLE")
        else:
            self.route_lbl.setText("No provider configured: add a key in Settings → Providers, or start Ollama.")
            self.composer_route.setText("No provider")
            if not self.busy():
                self.set_state("OFFLINE")
        shown = self.visible(self.messages)
        self.context_lbl.setText(f"This conversation: {len(shown)} messages ({len(self.messages)} with tool results). The most recent {self.g.MAX_SESSION_MESSAGES} are kept and sent; memory facts relevant to each message are added by the core.")

    def set_state(self, state: str) -> None:
        _, text, colour = ORB_STATES.get(state, ORB_STATES["IDLE"])
        self.state = state
        if self.orb is not None:
            self.orb.set_semantic("WORKING" if state == "EXECUTING" else state)
        if self.glyph is not None:
            self.glyph.set_state("WORKING" if state == "EXECUTING" else state)
        self.state_lbl.setText(text)
        self.state_lbl.setStyleSheet(f"color: {colour}; font-weight: 600;")
        self.state_line.setText(f"● {text}")
        self.state_line.setStyleSheet(f"color: {colour};")
        self.state_line.setAccessibleName(f"Prometheus is {text.lower()}")
        self.state_changed.emit(state)

    def set_reduced_motion(self, reduced: bool) -> None:
        """Reduced motion: a still sun that is redrawn when the state changes."""
        if self.orb is not None:
            self.orb.set_reduced_motion(reduced)
        if self.glyph is not None:
            self.glyph.set_reduced_motion(reduced)

    def pause_animation(self, paused: bool) -> None:
        """Stop drawing the sun while the window is hidden or minimised."""
        if self.orb is not None:
            self.orb.set_paused(paused)

    def set_window_active(self, active: bool) -> None:
        if self.orb is not None:
            self.orb.set_window_active(active)

    def _entry(self, who: str, body_html: str, colour: str, actions: str = "") -> str:
        stamp = time.strftime("%H:%M")
        if who == "You":
            return (f'<table width="100%" cellspacing="0" cellpadding="0" style="margin:14px 0 4px 0;"><tr><td width="12%"></td>'
                    f'<td bgcolor="{T.SURFACE_ELEVATED}" style="padding:10px 14px;"><span style="color:{T.TEXT_FAINT}; font-size:8pt;">You · {stamp}</span>'
                    f'<div style="margin-top:3px;">{body_html}</div></td></tr></table>')
        if who in ("Tool", "System", "Reminder"):
            return f'<div style="margin:6px 0 6px 2px; color:{colour}; font-size:9pt;">{body_html}</div>'
        return (f'<div style="margin:16px 0 4px 0;"><span style="color:{colour}; font-weight:600;">☀ {who}</span>'
                f' <span style="color:{T.TEXT_FAINT}; font-size:8pt;">{stamp}</span>{actions}'
                f'<div style="margin:4px 0 0 0;">{body_html}</div></div>')

    def _md(self, text: str) -> str:
        self.seq += 1
        return self.md.render_markdown(text, MD_THEME, self.code, id_prefix=f"m{self.seq}")

    def _actions(self, idx: int, last: bool) -> str:
        links = f' &nbsp; <a href="copymsg:{idx}" style="color:{T.TEXT_FAINT}; font-size:8pt;">Copy</a>'
        if list_items(self.raw.get(idx, "")):
            links += f' &nbsp; <a href="steps:{idx}" style="color:{T.TEXT_FAINT}; font-size:8pt;">Use as task steps</a>'
        if last:
            links += f' &nbsp; <a href="regenerate:" style="color:{T.TEXT_FAINT}; font-size:8pt;">Regenerate</a>'
        return links

    def add(self, who: str, text: str, colour: str = T.TEXT, markdown: bool = False) -> None:
        body = self._md(text) if markdown else self.md.esc(text).replace("\n", "<br/>")
        if who == "Tool":
            body = f'<span style="font-family:Consolas,monospace;">⚙ {body}</span>'
        idx = len(self.entries)
        if who == "Prometheus":
            self.raw[idx] = text
        self.entries.append(self._entry(who, body, colour, self._actions(idx, False) if who == "Prometheus" else ""))
        self._render()

    def _render(self) -> None:
        bar = self.view.verticalScrollBar()
        at_end = bar.value() >= bar.maximum() - 30
        visible_entries = self.entries[-300:]
        self.view.setHtml("".join(visible_entries))
        if at_end:
            bar.setValue(bar.maximum())

    def _reset_view(self) -> None:
        self.entries.clear()
        self.raw.clear()
        self.code.clear()
        self.streaming = None
        self.last_error = ""

    def _render_history(self) -> None:
        shown = self.visible(self.messages)
        for m in shown[-60:]:
            if m["role"] == "user":
                self.add("You", m["content"], T.TEXT)
            else:
                self.add("Prometheus", m["content"], T.ACCENT, markdown=True)
        if not shown:
            self._welcome()
        self._mark_last()
        self.refresh()

    def _welcome(self) -> None:
        """An empty conversation: an invitation and starters (they fill the box; nothing is sent)."""
        chips = " &nbsp; ".join(f'<a href="starter:{i}" style="color:{T.HIGHLIGHT}; text-decoration:none;">{t}</a>' for i, (t, _) in enumerate(STARTERS))
        self.entries.append(
            f'<div style="margin:60px 0 0 0; text-align:center;"><span style="font-size:20pt; color:{T.ACCENT};">☀</span>'
            f'<p style="font-size:15pt; color:{T.TEXT}; margin:8px 0 4px 0;">What shall we work on?</p>'
            f'<p style="color:{T.TEXT_SECONDARY};">I can research, calculate, plan, build in your workspace and remember what matters.<br/>Anything with real-world effects asks you first.</p>'
            f'<p style="margin-top:14px;">{chips}</p></div>'
        )
        self._render()

    def _mark_last(self) -> None:
        """Give the newest Prometheus reply a Regenerate link (only when it answers the last message)."""
        last = max((i for i in self.raw), default=None)
        if last is None or not self.visible(self.messages) or self.visible(self.messages)[-1]["role"] != "assistant":
            return
        self.entries[last] = self._entry("Prometheus", self._md(self.raw[last]), T.ACCENT, self._actions(last, True))
        self._render()

    def _link(self, url) -> None:
        href = url.toString()
        if href.startswith(self.md.COPY_PREFIX):
            code = self.code.get(href[len(self.md.COPY_PREFIX):])
            if code is not None:
                QApplication.clipboard().setText(code)
                self.state_lbl.setText("Code copied")
        elif href.startswith("copymsg:"):
            try:
                QApplication.clipboard().setText(self.raw[int(href.split(":", 1)[1])])
                self.state_lbl.setText("Message copied")
            except (KeyError, ValueError):
                pass
        elif href.startswith("starter:"):
            try:
                self.input.setText(STARTERS[int(href.split(":", 1)[1])][1])
                self.input.setFocus()
            except (IndexError, ValueError):
                pass
        elif href.startswith("steps:"):
            self._use_as_steps(int(href.split(":", 1)[1]))
        elif href == "regenerate:":
            self.regenerate()
        elif href == "retry:":
            self.regenerate()
        elif href.startswith(("http://", "https://")):
            QDesktopServices.openUrl(url)

    def _use_as_steps(self, idx: int) -> None:
        """Make the list in a reply the current task's steps (through update_task_state, audited)."""
        from ..feedback import notify

        items = list_items(self.raw.get(idx, ""))
        if not items:
            return
        res = self.core.dispatch("update_task_state", steps=items, status="in_progress")
        if res.get("status") == "success":
            notify(self, f"{len(items)} steps saved as the current task", "ok", "Open Reminders & tasks to tick them off.")
        else:
            notify(self, "The steps were not saved", "err", str(res.get("message") or res.get("reason") or res))

    def _copy_all(self) -> None:
        lines = [f"{'You' if m['role'] == 'user' else 'Prometheus'}: {m['content']}" for m in self.visible(self.messages)]
        QApplication.clipboard().setText("\n\n".join(lines))
        self.state_lbl.setText("Conversation copied")

    # ----- a turn -----
    def busy(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def send(self, text: Optional[str] = None) -> None:
        text = (text if isinstance(text, str) else self.input.text()).strip()
        if not text:
            return
        if self.busy():
            self.add("System", "Still working on the previous request. Press Stop (Esc) to cancel it.", T.WARN)
            return
        if text.startswith("/"):
            self.input.clear()
            self.add("You", text)
            self._slash(text)
            return
        if not self.core.router.configured:
            self.add("System", "No model provider is configured, so nothing was sent. Add a key in Settings → Providers, or start Ollama.", T.WARN)
            self.set_state("OFFLINE")
            return
        self.input.clear()
        self.add("You", text)
        self.messages.append({"role": "user", "content": text})
        self._save()
        self._start()

    def regenerate(self) -> None:
        """Answer the last message again: the reply (and its tool steps) after it are replaced."""
        if self.busy():
            return
        last_user = max((i for i, m in enumerate(self.messages) if m.get("role") == "user"), default=None)
        if last_user is None:
            return
        del self.messages[last_user + 1:]
        self._reset_view()
        self._render_history()
        self._start()

    def _start(self) -> None:
        self.spoke = False
        self.last_error = ""
        auto = bool(self.settings.get("auto_approve")) and not self.conv.get("mission")  # never inside a Forge mission
        w = self.g.PrometheusWorker(self.core.router, self.messages, auto_approve=auto, fallback_models=self.config.get("fallback_models"))
        w.state_changed.connect(self._worker_state)
        w.status_updated.connect(self._status)
        w.tool_executed.connect(self._tool_done)
        w.text_delta.connect(self._delta)
        w.response_received.connect(self._response)
        w.partial_text.connect(self._speak_sentence)
        w.confirmation_requested.connect(self._confirm)
        w.finished.connect(self._finished)
        self.worker = w
        self.stop_btn.setEnabled(True)
        self.send_btn.setEnabled(False)
        self.busy_changed.emit(True)
        self.set_state("THINKING")
        w.start()

    def _worker_state(self, s: str) -> None:
        if s == "THINKING":
            self.set_state("THINKING")
        elif s == "ADAPTING":
            self.set_state("WORKING")  # the worker's tool phase; refined per tool in _status
        elif s == "IDLE" and self.last_error:
            self.set_state("ERROR")

    def _status(self, text: str, _colour: str = "") -> None:
        t = (text or "").strip()
        if t.startswith("ADAPTING SYSTEM LOGIC:"):
            self.set_state(tool_state(t.split(":", 1)[1].strip()))
        if t.startswith("CORE ERROR:"):
            self.last_error = t.split(":", 1)[1].strip()
            self.add("System", f"Something went wrong: {self.last_error}", T.ERR)
            self.entries[-1] = self.entries[-1].replace("</div>", f' &nbsp;<a href="retry:" style="color:{T.ACCENT};">Retry</a></div>', 1)
            self._render()
            self.set_state("ERROR")
        elif t.startswith(("RESPONSE HIT THE TOKEN LIMIT", "TOOL LOOP LIMIT")):
            self.add("System", calm_status(t), T.WARN)
        self.state_lbl.setText(calm_status(t)[:60] if not t.startswith("CORE ERROR") else "Something went wrong")

    def _delta(self, raw: str) -> None:
        entry = self._entry("Prometheus", self._md(raw), T.ACCENT)
        if self.streaming is None:
            self.entries.append(entry)
            self.streaming = len(self.entries) - 1
        else:
            self.entries[self.streaming] = entry
        if not self._render_timer.isActive():
            self._render_timer.start()

    def _response(self, text: str) -> None:
        idx = self.streaming if self.streaming is not None else len(self.entries)
        if self.streaming is None:
            self.entries.append("")
        self.raw[idx] = text
        self.entries[idx] = self._entry("Prometheus", self._md(text), T.ACCENT, self._actions(idx, False))
        self.streaming = None
        self._render()
        if self.tts and not self.spoke and text.strip():
            self.tts.speak(self.md.clean_for_speech(text))
            self.set_state("SPEAKING")

    def _speak_sentence(self, sentence: str) -> None:
        if self.tts:
            self.spoke = True
            self.tts.speak(sentence)
            self.set_state("SPEAKING")

    def _tool_done(self, tool: str, args: str, result: str) -> None:
        try:
            status = json.loads(result).get("status", "")
        except Exception:
            status = ""
        # a tool's own text goes on its own line; the streamed reply continues below it
        if self.streaming is not None:
            self.streaming = None
        colour = T.OK if status == "success" else T.WARN if status in ("refused", "denied", "cancelled") else T.ERR if status in ("error", "execution_error") else T.TEXT_SECONDARY
        word = {"success": "done", "refused": "refused", "denied": "denied", "cancelled": "cancelled", "error": "failed", "execution_error": "failed"}.get(status, status or "done")
        self.add("Tool", f"{tool} — {word}", colour)

    def _confirm(self, tool: str, args_json: str) -> None:
        m = self.conv.get("mission")
        if m:
            from ...services import forge_missions as F

            try:
                args = json.loads(args_json)
            except Exception:
                args = {}
            ok, reason = F.decide(m.get("discipline", ""), tool, args if isinstance(args, dict) else {}, self.core.paths()["workspace"])
            if not ok:
                if self.worker is not None:
                    self.worker.provide_confirmation(False)
                self.core.p.audit_log.record(tool, args, "refused", f"forge discipline {m.get('discipline')}: {reason}")
                F.MissionLog(self.core.paths()["data"]).count_refusal(m.get("id", ""))
                self.add("System", f"Refused {tool}: {reason}", T.WARN)
                return
        self.set_state("WARNING")
        self._clear_card()
        reason = next((m.get("content") or "" for m in reversed(self.messages) if m.get("role") == "assistant" and m.get("tool_calls")), "")
        self.card = ApprovalCard(tool, args_json, workspace=self.core.paths()["workspace"], reason=reason)
        self.card.answered.connect(lambda ok, t=tool: self._answer(t, ok))
        self.card_slot.addWidget(self.card)
        self.window().activateWindow()

    def _answer(self, tool: str, approved: bool) -> None:
        self._clear_card()
        if self.worker is not None:
            self.worker.provide_confirmation(approved)
        self.add("System", f"You {'approved' if approved else 'denied'} {tool}.", T.OK if approved else T.ERR)
        self.set_state(tool_state(tool) if approved else "THINKING")

    def _clear_card(self) -> None:
        if self.card is not None:
            self.card.setParent(None)
            self.card.deleteLater()
            self.card = None

    def stop(self) -> None:
        if self.tts:
            try:
                self.tts.set_muted(True)
                self.tts.set_muted(not self.config.get("speech_enabled", True))
            except Exception:
                pass
        if self.busy():
            if self.card is not None:
                self._answer("the pending tool", False)
            self.worker.request_stop()
            self.add("System", "Stopping.", T.WARN)

    def _save(self) -> None:
        self.g.trim_messages(self.messages, self.g.MAX_SESSION_MESSAGES)
        self.store.save(self.conv)
        self.g._save_session(self.messages)  # the HUD continues from the same conversation

    def _finished(self) -> None:
        self._render_timer.stop()
        self.streaming = None
        self._render()
        self.stop_btn.setEnabled(False)
        self.send_btn.setEnabled(True)
        self._clear_card()
        self._save()
        self._mark_last()
        self._reload_list()
        self.refresh()
        self.busy_changed.emit(False)
        if self.state not in ("SPEAKING", "ERROR", "OFFLINE"):
            self.set_state("SUCCESS")
        if self.state != "ERROR":
            self._idle_timer.start(2500 if not (self.tts and self.tts.is_busy) else 6000)

    def start_mission(self, discipline: str, project: str, objective: str) -> bool:
        """Open a new conversation framed by a Forge discipline and send the mission."""
        from ...services import forge_missions as F

        if self.busy():
            self.add("System", "Stop the current request before starting a Forge mission.", T.WARN)
            return False
        if not self.core.router.configured:
            self.add("System", "No model provider is configured, so the mission was not started. Add a key in Settings → Providers, or start Ollama.", T.WARN)
            return False
        self._save()
        name = F.DISCIPLINES[discipline]["name"]
        self.conv = self.store.create([], title=f"{name} · {project}: {objective}"[:80])
        mission = F.MissionLog(self.core.paths()["data"]).start(discipline, project, objective, self.conv["id"])
        self.conv["mission"] = {"id": mission["id"], "discipline": discipline, "project": project}
        self.store.save(self.conv)
        self.messages = self.conv["messages"]
        self._reset_view()
        self._reload_list()
        text = F.prompt(discipline, project, objective)
        self.add("You", text)
        self.messages.append({"role": "user", "content": text})
        self._save()
        self._start()
        return True

    def new_conversation(self) -> None:
        if self.busy():
            self.add("System", "Stop the current request before starting a new conversation.", T.WARN)
            return
        self._save()
        if not self.visible(self.messages):
            # the open one is still empty: reuse it rather than piling up empty conversations
            self._reset_view()
        else:
            self.conv = self.store.create([])
            self.messages = self.conv["messages"]
            self._reset_view()
        self.g._save_session(self.messages)
        self._welcome()
        self._reload_list()
        self.refresh()
        self.input.setFocus()

    def _slash(self, cmd: str) -> None:
        name = cmd.split()[0].lower()
        if name in ("/new", "/clear"):
            self.new_conversation()
        elif name == "/help":
            self.add("System", "/new — start a new conversation · /orbit — plan this in ORBIT · /rename — rename this one · Esc — stop · Ctrl+K — search everything · Shift+Enter — new line", T.TEXT_SECONDARY)
        elif name == "/orbit":
            win = self.window()
            if hasattr(win, "plan_in_orbit"):
                win.plan_in_orbit(cmd[len(name):].strip())
        elif name == "/rename":
            title = cmd[len(name):].strip()
            if title:
                self.store.rename(self.conv["id"], title)
                self.conv = self.store.get(self.conv["id"]) or self.conv
                self.messages = self.conv["messages"]
                self._reload_list()
            else:
                self.rename_conversation(self.conv["id"])
        else:
            self.add("System", f"Unknown command {name}. Try /help.", T.WARN)

    # ----- voice -----
    def _mic_toggled(self, on: bool) -> None:
        if self.voice is None:
            return
        if on:
            if self.voice.start_recording():
                self.set_state("LISTENING")
            else:
                self.mic.setChecked(False)
        else:
            self.voice.stop_recording()
            self.set_state("THINKING")

    def _transcribed(self, text: str) -> None:
        # The transcript goes into the box for the operator to check; it is not sent automatically.
        if text.strip():
            self.input.setText(text.strip())
            self.input.setFocus()
        self.set_state("IDLE")

    def _audio_level(self, level: float) -> None:
        if self.orb is not None:
            self.orb.set_audio_level(level)
        if self.glyph is not None:
            self.glyph.set_audio_level(level)

    def shutdown(self) -> None:
        if self.busy():
            self.worker.request_stop()
            self.worker.wait(3000)
        if self.voice is not None:
            self.voice.stop_recording()
            self.voice.wait(1500)
        self._save()
