"""Forge: skills (proposed, tested, approved, versioned) and self-modification patches.
Every action goes through the core's tools, so the static policy gates, tests, confirmations and the
audit log apply. The stages are kept distinct: proposed → validated → approved → applied."""

from __future__ import annotations

import json
import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QAbstractItemView, QButtonGroup, QComboBox, QGridLayout, QHBoxLayout, QHeaderView, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget

from .. import icons
from .. import theme as T
from ..widgets import Card, Page, label, tidy_table


class ForgePage(Page):
    title = "Forge"
    subtitle = "Project work in four disciplines, skills Prometheus has learned, and changes it has proposed to itself."
    scroll = True

    def __init__(self, core, frozen: bool, parent=None):
        super().__init__(core, parent)
        self.frozen = frozen
        tabs = QTabWidget()
        tabs.setMinimumHeight(760)
        tabs.addTab(self._missions_tab(), "Missions")
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

    # ----- missions -----
    def _missions_tab(self) -> QWidget:
        from ...services.forge_missions import DISCIPLINES

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(12)
        grid = QGridLayout()
        grid.setSpacing(10)
        self.disc = QButtonGroup(self)
        self.disc.setExclusive(True)
        self.disc_keys = list(DISCIPLINES)
        for i, key in enumerate(self.disc_keys):
            d = DISCIPLINES[key]
            card = Card(d["name"], interactive=True, icon_name={"architect": "search", "builder": "forge", "debugger": "alert", "reconstructor": "file"}[key])
            summ = label(d["summary"], "sub")
            summ.setMinimumHeight(38)
            card.body.addWidget(summ)
            card.body.addWidget(label(d["boundary"], "faint"))
            pick = QPushButton("Choose")
            pick.setCheckable(True)
            pick.setChecked(i == 0)
            self.disc.addButton(pick, i)
            card.body.addWidget(pick, 0, Qt.AlignmentFlag.AlignRight)
            grid.addWidget(card, i // 2, i % 2)
        lay.addLayout(grid)
        form = Card("Start a mission", icon_name="bolt")
        row = QHBoxLayout()
        row.addWidget(label("Project", "sub"))
        self.project = QComboBox()
        self.project.setAccessibleName("Project")
        row.addWidget(self.project, 1)
        form.body.addLayout(row)
        self.objective = QPlainTextEdit()
        self.objective.setPlaceholderText("Objective or problem (for example: add drag to the trajectory model and a test for delta_v)")
        self.objective.setAccessibleName("Objective")
        self.objective.setFixedHeight(70)
        form.body.addWidget(self.objective)
        frow = QHBoxLayout()
        self.mission_msg = label("The mission runs in the Companion as its own conversation; you approve each change there.", "faint")
        frow.addWidget(self.mission_msg, 1)
        go = QPushButton(icons.icon("send", T.ON_ACCENT), " Start mission")
        go.setObjectName("primary")
        go.clicked.connect(self._start_mission)
        frow.addWidget(go)
        form.body.addLayout(frow)
        lay.addWidget(form)
        lay.addWidget(label("Mission history", "h2"))
        self.history = QListWidget()
        self.history.setObjectName("plain")
        self.history.setAccessibleName("Mission history")
        self.history.itemActivated.connect(self._open_mission)
        self.history.itemClicked.connect(self._open_mission)
        lay.addWidget(self.history, 1)
        return w

    def _start_mission(self) -> None:
        objective = self.objective.toPlainText().strip()
        project = self.project.currentData()
        if not project:
            self.mission_msg.setText("Put a project folder in the workspace first (Workspace page).")
            return
        if len(objective) < 5:
            self.mission_msg.setText("Describe the objective in a sentence.")
            return
        key = self.disc_keys[max(0, self.disc.checkedId())]
        win = self.window()
        if hasattr(win, "companion") and win.companion.start_mission(key, project, objective):
            self.objective.clear()
            win.go("Companion")
        else:
            self.mission_msg.setText("The mission did not start: see the Companion for the reason.")

    def _open_mission(self, item) -> None:
        cid = item.data(Qt.ItemDataRole.UserRole)
        win = self.window()
        if cid and hasattr(win, "companion"):
            win.go("Companion")
            win.companion.open_conversation(cid)

    def refresh(self) -> None:
        from ...services import forge_missions as F
        from ...services import workspace_info as W

        root = self.core.paths()["workspace"]
        current = self.project.currentData()
        self.project.clear()
        for p in W.projects(root):
            rel = os.path.relpath(p["path"], root)
            self.project.addItem(f"{p['name']}" + ("  (git)" if p["git"] else ""), "." if rel == "." else rel)
        if current:
            self.project.setCurrentIndex(max(0, self.project.findData(current)))
        self.history.clear()
        for m in F.MissionLog(self.core.paths()["data"]).list()[:50]:
            d = F.DISCIPLINES.get(m["discipline"], {"name": m["discipline"]})
            it = QListWidgetItem(icons.icon("forge", T.ACCENT), f"{d['name']} · {m['project']} — {m['objective'][:90]}   ·   {m['started'][:16].replace('T', ' ')}" + (f"   ·   {m['refused']} refused" if m.get("refused") else ""))
            it.setData(Qt.ItemDataRole.UserRole, m.get("conversation_id"))
            it.setToolTip("Open the conversation that holds this mission's work")
            self.history.addItem(it)
        if not self.history.count():
            self.history.addItem("No missions yet.")
        self._refresh_skills()

    def _refresh_skills(self) -> None:
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
