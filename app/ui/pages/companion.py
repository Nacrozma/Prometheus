"""Companion: the conversation, with the orb beside it.

Reuses the HUD's real pieces instead of re-implementing them: `PrometheusWorker` (streaming, the
tool loop, the conscience check, fallbacks), the safe Markdown renderer, session storage, the
speech pipeline and the OpenGL orb. Tool approvals are shown inline as cards with the exact tool
and arguments as plain text; the worker blocks until the operator answers.
"""

from __future__ import annotations

import json
import time
from typing import List, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PyQt6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLineEdit, QPlainTextEdit, QPushButton, QTextBrowser, QVBoxLayout, QWidget

from .. import theme as T
from ..widgets import Page, label

# Semantic states the orb shows, mapped onto the shader's four render modes (0 idle, 1 thinking,
# 2 speaking, 3 adapting) plus a labelled colour. The mapping is the only thing that is "made up":
# every state is set by a real event.
ORB_STATES = {
    "IDLE": (0, "Idle", T.TEXT_DIM),
    "LISTENING": (2, "Listening", T.INFO),
    "THINKING": (1, "Thinking", T.GOLD),
    "EXECUTING": (1, "Running a tool", T.AMBER),
    "SPEAKING": (2, "Speaking", T.GOLD),
    "SUCCESS": (0, "Done", T.OK),
    "WARNING": (0, "Needs you", T.WARN),
    "ERROR": (0, "Something went wrong", T.ERR),
    "ADAPTING": (3, "Adapting", T.AMBER),
}


class ApprovalCard(QFrame):
    """The exact tool and arguments, as plain text. Deny is the default."""

    answered = pyqtSignal(bool)

    def __init__(self, tool: str, args_json: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("approval")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.addWidget(label(f"Prometheus wants to run a tool with real-world effects: {tool}", "warn"))
        try:
            pretty = json.dumps(json.loads(args_json), indent=2, ensure_ascii=False)
        except Exception:
            pretty = args_json
        box = QPlainTextEdit(pretty)
        box.setReadOnly(True)
        box.setMaximumHeight(150)
        box.setAccessibleName("Tool arguments")
        lay.addWidget(box)
        row = QHBoxLayout()
        row.addWidget(label("Nothing runs until you choose. The call is checked again by the safety policy and recorded in the audit log.", "faint"), 1)
        deny = QPushButton("Deny")
        allow = QPushButton("Approve")
        allow.setObjectName("primary")
        deny.setDefault(True)
        deny.clicked.connect(lambda: self.answered.emit(False))
        allow.clicked.connect(lambda: self.answered.emit(True))
        row.addWidget(deny)
        row.addWidget(allow)
        lay.addLayout(row)


class CompanionPage(Page):
    title = "Companion"
    subtitle = "Talk to Prometheus. Tools with real-world effects always ask first."
    state_changed = pyqtSignal(str)
    busy_changed = pyqtSignal(bool)

    def __init__(self, core, settings, parent=None):
        super().__init__(core, parent)
        import gui_orb as g
        import gui_markdown as md
        from gui_config import AppConfig

        self.g, self.md = g, md
        self.settings = settings
        self.config = AppConfig()
        try:
            g.apply_router_settings(self.config)
        except Exception:
            pass
        self.messages: List[dict] = g._load_session()
        self.worker = None
        self.card: Optional[ApprovalCard] = None
        self.entries: List[str] = []
        self.code: dict = {}
        self.streaming: Optional[int] = None
        self.seq = 0
        self.state = "IDLE"
        self.spoke = False

        row = QHBoxLayout()
        row.setSpacing(16)
        left = QVBoxLayout()
        self.view = QTextBrowser()
        self.view.setOpenLinks(False)
        self.view.anchorClicked.connect(self._link)
        self.view.setAccessibleName("Conversation")
        left.addWidget(self.view, 1)
        self.card_slot = QVBoxLayout()
        left.addLayout(self.card_slot)
        inp = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Ask Prometheus anything… (Enter to send, / for commands)")
        self.input.setAccessibleName("Message")
        self.input.returnPressed.connect(self.send)
        self.mic = QPushButton("Talk")
        self.mic.setAccessibleName("Voice input")
        self.mic.setCheckable(True)
        self.mic.toggled.connect(self._mic_toggled)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop)
        self.send_btn = QPushButton("Send")
        self.send_btn.setObjectName("primary")
        self.send_btn.clicked.connect(self.send)
        for w in (self.input,):
            inp.addWidget(w, 1)
        for w in (self.mic, self.stop_btn, self.send_btn):
            inp.addWidget(w)
        left.addLayout(inp)
        row.addLayout(left, 3)

        right = QVBoxLayout()
        right.setSpacing(8)
        self.orb = None
        try:
            self.orb = g.SolarSunWidget()
            self.orb.setMinimumSize(240, 240)
            self.orb.setAccessibleName("Prometheus orb")
            right.addWidget(self.orb, 0, Qt.AlignmentFlag.AlignHCenter)
        except Exception as e:  # no OpenGL: the page still works
            right.addWidget(label(f"The orb needs OpenGL 3.3, which is not available here ({type(e).__name__}).", "faint"))
        self.state_lbl = label("Idle")
        self.state_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        right.addWidget(self.state_lbl)
        self.route_lbl = label("", "faint")
        right.addWidget(self.route_lbl)
        self.voice_lbl = label("", "faint")
        right.addWidget(self.voice_lbl)
        new = QPushButton("New conversation")
        new.clicked.connect(self.new_conversation)
        right.addWidget(new)
        right.addStretch(1)
        row.addLayout(right, 1)
        self.content.addLayout(row, 1)

        # Speech: the existing pipeline, used only where its packages are installed.
        self.tts = None
        if g.VOICE_OUTPUT_AVAILABLE:
            try:
                self.tts = g.TTSManager(voice=self.config.get("voice"), audio_callback=self._audio_level, rate_percent=self.config.get("speech_rate", 0))
                self.tts.set_muted(not self.config.get("speech_enabled", True))
            except Exception:
                self.tts = None
        self.voice = g.WhisperVoiceThread() if g.VOICE_INPUT_AVAILABLE else None
        if self.voice is not None:
            self.voice.transcription_done.connect(self._transcribed)
            self.voice.status_signal.connect(lambda s: self.state_lbl.setText(s.capitalize()))
            self.voice.audio_level_signal.connect(self._audio_level)
            self.voice.finished.connect(lambda: self.mic.setChecked(False))
        self.mic.setEnabled(self.voice is not None)
        if self.voice is None:
            self.mic.setToolTip("Voice input needs openai-whisper (pip install openai-whisper). See Settings → Voice.")
        self.voice_lbl.setText(self._voice_text())

        QShortcut(QKeySequence("Escape"), self, activated=self.stop)
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(lambda: self.set_state("IDLE"))
        self._render_history()
        self.refresh()

    # ----- display -----
    def _voice_text(self) -> str:
        parts = ["Voice input: " + ("ready" if self.voice else "not installed"), "Speech: " + ("ready" if self.tts else "not available")]
        return " · ".join(parts)

    def refresh(self) -> None:
        r = self.core.router
        used = r.last_used_provider or r.provider
        model = r.last_used_model or r.default_model
        self.route_lbl.setText(f"Provider: {used} · {model}" if used and used != "none" else "No provider configured: add a key in Settings → Providers.")

    def set_state(self, state: str) -> None:
        mode, text, colour = ORB_STATES.get(state, ORB_STATES["IDLE"])
        self.state = state
        if self.orb is not None:
            self.orb.state = mode
            self.orb.update()
        self.state_lbl.setText(text)
        self.state_lbl.setStyleSheet(f"color: {colour}; font-weight: 600;")
        self.state_changed.emit(state)

    def set_reduced_motion(self, reduced: bool) -> None:
        """Reduced motion: a still orb that is redrawn when the state changes."""
        if self.orb is None:
            return
        if reduced:
            self.orb.timer.stop()
            self.orb.update()
        elif not self.orb.timer.isActive():
            self.orb._last_tick = time.perf_counter()
            self.orb.timer.start(16)

    def pause_animation(self, paused: bool) -> None:
        """Stop drawing the orb while the window is hidden or minimised."""
        if self.orb is None:
            return
        if paused:
            self.orb.timer.stop()
        elif not self.settings.get("reduced_motion"):
            self.orb._last_tick = time.perf_counter()
            self.orb.timer.start(16)

    def _entry(self, who: str, body_html: str, colour: str) -> str:
        stamp = time.strftime("%H:%M")
        return f'<div style="margin-bottom:10px;"><span style="color:{T.TEXT_FAINT}; font-size:8pt;">{stamp}</span> <b style="color:{colour};">{who}</b><div style="margin:2px 0 0 2px;">{body_html}</div></div>'

    def _md(self, text: str) -> str:
        self.seq += 1
        return self.md.render_markdown(text, self.g.MD_THEME, self.code, id_prefix=f"m{self.seq}")

    def add(self, who: str, text: str, colour: str = T.TEXT, markdown: bool = False) -> None:
        body = self._md(text) if markdown else self.md.esc(text).replace("\n", "<br/>")
        self.entries.append(self._entry(who, body, colour))
        self._render()

    def _render(self) -> None:
        bar = self.view.verticalScrollBar()
        at_end = bar.value() >= bar.maximum() - 30
        self.view.setHtml("".join(self.entries[-300:]))
        if at_end:
            bar.setValue(bar.maximum())

    def _render_history(self) -> None:
        shown = [m for m in self.messages if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str) and m.get("content").strip()]
        for m in shown[-40:]:
            if m["role"] == "user":
                self.add("You", m["content"], T.TEXT)
            else:
                self.add("Prometheus", m["content"], T.GOLD, markdown=True)
        if not shown:
            self.add("Prometheus", "Ready. Ask me to research, calculate, plan, build or remember something.", T.GOLD)

    def _link(self, url) -> None:
        href = url.toString()
        if href.startswith(self.md.COPY_PREFIX):
            code = self.code.get(href[len(self.md.COPY_PREFIX):])
            if code is not None:
                QApplication.clipboard().setText(code)
                self.state_lbl.setText("Code copied")
        elif href.startswith(("http://", "https://")):
            QDesktopServices.openUrl(url)

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
        self.input.clear()
        self.add("You", text)
        self.messages.append({"role": "user", "content": text})
        self.spoke = False
        w = self.g.PrometheusWorker(self.core.router, self.messages, auto_approve=self.settings.get("auto_approve"), fallback_models=self.config.get("fallback_models"))
        w.state_changed.connect(lambda s: self.set_state("THINKING" if s == "THINKING" else s))
        w.status_updated.connect(lambda t, c: self.state_lbl.setText(t))
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

    def _delta(self, raw: str) -> None:
        entry = self._entry("Prometheus", self._md(raw), T.GOLD)
        if self.streaming is None:
            self.entries.append(entry)
            self.streaming = len(self.entries) - 1
        else:
            self.entries[self.streaming] = entry
        self._render()

    def _response(self, text: str) -> None:
        self._delta(text)
        self.streaming = None
        if self.tts and not self.spoke and text.strip():
            self.tts.speak(self.md.clean_for_speech(text))
            self.set_state("SPEAKING")

    def _speak_sentence(self, sentence: str) -> None:
        if self.tts:
            self.spoke = True
            self.tts.speak(sentence)
            self.set_state("SPEAKING")

    def _tool_done(self, tool: str, args: str, result: str) -> None:
        self.set_state("EXECUTING")
        try:
            status = json.loads(result).get("status", "")
        except Exception:
            status = ""
        colour = T.OK if status == "success" else T.WARN if status in ("refused", "denied", "cancelled") else T.ERR if status == "error" else T.TEXT_DIM
        self.add("Tool", f"{tool} → {status or 'done'}", colour)

    def _confirm(self, tool: str, args_json: str) -> None:
        self.set_state("WARNING")
        self._clear_card()
        self.card = ApprovalCard(tool, args_json)
        self.card.answered.connect(lambda ok, t=tool: self._answer(t, ok))
        self.card_slot.addWidget(self.card)
        self.window().activateWindow()

    def _answer(self, tool: str, approved: bool) -> None:
        self._clear_card()
        if self.worker is not None:
            self.worker.provide_confirmation(approved)
        self.add("System", f"You {'approved' if approved else 'denied'} {tool}.", T.OK if approved else T.ERR)
        self.set_state("EXECUTING" if approved else "THINKING")

    def _clear_card(self) -> None:
        if self.card is not None:
            self.card.setParent(None)
            self.card.deleteLater()
            self.card = None

    def stop(self) -> None:
        if self.tts:
            try:
                self.tts.set_muted(True)
                self.tts.set_muted(False)
            except Exception:
                pass
        if self.busy():
            if self.card is not None:
                self._answer("the pending tool", False)
            self.worker.request_stop()
            self.add("System", "Stopping.", T.WARN)

    def _finished(self) -> None:
        self.stop_btn.setEnabled(False)
        self.send_btn.setEnabled(True)
        self._clear_card()
        self.g.trim_messages(self.messages, self.g.MAX_SESSION_MESSAGES)
        self.g._save_session(self.messages)
        self.refresh()
        self.busy_changed.emit(False)
        if self.state not in ("SPEAKING", "ERROR"):
            self.set_state("SUCCESS")
        self._idle_timer.start(2500 if not (self.tts and self.tts.is_busy) else 6000)

    def new_conversation(self) -> None:
        if self.busy():
            self.add("System", "Stop the current request before starting a new conversation.", T.WARN)
            return
        self.messages.clear()
        self.g._save_session(self.messages)
        self.entries.clear()
        self.code.clear()
        self.add("Prometheus", "New conversation. What shall we work on?", T.GOLD)

    def _slash(self, cmd: str) -> None:
        name = cmd.split()[0].lower()
        if name in ("/new", "/clear"):
            self.new_conversation()
        elif name == "/help":
            self.add("System", "/new — start a new conversation · Esc — stop · Other sections are in the sidebar (Ctrl+K to jump).", T.TEXT_DIM)
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

    def shutdown(self) -> None:
        if self.busy():
            self.worker.request_stop()
            self.worker.wait(3000)
        if self.voice is not None:
            self.voice.stop_recording()
            self.voice.wait(1500)
        self.g._save_session(self.messages)
