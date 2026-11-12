"""Forge: skills (proposed, tested, approved, versioned) and self-modification patches.
Every action goes through the core's tools, so the static policy gates, tests, confirmations and the
audit log apply. The stages are kept distinct: proposed → validated → approved → applied."""

from __future__ import annotations

import json

from PyQt6.QtWidgets import QAbstractItemView, QHBoxLayout, QHeaderView, QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget

from ..widgets import Card, Page, label, tidy_table


class ForgePage(Page):
    title = "Forge"
    subtitle = "Skills Prometheus has learned, and changes it has proposed to itself."

    def __init__(self, core, frozen: bool, parent=None):
        super().__init__(core, parent)
        self.frozen = frozen
        tabs = QTabWidget()
        # Skills
        sk = QWidget()
        sl = QVBoxLayout(sk)
        sl.addWidget(label("A skill is created by asking in the Companion (the synthesize/propose tools). It must pass the static policy check and its own tests before it is registered; running one asks first unless Docker isolation is available.", "faint"))
        self.skills = QTableWidget(0, 5)
        tidy_table(self.skills, 3)
        self.skills.setHorizontalHeaderLabels(["Skill", "Version", "Enabled", "Description", "Tests"])
        self.skills.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.skills.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.skills.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        sl.addWidget(self.skills, 1)
        row = QHBoxLayout()
        self.rollback_btn = QPushButton("Roll back selected skill")
        self.rollback_btn.clicked.connect(self._rollback)
        row.addStretch(1)
        row.addWidget(self.rollback_btn)
        sl.addLayout(row)
        self.skill_msg = label("", "faint")
        sl.addWidget(self.skill_msg)
        tabs.addTab(sk, "Skills")
        # Patches
        pt = QWidget()
        pl = QVBoxLayout(pt)
        if frozen:
            pl.addWidget(label("Self-modification patches change Prometheus's own source code, so they are only available when running from a source checkout. This installed copy bundles its code, which a patch must not change.", "warn"))
        else:
            pl.addWidget(label("A patch is proposed in the Companion (propose_code_change), checked by the patch gate (static policy + tests), then applied only after you approve apply_pending_patch. The gate is not proof a patch is safe.", "faint"))
        self.patches = QTableWidget(0, 4)
        tidy_table(self.patches, -1)
        self.patches.setHorizontalHeaderLabels(["Patch", "Target", "Gate", "Details"])
        self.patches.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.patches.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        pl.addWidget(self.patches, 1)
        tabs.addTab(pt, "Patches")
        self.content.addWidget(tabs, 1)

    def refresh(self) -> None:
        skills = self.core.skills()
        self.skills.setRowCount(0)
        for s in skills:
            r = self.skills.rowCount()
            self.skills.insertRow(r)
            cells = [s.get("name", ""), str(s.get("version", "")), "yes" if s.get("enabled", True) else "no", s.get("description", ""), str(s.get("tests_passed", s.get("tests", "")))]
            for c, v in enumerate(cells):
                self.skills.setItem(r, c, QTableWidgetItem(str(v)))
        self.skill_msg.setText("" if skills else "No skills yet.")
        patches = self.core.pending_patches()
        self.patches.setRowCount(0)
        for p in patches:
            r = self.patches.rowCount()
            self.patches.insertRow(r)
            gate = p.get("gate", {})
            cells = [p.get("_file", ""), p.get("target_file", p.get("target", "")), "passed" if isinstance(gate, dict) and gate.get("passed") else str(gate.get("status", "")) if isinstance(gate, dict) else str(gate), json.dumps({k: v for k, v in p.items() if k not in ("_file", "new_content", "content")})[:300]]
            for c, v in enumerate(cells):
                self.patches.setItem(r, c, QTableWidgetItem(str(v)))

    def _rollback(self) -> None:
        row = self.skills.currentRow()
        if row < 0:
            self.skill_msg.setText("Select a skill first.")
            return
        name = self.skills.item(row, 0).text()
        res = self.core.dispatch("rollback_skill", name=name)
        self.skill_msg.setText(f"{name}: {res.get('status')} {res.get('message', '')}")
        self.refresh()
