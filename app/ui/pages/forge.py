"""Forge: a mission studio.

Left, the missions (a new mission at the top, then history) and the skills Prometheus has learned.
Centre, one of three views:
* **New mission**: project → objective → a recommended discipline (you can choose another) → its scope
  in plain words → start. The mission runs in the Companion as its own conversation, with approvals.
* **Mission**: the objective, the discipline's stages reached by recorded events only, files touched,
  runs, refusals and the final report, in the discipline's own vocabulary.
* **Skills & patches**: learned skills (roll back) and self-modification patches, as before.
Boundaries are enforced at the approval gate (`services/forge_missions.py`).
"""

from __future__ import annotations

import json
import os

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .. import icons
from .. import theme as T
from ..feedback import notify
from ..widgets import Page, label, tidy_table

DISC_ICON = {"architect": "search", "builder": "forge", "debugger": "alert", "reconstructor": "file"}
REPORT_TITLE = {"architect": "Plan and findings", "builder": "What was built", "debugger": "Root cause and fix", "reconstructor": "Recovered architecture"}
CHANGES_TITLE = {"architect": "Files read", "builder": "Files changed", "debugger": "Files changed by the fix", "reconstructor": "Recovery files written"}


class ForgePage(Page):
    title = "Forge"
    header = "none"
    margins = (0, 0, 0, 0)

    def __init__(self, core, frozen: bool, parent=None):
        super().__init__(core, parent)
        from ...services.forge_missions import DISCIPLINES

        self.frozen = frozen
        self.D = DISCIPLINES
        split = QSplitter()
        split.setHandleWidth(1)
        split.setChildrenCollapsible(False)

        # ----- rail -----
        rail = QFrame()
        rail.setObjectName("rail")
        rail.setMinimumWidth(240)
        rail.setMaximumWidth(320)
        rl = QVBoxLayout(rail)
        rl.setContentsMargins(16, 22, 12, 16)
        rl.setSpacing(10)
        rl.addWidget(label("Forge", "h1"))
        rl.addWidget(label("Project work in four disciplines, each with its own boundary.", "faint"))
        new = QPushButton(icons.icon("plus", T.ON_ACCENT), " New mission")
        new.setObjectName("primary")
        new.clicked.connect(lambda: self._show_new())
        rl.addWidget(new)
        rl.addWidget(label("MISSIONS", "eyebrow"))
        self.missions = QListWidget()
        self.missions.setObjectName("rail")
        self.missions.setIconSize(QSize(16, 16))
        self.missions.setWordWrap(True)
        self.missions.setAccessibleName("Missions")
        self.missions.itemClicked.connect(self._open_item)
        self.missions.itemActivated.connect(self._open_item)
        rl.addWidget(self.missions, 1)
        sk = QPushButton(icons.icon("bolt", T.TEXT_SECONDARY), " Skills && self-patches")
        sk.setObjectName("ghost")
        sk.clicked.connect(lambda: (self.stack.setCurrentIndex(2), self._refresh_skills()))
        rl.addWidget(sk)
        split.addWidget(rail)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._new_view())
        self.stack.addWidget(self._mission_view())
        self.stack.addWidget(self._skills_view())
        split.addWidget(self.stack)
        split.setStretchFactor(1, 1)
        split.setSizes([270, 1000])
        self.content.addWidget(split, 1)
        self.current = None

    # ----- new mission -----
    def _new_view(self) -> QWidget:
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.Shape.NoFrame)
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(36, 28, 36, 24)
        lay.setSpacing(14)
        lay.addWidget(label("NEW MISSION", "eyebrow"))
        t = label("What should Prometheus work on?", "h1")
        lay.addWidget(t)
        lay.addWidget(label("1  ·  Project", "h2"))
        self.project = QComboBox()
        self.project.setAccessibleName("Project")
        self.project.setMaximumWidth(520)
        lay.addWidget(self.project)
        self.no_project = label("No project folders in the workspace yet. Put a project in the workspace folder (Workspace page shows where it is).", "warn")
        lay.addWidget(self.no_project)
        lay.addWidget(label("2  ·  Objective", "h2"))
        self.objective = QPlainTextEdit()
        self.objective.setPlaceholderText("Describe the outcome or the problem, for example: “add drag to the trajectory model and a test for delta_v”, or “the importer crashes on empty files”.")
        self.objective.setAccessibleName("Objective")
        self.objective.setFixedHeight(84)
        self.objective.textChanged.connect(self._recommend)
        lay.addWidget(self.objective)
        lay.addWidget(label("3  ·  Discipline", "h2"))
        self.rec = label("", "faint")
        lay.addWidget(self.rec)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.disc = QButtonGroup(self)
        self.disc.setExclusive(True)
        self.keys = list(self.D)
        for i, key in enumerate(self.keys):
            b = QPushButton(icons.icon(DISC_ICON[key], T.TEXT_SECONDARY, active=T.ACCENT), f" {self.D[key]['name']}")
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setChecked(i == 1)
            b.setToolTip(self.D[key]["summary"])
            self.disc.addButton(b, i)
            row.addWidget(b)
        row.addStretch(1)
        self.disc.idClicked.connect(lambda _: self._scope())
        lay.addLayout(row)
        lay.addWidget(label("4  ·  Scope", "h2"))
        self.scope = QFrame()
        self.scope.setObjectName("homeRow")
        sl = QVBoxLayout(self.scope)
        sl.setContentsMargins(16, 12, 16, 12)
        self.scope_text = label("", "sub")
        sl.addWidget(self.scope_text)
        self.scope_bound = label("", "faint")
        sl.addWidget(self.scope_bound)
        lay.addWidget(self.scope)
        go_row = QHBoxLayout()
        self.new_msg = label("The mission opens in the Companion as its own conversation; you approve each change there. Auto-approve is off during missions.", "faint")
        go_row.addWidget(self.new_msg, 1)
        go = QPushButton(icons.icon("send", T.ON_ACCENT), " Start mission")
        go.setObjectName("primary")
        go.clicked.connect(self._start_mission)
        go_row.addWidget(go)
        lay.addLayout(go_row)
        lay.addStretch(1)
        sa.setWidget(w)
        self._scope()
        return sa

    def _disc(self) -> str:
        return self.keys[max(0, self.disc.checkedId())]

    def _recommend(self) -> None:
        from ...services.forge_missions import recommend

        text = self.objective.toPlainText().strip()
        if len(text) < 8:
            self.rec.setText("Prometheus suggests a discipline once you describe the objective.")
            return
        key = recommend(text)
        self.rec.setText(f"Suggested: {self.D[key]['name']}, from the wording of your objective. Choose another if it fits better.")
        self.disc.button(self.keys.index(key)).setChecked(True)
        self._scope()

    def _scope(self) -> None:
        d = self.D[self._disc()]
        self.scope_text.setText(f"{d['name']}: {d['summary']}")
        self.scope_bound.setText(f"Boundary: {d['boundary']}")

    def _start_mission(self) -> None:
        objective = self.objective.toPlainText().strip()
        project = self.project.currentData()
        if not project:
            notify(self, "Choose a project first", "warn", "Put a project folder in the workspace.")
            return
        if len(objective) < 5:
            notify(self, "Describe the objective in a sentence", "warn")
            return
        win = self.window()
        if hasattr(win, "companion") and win.companion.start_mission(self._disc(), project, objective):
            self.objective.clear()
            notify(self, f"{self.D[self._disc()]['name']} mission started", "info", "It is running in the Companion; approvals appear there.")
            win.go("Companion")
        else:
            notify(self, "The mission did not start", "err", "See the Companion for the reason.")

    def _show_new(self) -> None:
        self.missions.clearSelection()
        self.stack.setCurrentIndex(0)
        self.objective.setFocus()

    # ----- mission view -----
    def _mission_view(self) -> QWidget:
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.Shape.NoFrame)
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(36, 28, 36, 24)
        lay.setSpacing(12)
        self.m_eyebrow = label("", "eyebrow")
        lay.addWidget(self.m_eyebrow)
        self.m_title = label("", "h1")
        lay.addWidget(self.m_title)
        self.m_meta = label("", "faint")
        lay.addWidget(self.m_meta)
        self.m_stages = QHBoxLayout()
        self.m_stages.setSpacing(0)
        lay.addLayout(self.m_stages)
        row = QHBoxLayout()
        row.setSpacing(28)
        left = QVBoxLayout()
        self.m_report_title = label("", "eyebrow")
        left.addWidget(self.m_report_title)
        self.m_report = QTextBrowser()
        self.m_report.setMinimumHeight(320)
        self.m_report.setOpenLinks(False)
        left.addWidget(self.m_report, 1)
        row.addLayout(left, 3)
        right = QVBoxLayout()
        self.m_files_title = label("", "eyebrow")
        right.addWidget(self.m_files_title)
        self.m_files = label("", "sub")
        right.addWidget(self.m_files)
        right.addWidget(label("CHANGES PROPOSED", "eyebrow"))
        self.m_diff = QTextBrowser()
        self.m_diff.setAccessibleName("Changes proposed in this mission")
        self.m_diff.setMinimumHeight(160)
        right.addWidget(self.m_diff)
        right.addWidget(label("RUNS AND CHECKS", "eyebrow"))
        self.m_runs = label("", "sub")
        right.addWidget(self.m_runs)
        right.addWidget(label("BOUNDARY", "eyebrow"))
        self.m_bound = label("", "faint")
        right.addWidget(self.m_bound)
        right.addStretch(1)
        op = QPushButton(icons.icon("chat", T.TEXT_SECONDARY), " Open the conversation")
        op.clicked.connect(self._open_conversation)
        right.addWidget(op)
        row.addLayout(right, 2)
        lay.addLayout(row, 1)
        sa.setWidget(w)
        return sa

    def _open_item(self, item) -> None:
        m = item.data(Qt.ItemDataRole.UserRole)
        if m:
            self.show_mission(m)

    def show_mission(self, m: dict) -> None:
        from ...services.forge_missions import progress

        self.current = m
        win = self.window()
        conv = win.conversations.get(m.get("conversation_id", "")) if hasattr(win, "conversations") else None
        msgs = conv["messages"] if conv else []
        p = progress(m["discipline"], msgs)
        d = self.D.get(m["discipline"], {"name": m["discipline"], "boundary": ""})
        self.m_eyebrow.setText(f"{d['name'].upper()} MISSION · {m['project']}")
        self.m_title.setText(m["objective"])
        self.m_meta.setText(f"Started {m['started'][:16].replace('T', ' ')} · {p['reads']} reads · {p['changes']} change attempts · {len(p['runs'])} runs · {p['refused']} refused" + ("" if conv else " · its conversation was deleted"))
        while self.m_stages.count():
            it = self.m_stages.takeAt(0)
            if it.widget():
                it.widget().setParent(None)
        for i, name in enumerate(p["stages"]):
            done = i < p["reached"]
            current = i == p["reached"] - 1
            lab = label(("● " if done else "○ ") + name, wrap=False)
            lab.setStyleSheet(f"color: {T.ACCENT if current else T.OK if done else T.TEXT_FAINT}; padding: 6px 14px; border-bottom: 2px solid {T.ACCENT if current else T.BORDER_WARM if done else T.BORDER}; font-weight: {600 if current else 400};")
            lab.setAccessibleName(f"{name}: {'reached' if done else 'not reached'}")
            self.m_stages.addWidget(lab)
        self.m_stages.addStretch(1)
        self.m_report_title.setText(REPORT_TITLE.get(m["discipline"], "Report").upper())
        if p["report"]:
            import gui_markdown as md

            from .companion import MD_THEME

            self.m_report.setHtml(md.render_markdown(p["report"], MD_THEME, {}, id_prefix="fm"))
        else:
            self.m_report.setHtml(f"<p style='color:{T.TEXT_FAINT};'>No report yet. The mission is still running, waiting for an approval, or was stopped. Open the conversation to continue it.</p>")
        self.m_files_title.setText(CHANGES_TITLE.get(m["discipline"], "Files").upper())
        if m["discipline"] == "architect":
            reads = [c["args"].get("path") for c in p["calls"] if c["tool"] in ("read_file", "read_source_code") and c["args"].get("path")]
            self.m_files.setText("\n".join(f"• {r}" for r in dict.fromkeys(reads)) or "None yet.")
        else:
            self.m_files.setText("\n".join(f"• {f['path']}  ({f['status']})" for f in p["files"]) or "None yet.")
        self.m_runs.setText("\n".join(f"• {c['tool']}: {c['status']}" for c in p["runs"]) or "None.")
        import gui_markdown as md

        from ...services.approval import unified

        blocks = []
        for c in p["calls"]:
            a = c["args"]
            if c["tool"] == "edit_file" and ("old_string" in a or "new_string" in a):
                lines = unified(str(a.get("old_string", "")), str(a.get("new_string", "")), str(a.get("path", "")))
            elif c["tool"] == "write_file" and a.get("content"):
                lines = [f"+++ {a.get('path', '')} (written)"] + ["+" + ln for ln in str(a["content"]).splitlines()[:60]]
            else:
                continue
            rows = "".join(f'<span style="color:{T.OK if ln.startswith("+") and not ln.startswith("+++") else T.ERR if ln.startswith("-") and not ln.startswith("---") else T.TEXT_SECONDARY};">{md.esc(ln)}</span>\n' for ln in lines)
            blocks.append(f'<p style="color:{T.TEXT_FAINT}; margin:6px 0 2px 0;">{md.esc(c["tool"])} · {md.esc(c["status"])}</p><pre style="font-family:monospace; font-size:8pt; margin:0;">{rows}</pre>')
        self.m_diff.setHtml("".join(blocks) or f"<p style='color:{T.TEXT_FAINT};'>No file changes were proposed in this mission.</p>")
        self.m_bound.setText(d["boundary"])
        self.stack.setCurrentIndex(1)

    def _open_conversation(self) -> None:
        win = self.window()
        if self.current and hasattr(win, "companion"):
            win.go("Companion")
            win.companion.open_conversation(self.current.get("conversation_id", ""))

    # ----- skills and patches -----
    def _skills_view(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(36, 28, 36, 24)
        lay.setSpacing(10)
        lay.addWidget(label("SKILLS & SELF-PATCHES", "eyebrow"))
        lay.addWidget(label("What Prometheus has learned", "h1"))
        lay.addWidget(label("A skill is created by asking in the Companion. It must pass the static policy check and its own tests before it is registered; running one asks first unless Docker isolation is available.", "faint"))
        self.skills = QTableWidget(0, 5)
        tidy_table(self.skills, 3)
        self.skills.setHorizontalHeaderLabels(["Skill", "Version", "Enabled", "Description", "Tests"])
        self.skills.setAccessibleName("Skills")
        lay.addWidget(self.skills, 1)
        row = QHBoxLayout()
        self.skill_msg = label("", "faint")
        row.addWidget(self.skill_msg, 1)
        self.rollback_btn = QPushButton(icons.icon("retry", T.TEXT_SECONDARY), " Roll back selected skill")
        self.rollback_btn.clicked.connect(self._rollback)
        row.addWidget(self.rollback_btn)
        lay.addLayout(row)
        lay.addWidget(label("Self-patches", "h2"))
        if self.frozen:
            lay.addWidget(label("Self-modification patches change Prometheus's own source code, so they are only available when running from a source checkout.", "warn"))
        else:
            lay.addWidget(label("A patch is proposed in the Companion (propose_code_change), checked by the patch gate (static policy + tests), then applied only after you approve apply_pending_patch. The gate is not proof a patch is safe.", "faint"))
        self.patches = QTableWidget(0, 4)
        tidy_table(self.patches, 3)
        self.patches.setHorizontalHeaderLabels(["Patch", "Target", "Gate", "Details"])
        self.patches.setAccessibleName("Self-patches")
        lay.addWidget(self.patches, 1)
        return w

    def refresh(self) -> None:
        from ...services import forge_missions as F
        from ...services import workspace_info as W

        root = self.core.paths()["workspace"]
        current = self.project.currentData()
        self.project.clear()
        for p in W.projects(root):
            rel = os.path.relpath(p["path"], root)
            self.project.addItem(p["name"] + ("  · git" if p["git"] else ""), "." if rel == "." else rel)
        if current:
            self.project.setCurrentIndex(max(0, self.project.findData(current)))
        self.no_project.setVisible(self.project.count() == 0)
        self.missions.clear()
        ms = F.MissionLog(self.core.paths()["data"]).list()[:60]
        for m in ms:
            d = self.D.get(m["discipline"], {"name": m["discipline"]})
            it = QListWidgetItem(icons.icon(DISC_ICON.get(m["discipline"], "forge"), T.ACCENT), f"{m['objective'][:60]}\n{d['name']} · {m['project']} · {m['started'][5:16].replace('T', ' ')}")
            it.setData(Qt.ItemDataRole.UserRole, m)
            self.missions.addItem(it)
        if not ms:
            it = QListWidgetItem("No missions yet. Start one with New mission.")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.missions.addItem(it)
        if self.stack.currentIndex() == 1 and self.current:
            self.show_mission(self.current)
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
        self.skill_msg.setText("" if skills else "No skills yet. Ask Prometheus to learn one in a conversation.")
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
            notify(self, "Select a skill first", "warn")
            return
        name = self.skills.item(row, 0).text()
        res = self.core.dispatch("rollback_skill", name=name)
        notify(self, f"{name} rolled back" if res.get("status") == "success" else f"{name} was not rolled back", "ok" if res.get("status") == "success" else "err", res.get("message", ""))
        self._refresh_skills()
