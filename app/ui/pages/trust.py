"""Trust & safety: what is allowed, what asks, what is denied; where data goes; the audit log and its
integrity; what can be undone. Read from the core's own policy and logs: this page cannot loosen anything.
The one action here, Undo, restores the last file a workspace tool changed and is itself audited."""

from __future__ import annotations

import json
import os

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QHeaderView, QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QTextBrowser, QVBoxLayout, QWidget

from .. import icons
from .. import theme as T
from ..widgets import Page, label, stat_tile, tidy_table

LIMITS = (
    "Limits, stated plainly: the destructive-command filter is not a sandbox; skills without Docker are resource-limited only; "
    "the patch gate is not proof a patch is safe; undo restores files the workspace tools changed, not other effects of shell commands; "
    "the audit hash chain detects edits but cannot stop someone with full file access replacing the whole log."
)
OUTCOME_TONE = {"success": T.OK, "error": T.ERR, "execution_error": T.ERR, "refused": T.WARN, "declined": T.WARN, "denied": T.WARN, "cancelled": T.TEXT_SECONDARY}
FILTERS = [("All activity", None), ("Problems", {"error", "execution_error", "refused", "declined", "denied"}), ("Changes (writes, runs, memory)", "changes")]
CHANGE_TOOLS = {"write_file", "edit_file", "execute_shell", "run_code_forge", "apply_pending_patch", "sculpt_workspace", "synthesize_dynamic_tool", "export_obsidian", "ghost_control", "update_memory", "update_task_state", "schedule_task", "cancel_scheduled", "rollback_skill"}
LOCAL_PROVIDERS = {"ollama"}


class TrustPage(Page):
    title = "Trust & safety"
    subtitle = "Every tool call is checked by the core's policy and recorded in a hash-chained audit log. This page shows the rules, where your data goes, and what happened."
    scroll = True

    def __init__(self, core, settings, parent=None):
        super().__init__(core, parent)
        self.settings = settings
        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        self.t_auto = stat_tile("—", "approval for real-world tools")
        self.t_gated = stat_tile("—", "tools that ask first")
        self.t_denied = stat_tile("—", "tools denied by your rules")
        self.t_chain = stat_tile("—", "audit chain")
        for t in (self.t_auto, self.t_gated, self.t_denied, self.t_chain):
            tiles.addWidget(t)
        self.content.addLayout(tiles)

        tabs = QTabWidget()
        tabs.setMinimumHeight(520)
        # activity
        aw = QWidget()
        al = QVBoxLayout(aw)
        row = QHBoxLayout()
        self.filter = QComboBox()
        self.filter.setAccessibleName("Activity filter")
        for name, _ in FILTERS:
            self.filter.addItem(name)
        self.filter.currentIndexChanged.connect(lambda _: self._fill_audit())
        row.addWidget(self.filter)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by tool name…")
        self.search.setAccessibleName("Filter by tool")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _: self._fill_audit())
        row.addWidget(self.search, 1)
        verify = QPushButton(icons.icon("shield", T.TEXT_SECONDARY), " Verify the chain")
        verify.clicked.connect(self._verify)
        row.addWidget(verify)
        al.addLayout(row)
        self.chain = label("")
        al.addWidget(self.chain)
        self.audit = QTableWidget(0, 5)
        tidy_table(self.audit, 4)
        self.audit.setHorizontalHeaderLabels(["Time", "Tool", "Outcome", "Duration", "Arguments (redacted)"])
        self.audit.setAccessibleName("Audit log")
        al.addWidget(self.audit, 1)
        tabs.addTab(aw, "Activity")
        # data
        self.data = QTextBrowser()
        self.data.setAccessibleName("Where your data goes")
        tabs.addTab(self.data, "Where data goes")
        # permissions
        pw = QWidget()
        pl = QVBoxLayout(pw)
        self.perm = QTableWidget(0, 2)
        tidy_table(self.perm, 1)
        self.perm.setHorizontalHeaderLabels(["Tool", "Rule"])
        pl.addWidget(self.perm, 1)
        self.scopes = label("", "faint")
        pl.addWidget(self.scopes)
        pl.addWidget(label("Rules come from permissions.json in the data folder (stricter-only: it can deny or require confirmation, never relax the built-in checks). Forge missions add their own boundary on top (Architect read-only, Reconstructor new files only).", "faint"))
        tabs.addTab(pw, "Permissions")
        # undo
        uw = QWidget()
        ul = QVBoxLayout(uw)
        self.undo = QTableWidget(0, 3)
        tidy_table(self.undo, 1)
        self.undo.setHorizontalHeaderLabels(["When", "File", "Kind"])
        ul.addWidget(self.undo, 1)
        urow = QHBoxLayout()
        urow.addWidget(label("Undo restores the file a workspace tool changed most recently (one step at a time). It does not reverse shell commands or other effects.", "faint"), 1)
        self.undo_btn = QPushButton(icons.icon("retry", T.TEXT_SECONDARY), " Undo the last file change")
        self.undo_btn.clicked.connect(self._undo)
        urow.addWidget(self.undo_btn)
        ul.addLayout(urow)
        self.undo_msg = label("", "faint")
        ul.addWidget(self.undo_msg)
        tabs.addTab(uw, "Undo")
        self.content.addWidget(tabs, 1)
        self.content.addWidget(label(LIMITS, "faint"))
        self.entries = []

    def refresh(self) -> None:
        pol = self.core.policy()
        auto = bool(self.settings.get("auto_approve"))
        self.t_auto.value_label.setText("OFF" if auto else "ON")
        self.t_auto.value_label.setStyleSheet(f"color: {T.ERR if auto else T.OK};")
        deny = getattr(pol, "deny", {}) or {}
        confirm = set(getattr(pol, "ask", set()) or set())
        tools = sorted(self.core.tool_names())
        gated = [t for t in tools if t not in deny and (self.core.is_dangerous(t) or t in confirm)]
        self.t_gated.value_label.setText(str(len(gated)))
        self.t_denied.value_label.setText(str(len([t for t in tools if t in deny])))
        self.perm.setRowCount(0)
        for tool in tools:
            if tool in deny:
                rule, tone = f"Denied: {deny[tool]}", T.ERR
            elif tool in gated:
                rule, tone = "Asks first" + (" (auto-approve is ON: runs without asking)" if auto else ""), T.WARN if auto else T.ACCENT
            else:
                rule, tone = "Allowed (read-only or low-risk)", T.TEXT_SECONDARY
            r = self.perm.rowCount()
            self.perm.insertRow(r)
            self.perm.setItem(r, 0, QTableWidgetItem(tool))
            it = QTableWidgetItem(rule)
            it.setForeground(QColor(tone))
            self.perm.setItem(r, 1, it)
        scopes = getattr(pol, "write_scopes", None)
        self.scopes.setText(f"Write scopes inside the workspace: {', '.join(scopes)}" if scopes else "Write scopes: the whole workspace (no narrower scope set).")
        self.entries = list(reversed(self.core.audit_tail(500)))
        self._fill_audit()
        self._fill_data()
        self.undo.setRowCount(0)
        undo = self.core.undo_entries(30)
        for u in undo:
            r = self.undo.rowCount()
            self.undo.insertRow(r)
            for c, key in enumerate(("ts", "path", "kind")):
                self.undo.setItem(r, c, QTableWidgetItem(str(u.get(key, u.get("time", "")) if key == "ts" else u.get(key, ""))))
        self.undo_btn.setEnabled(bool(undo))
        self._verify()

    def _fill_audit(self) -> None:
        f = FILTERS[self.filter.currentIndex()][1]
        q = self.search.text().strip().lower()
        self.audit.setRowCount(0)
        for e in self.entries:
            tool, outcome = str(e.get("tool", "")), str(e.get("outcome", ""))
            if f == "changes" and tool not in CHANGE_TOOLS and not tool.startswith("desktop."):
                continue
            if isinstance(f, set) and outcome not in f:
                continue
            if q and q not in tool.lower():
                continue
            r = self.audit.rowCount()
            self.audit.insertRow(r)
            ms = e.get("ms", None)
            dur = f"{float(ms) / 1000:.2f} s" if isinstance(ms, (int, float)) and ms else "—"
            cells = [str(e.get("ts", "")).replace("T", " "), tool, outcome, dur, json.dumps(e.get("args", ""), ensure_ascii=False)[:400]]
            for c, v in enumerate(cells):
                it = QTableWidgetItem(v)
                if c == 2:
                    it.setForeground(QColor(OUTCOME_TONE.get(outcome, T.TEXT_SECONDARY)))
                self.audit.setItem(r, c, it)

    def _fill_data(self) -> None:
        st = self.core.router_status()
        active = st.get("active_providers") or []
        rows = []
        for p in active:
            where = "this computer (Ollama)" if p in LOCAL_PROVIDERS else f"{p}'s servers (cloud)"
            rows.append((f"Your messages, the conversation history Prometheus keeps, relevant memory facts and tool results → model provider <b>{p}</b>", where, T.OK if p in LOCAL_PROVIDERS else T.WARN))
        if not active:
            rows.append(("No model provider is configured: nothing is sent anywhere.", "—", T.TEXT_SECONDARY))
        import gui_orb as g

        rows.append(("Speech output: the text being spoken → Microsoft's edge-tts service", "cloud, only while speech is on" if g.VOICE_OUTPUT_AVAILABLE else "not installed", T.WARN if g.VOICE_OUTPUT_AVAILABLE else T.TEXT_SECONDARY))
        rows.append(("Voice input: your recording → Whisper", "this computer, never saved" if g.VOICE_INPUT_AVAILABLE else "not installed", T.OK if g.VOICE_INPUT_AVAILABLE else T.TEXT_SECONDARY))
        rows.append(("Web search: the search query → Tavily (api.tavily.com)", "cloud, only when the web_search tool runs" if os.getenv("TAVILY_API_KEY") else "off (no TAVILY_API_KEY)", T.WARN if os.getenv("TAVILY_API_KEY") else T.TEXT_SECONDARY))
        rows.append(("Memory, conversations, reminders, the audit log, Forge missions", f"this computer only ({self.core.paths()['data']})", T.OK))
        rows.append(("API keys", "your operating system's credential store; never in settings files or logs", T.OK))
        html = "<table cellpadding='6'>" + "".join(f"<tr><td style='padding-right:18px;'>{a}</td><td style='color:{tone};'>{b}</td></tr>" for a, b, tone in rows) + "</table>"
        html += f"<p style='color:{T.TEXT_FAINT};'>From the configuration Prometheus is running with now. Prometheus does not send telemetry.</p>"
        self.data.setHtml(html)

    def _verify(self) -> None:
        ok, msg = self.core.audit_verify()
        self.chain.setText(("Audit chain intact: " if ok else "Audit chain BROKEN: ") + msg)
        self.chain.setStyleSheet(f"color: {T.OK if ok else T.ERR}; font-weight: 600;")
        self.t_chain.value_label.setText("intact" if ok else "BROKEN")
        self.t_chain.value_label.setStyleSheet(f"color: {T.OK if ok else T.ERR};")

    def _undo(self) -> None:
        if QMessageBox.question(self, "Undo the last file change?", "The most recent file a workspace tool wrote or edited is put back as it was before. Continue?", QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
            return
        res = self.core.p.undo_journal.undo()
        self.core.p.audit_log.record("desktop.undo", {"path": res.get("path", "")}, res.get("status", "error"), "owner action in the desktop app")
        self.undo_msg.setText(res.get("message") or (f"Restored {res.get('path', '')}." if res.get("status") == "success" else str(res)))
        self.refresh()
