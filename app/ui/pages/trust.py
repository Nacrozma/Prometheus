"""Trust & safety: transparent oversight.

A posture statement first, in words, from the real configuration and the audit log. Then four views
(segmented control): **Timeline** (audit events grouped by day, filter by kind, an inspector with the
redacted arguments of the selected event), **Where data goes** (source → destination, local or cloud),
**Permissions** (grouped: asks first, allowed, denied), **Undo** (restore the last file a workspace tool
changed; confirmed and audited). The page reads the core's own policy and logs: it cannot loosen anything.
"""

from __future__ import annotations

import json
import os

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QButtonGroup, QComboBox, QFrame, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget

from .. import icons
from .. import theme as T
from ..feedback import notify
from ..widgets import Page, label, tidy_table

LIMITS = (
    "Limits, stated plainly: the destructive-command filter is not a sandbox; skills without Docker are resource-limited only; "
    "the patch gate is not proof a patch is safe; undo restores files the workspace tools changed, not other effects of shell commands; "
    "the audit hash chain detects edits but cannot stop someone with full file access replacing the whole log."
)
FILTERS = [("Everything", None), ("Problems", {"error", "execution_error", "refused", "declined", "denied"}), ("Changes", "changes"), ("Your own actions", "desktop")]
CHANGE_TOOLS = {"write_file", "edit_file", "execute_shell", "run_code_forge", "apply_pending_patch", "sculpt_workspace", "synthesize_dynamic_tool", "export_obsidian", "ghost_control", "update_memory", "update_task_state", "schedule_task", "cancel_scheduled", "rollback_skill"}
OUTCOME = {"success": ("check", T.OK, "succeeded"), "error": ("alert", T.ERR, "failed"), "execution_error": ("alert", T.ERR, "failed"), "refused": ("shield", T.WARN, "refused"), "declined": ("shield", T.WARN, "declined by you"), "denied": ("shield", T.WARN, "denied"), "cancelled": ("stop", T.TEXT_SECONDARY, "cancelled")}
LOCAL_PROVIDERS = {"ollama"}


class TrustPage(Page):
    title = "Trust & safety"
    header = "none"
    margins = (0, 0, 0, 0)

    def __init__(self, core, settings, parent=None):
        super().__init__(core, parent)
        self.settings = settings
        self.entries = []
        outer = QWidget()
        ol = QVBoxLayout(outer)
        ol.setContentsMargins(36, 26, 36, 14)
        ol.setSpacing(10)
        ol.addWidget(label("TRUST & SAFETY", "eyebrow"))
        self.posture = label("", "h1")
        self.posture.setStyleSheet(f"font-size: 16pt; font-family: {T.FONT_DISPLAY};")
        self.posture.setMaximumWidth(1000)
        ol.addWidget(self.posture)
        self.posture2 = label("", "sub")
        self.posture2.setMaximumWidth(1000)
        ol.addWidget(self.posture2)
        seg = QHBoxLayout()
        seg.setSpacing(6)
        self.seg = QButtonGroup(self)
        for i, name in enumerate(("Timeline", "Where data goes", "Permissions", "Undo")):
            b = QPushButton(name)
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setChecked(i == 0)
            self.seg.addButton(b, i)
            seg.addWidget(b)
        seg.addStretch(1)
        self.verify_btn = QPushButton(icons.icon("shield", T.TEXT_SECONDARY), " Verify the audit chain")
        self.verify_btn.setObjectName("ghost")
        self.verify_btn.clicked.connect(lambda: self._verify(announce=True))
        seg.addWidget(self.verify_btn)
        ol.addLayout(seg)
        self.stack = QStackedWidget()
        self.seg.idClicked.connect(self.stack.setCurrentIndex)
        self.stack.addWidget(self._timeline())
        self.data = QTextBrowser()
        self.data.setAccessibleName("Where your data goes")
        self.stack.addWidget(self.data)
        self.stack.addWidget(self._permissions())
        self.stack.addWidget(self._undo())
        ol.addWidget(self.stack, 1)
        ol.addWidget(label(LIMITS, "faint"))
        self.content.addWidget(outer, 1)

    # ----- views -----
    def _timeline(self) -> QWidget:
        split = QSplitter()
        split.setHandleWidth(1)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 6, 10, 0)
        row = QHBoxLayout()
        self.filter = QComboBox()
        self.filter.setAccessibleName("Show")
        for name, _ in FILTERS:
            self.filter.addItem(name)
        self.filter.currentIndexChanged.connect(lambda _: self._fill_timeline())
        row.addWidget(self.filter)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by tool…")
        self.search.setAccessibleName("Filter by tool")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _: self._fill_timeline())
        row.addWidget(self.search, 1)
        ll.addLayout(row)
        self.timeline = QListWidget()
        self.timeline.setObjectName("rail")
        self.timeline.setIconSize(QSize(16, 16))
        self.timeline.setAccessibleName("Activity timeline")
        self.timeline.currentItemChanged.connect(lambda it, _p: self._inspect(it))
        ll.addWidget(self.timeline, 1)
        split.addWidget(left)
        ins = QFrame()
        ins.setObjectName("inspector")
        il = QVBoxLayout(ins)
        il.setContentsMargins(16, 12, 16, 12)
        il.addWidget(label("EVENT", "eyebrow"))
        self.ev_title = label("Select an event to see its details.", "h2")
        il.addWidget(self.ev_title)
        self.ev_meta = label("", "faint")
        il.addWidget(self.ev_meta)
        self.ev_args = QTextBrowser()
        self.ev_args.setAccessibleName("Event arguments (redacted)")
        il.addWidget(self.ev_args, 1)
        split.addWidget(ins)
        split.setSizes([680, 380])
        return split

    def _permissions(self) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(24)
        self.perm_cols = {}
        for key, title, tone in (("ask", "Asks you first", T.ACCENT), ("allow", "Allowed (read-only or low-risk)", T.TEXT_SECONDARY), ("deny", "Denied by your rules", T.ERR)):
            col = QVBoxLayout()
            h = label(title.upper(), "eyebrow")
            h.setStyleSheet(f"color: {tone};")
            col.addWidget(h)
            lst = QListWidget()
            lst.setObjectName("rail")
            lst.setAccessibleName(title)
            col.addWidget(lst, 1)
            self.perm_cols[key] = lst
            lay.addLayout(col, 1)
        self.scopes = label("", "faint")
        side = QVBoxLayout()
        side.addWidget(label("HOW RULES WORK", "eyebrow"))
        side.addWidget(label("Rules come from permissions.json in the data folder. They can only make things stricter: deny a tool or require confirmation, never relax the built-in checks. Forge missions add their own boundary on top (Architect read-only, Reconstructor new files only). Auto-approve is a Settings switch with a warning, and is off during Forge missions.", "sub"))
        side.addWidget(self.scopes)
        side.addStretch(1)
        lay.addLayout(side, 1)
        return w

    def _undo(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.addWidget(label("Undo restores the file a workspace tool changed most recently, one step at a time. It does not reverse shell commands or other effects.", "sub"))
        self.undo = QTableWidget(0, 3)
        tidy_table(self.undo, 1)
        self.undo.setHorizontalHeaderLabels(["When", "File", "Kind"])
        self.undo.setAccessibleName("Undo journal")
        lay.addWidget(self.undo, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.undo_btn = QPushButton(icons.icon("retry", T.TEXT_SECONDARY), " Undo the last file change")
        self.undo_btn.clicked.connect(self._do_undo)
        row.addWidget(self.undo_btn)
        lay.addLayout(row)
        return w

    # ----- data -----
    def refresh(self) -> None:
        pol = self.core.policy()
        auto = bool(self.settings.get("auto_approve"))
        deny = getattr(pol, "deny", {}) or {}
        confirm = set(getattr(pol, "ask", set()) or set())
        tools = sorted(self.core.tool_names())
        gated = [t for t in tools if t not in deny and (self.core.is_dangerous(t) or t in confirm)]
        for lst in self.perm_cols.values():
            lst.clear()
        for t in tools:
            key = "deny" if t in deny else "ask" if t in gated else "allow"
            it = QListWidgetItem(f"{t}" + (f" — {deny[t]}" if key == "deny" else "  (auto-approve is ON)" if key == "ask" and auto else ""))
            self.perm_cols[key].addItem(it)
        scopes = getattr(pol, "write_scopes", None)
        self.scopes.setText(f"Write scopes inside the workspace: {', '.join(scopes)}" if scopes else "Write scopes: the whole workspace (no narrower scope set).")
        self.entries = list(reversed(self.core.audit_tail(500)))
        ok, msg = self.core.audit_verify()
        problems = [e for e in self.entries[:200] if str(e.get("outcome")) in ("error", "execution_error")]
        if auto:
            self.posture.setText("Auto-approve is ON: tools with real-world effects run without asking you.")
            self.posture.setStyleSheet(f"font-size: 16pt; font-family: {T.FONT_DISPLAY}; color: {T.ERR};")
        else:
            self.posture.setText(f"Prometheus asks before anything with real-world effects. {len(gated)} tools need your approval.")
            self.posture.setStyleSheet(f"font-size: 16pt; font-family: {T.FONT_DISPLAY};")
        self.posture2.setText(("✓ The audit log is intact" if ok else "⚠ The audit log does NOT verify") + f" ({len(self.entries)} recent events). " + (f"{len(problems)} recent tool call{'s' if len(problems) != 1 else ''} failed — see Problems." if problems else "No recent failures.") + (f" {len(deny)} tools are denied by your rules." if deny else ""))
        self._fill_timeline()
        self._fill_data()
        self.undo.setRowCount(0)
        undo = self.core.undo_entries(30)
        for u in undo:
            r = self.undo.rowCount()
            self.undo.insertRow(r)
            for c, key in enumerate(("ts", "path", "kind")):
                self.undo.setItem(r, c, QTableWidgetItem(str(u.get(key, u.get("time", "")) if key == "ts" else u.get(key, ""))))
        self.undo_btn.setEnabled(bool(undo))

    def _fill_timeline(self) -> None:
        f = FILTERS[self.filter.currentIndex()][1]
        q = self.search.text().strip().lower()
        self.timeline.clear()
        day = None
        shown = 0
        for e in self.entries:
            tool, outcome = str(e.get("tool", "")), str(e.get("outcome", ""))
            if f == "changes" and tool not in CHANGE_TOOLS and not tool.startswith("desktop."):
                continue
            if f == "desktop" and not tool.startswith("desktop."):
                continue
            if isinstance(f, set) and outcome not in f:
                continue
            if q and q not in tool.lower():
                continue
            d = str(e.get("ts", ""))[:10]
            if d != day:
                h = QListWidgetItem(d)
                h.setFlags(Qt.ItemFlag.NoItemFlags)
                font = h.font()
                font.setBold(True)
                h.setFont(font)
                h.setForeground(QColor(T.TEXT_FAINT))
                self.timeline.addItem(h)
                day = d
            ic, colour, word = OUTCOME.get(outcome, ("bolt", T.TEXT_SECONDARY, outcome or "recorded"))
            who = "You" if tool.startswith("desktop.") else "Prometheus"
            it = QListWidgetItem(icons.icon(ic, colour), f"{str(e.get('ts', ''))[11:16]}   {who}: {tool.removeprefix('desktop.').replace('_', ' ')} — {word}")
            it.setData(Qt.ItemDataRole.UserRole, e)
            self.timeline.addItem(it)
            shown += 1
        if not shown:
            it = QListWidgetItem("Nothing matches." if (f or q) else "No activity yet. Every tool call will be recorded here.")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.timeline.addItem(it)

    def _inspect(self, it) -> None:
        e = it.data(Qt.ItemDataRole.UserRole) if it else None
        if not e:
            return
        ic, colour, word = OUTCOME.get(str(e.get("outcome", "")), ("bolt", T.TEXT_SECONDARY, str(e.get("outcome", ""))))
        self.ev_title.setText(f"{e.get('tool', '')} — {word}")
        ms = e.get("ms")
        self.ev_meta.setText(f"{str(e.get('ts', '')).replace('T', ' ')} · entry #{e.get('seq', '')}" + (f" · took {float(ms) / 1000:.2f} s" if isinstance(ms, (int, float)) and ms else "") + (f"\n{e.get('detail')}" if e.get("detail") else ""))
        import gui_markdown as md

        self.ev_args.setHtml(f"<p style='color:{T.TEXT_FAINT};'>Arguments (secrets redacted before they were written):</p><pre style='white-space:pre-wrap; font-family:monospace;'>{md.esc(json.dumps(e.get('args', {}), indent=2, ensure_ascii=False)[:4000])}</pre>")

    def _fill_data(self) -> None:
        st = self.core.router_status()
        active = st.get("active_providers") or []
        import gui_orb as g

        rows = []
        for p in active:
            local = p in LOCAL_PROVIDERS
            rows.append(("Your messages, recent conversation, relevant memories, tool results", f"model provider {p}", "this computer" if local else "cloud", T.OK if local else T.WARN))
        if not active:
            rows.append(("Nothing", "no model provider is configured", "—", T.TEXT_SECONDARY))
        rows.append(("Text being spoken", "Microsoft edge-tts", "cloud, only while speech is on" if g.VOICE_OUTPUT_AVAILABLE else "not installed", T.WARN if g.VOICE_OUTPUT_AVAILABLE else T.TEXT_SECONDARY))
        rows.append(("Your voice recording", "Whisper", "this computer, never saved" if g.VOICE_INPUT_AVAILABLE else "not installed", T.OK if g.VOICE_INPUT_AVAILABLE else T.TEXT_SECONDARY))
        rows.append(("Web search queries", "Tavily (api.tavily.com)", "cloud, only when web_search runs" if os.getenv("TAVILY_API_KEY") else "off (no key)", T.WARN if os.getenv("TAVILY_API_KEY") else T.TEXT_SECONDARY))
        rows.append(("Memory, conversations, reminders, audit log, missions", "the data folder", "this computer only", T.OK))
        rows.append(("API keys", "your operating system's credential store", "never in settings files or logs", T.OK))
        html = "<table cellpadding='8'>" + "".join(f"<tr><td style='color:{T.TEXT};'>{a}</td><td style='color:{T.ACCENT};'>→</td><td>{b}</td><td style='color:{tone};'>{c}</td></tr>" for a, b, c, tone in rows) + "</table>"
        html += f"<p style='color:{T.TEXT_FAINT};'>From the configuration Prometheus is running with now. Prometheus sends no telemetry.</p>"
        self.data.setHtml(html)

    def _verify(self, announce: bool = False) -> None:
        ok, msg = self.core.audit_verify()
        if announce:
            notify(self, "Audit chain intact" if ok else "Audit chain BROKEN", "ok" if ok else "err", msg)

    def _do_undo(self) -> None:
        if QMessageBox.question(self, "Undo the last file change?", "The most recent file a workspace tool wrote or edited is put back as it was before. Continue?", QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.Cancel) != QMessageBox.StandardButton.Yes:
            return
        res = self.core.p.undo_journal.undo()
        self.core.p.audit_log.record("desktop.undo", {"path": res.get("path", "")}, res.get("status", "error"), "owner action in the desktop app")
        ok = res.get("status") == "success"
        notify(self, "File restored" if ok else "Nothing was undone", "ok" if ok else "warn", res.get("path", "") if ok else res.get("message", ""))
        self.refresh()
