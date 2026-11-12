"""Trust & permissions: what is allowed, what asks, what is denied; the audit log and its integrity;
what can be undone. Read from the core's own policy and logs: this page cannot loosen anything."""

from __future__ import annotations

import json

from PyQt6.QtWidgets import QAbstractItemView, QHBoxLayout, QHeaderView, QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget

from .. import theme as T
from ..widgets import Card, Page, label, tidy_table

LIMITS = (
    "Limits, stated plainly: the destructive-command filter is not a sandbox; skills without Docker are resource-limited only; "
    "the patch gate is not proof a patch is safe; undo restores files the workspace tools changed, not other effects of shell commands; "
    "the audit hash chain detects edits but cannot stop someone with full file access replacing the whole log."
)


class TrustPage(Page):
    title = "Trust & permissions"
    subtitle = "Every tool call is checked by the core's policy and recorded in a hash-chained audit log."

    def __init__(self, core, settings, parent=None):
        super().__init__(core, parent)
        self.settings = settings
        self.summary = label("", "sub")
        self.content.addWidget(self.summary)
        tabs = QTabWidget()
        # permissions
        pw = QWidget()
        pl = QVBoxLayout(pw)
        self.perm = QTableWidget(0, 2)
        tidy_table(self.perm, -1)
        self.perm.setHorizontalHeaderLabels(["Tool", "Rule"])
        self.perm.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.perm.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        pl.addWidget(self.perm, 1)
        self.scopes = label("", "faint")
        pl.addWidget(self.scopes)
        pl.addWidget(label("Rules come from permissions.json in the data folder (stricter-only: it can deny or require confirmation, never relax the built-in checks).", "faint"))
        tabs.addTab(pw, "Permissions")
        # audit
        aw = QWidget()
        al = QVBoxLayout(aw)
        row = QHBoxLayout()
        self.chain = label("")
        row.addWidget(self.chain, 1)
        verify = QPushButton("Verify the chain")
        verify.clicked.connect(self._verify)
        row.addWidget(verify)
        al.addLayout(row)
        self.audit = QTableWidget(0, 5)
        tidy_table(self.audit, -1)
        self.audit.setHorizontalHeaderLabels(["Time", "Tool", "Outcome", "Latency (s)", "Arguments (redacted)"])
        self.audit.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.audit.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        al.addWidget(self.audit, 1)
        tabs.addTab(aw, "Activity (audit log)")
        # undo
        uw = QWidget()
        ul = QVBoxLayout(uw)
        self.undo = QTableWidget(0, 3)
        tidy_table(self.undo, -1)
        self.undo.setHorizontalHeaderLabels(["When", "File", "Kind"])
        self.undo.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.undo.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        ul.addWidget(self.undo, 1)
        ul.addWidget(label("Ask the Companion to undo the last file change, or use /undo in the terminal.", "faint"))
        tabs.addTab(uw, "Undo")
        self.content.addWidget(tabs, 1)
        self.content.addWidget(label(LIMITS, "faint"))

    def refresh(self) -> None:
        pol = self.core.policy()
        auto = self.settings.get("auto_approve")
        self.summary.setText(("Auto-approve is ON: tools with real-world effects run without asking. " if auto else "Auto-approve is off: tools with real-world effects ask first. ") + f"{len(self.core.tool_names())} tools registered.")
        self.summary.setStyleSheet(f"color: {T.WARN if auto else T.TEXT_DIM};")
        self.perm.setRowCount(0)
        deny = getattr(pol, "deny", {}) or {}
        confirm = set(getattr(pol, "ask", set()) or set())
        for tool in sorted(self.core.tool_names()):
            if tool in deny:
                rule = f"Denied: {deny[tool]}"
            elif self.core.is_dangerous(tool) or tool in confirm:
                rule = "Asks first" + (" (auto-approve is on)" if auto else "")
            else:
                rule = "Allowed (read-only or low-risk)"
            r = self.perm.rowCount()
            self.perm.insertRow(r)
            self.perm.setItem(r, 0, QTableWidgetItem(tool))
            self.perm.setItem(r, 1, QTableWidgetItem(rule))
        scopes = getattr(pol, "write_scopes", None)
        self.scopes.setText(f"Write scopes inside the workspace: {', '.join(scopes)}" if scopes else "Write scopes: the whole workspace (no narrower scope set).")
        self.audit.setRowCount(0)
        for e in reversed(self.core.audit_tail(200)):
            r = self.audit.rowCount()
            self.audit.insertRow(r)
            cells = [str(e.get("ts", e.get("time", ""))), str(e.get("tool", "")), str(e.get("outcome", "")), f"{float(e.get('latency_s', 0) or 0):.2f}", json.dumps(e.get("args", ""), ensure_ascii=False)[:400]]
            for c, v in enumerate(cells):
                self.audit.setItem(r, c, QTableWidgetItem(v))
        self.undo.setRowCount(0)
        for u in self.core.undo_entries(30):
            r = self.undo.rowCount()
            self.undo.insertRow(r)
            for c, key in enumerate(("ts", "path", "kind")):
                self.undo.setItem(r, c, QTableWidgetItem(str(u.get(key, u.get("time", "")) if key == "ts" else u.get(key, ""))))
        self._verify()

    def _verify(self) -> None:
        ok, msg = self.core.audit_verify()
        self.chain.setText(("Audit chain intact: " if ok else "Audit chain BROKEN: ") + msg)
        self.chain.setStyleSheet(f"color: {T.OK if ok else T.ERR}; font-weight: 600;")
