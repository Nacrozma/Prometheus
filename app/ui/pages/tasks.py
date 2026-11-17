"""Reminders & tasks: the core's persistent reminders (schedule.json) and the multi-session task record.

Adding and cancelling reminders go through the schedule_task / cancel_scheduled tools, and the task record
through update_task_state, so every change is audited like any tool call. "Ask Prometheus to plan it"
sends a request to the Companion; nothing is scheduled or run without you seeing it there.
"""

from __future__ import annotations

import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .. import icons
from .. import theme as T
from ..widgets import Card, Page, label, pill, tidy_table

STATUSES = ["idle", "in_progress", "blocked", "done"]
VIEWS = [("Upcoming", {"scheduled"}), ("Delivered", {"delivered"}), ("Cancelled", {"cancelled"}), ("All", None)]


def when_text(iso: str, now: datetime.datetime) -> str:
    """'in 2 h · Tue 18:08' style; falls back to the raw value."""
    try:
        t = datetime.datetime.fromisoformat(str(iso))
    except ValueError:
        return str(iso)
    secs = (t - now).total_seconds()
    if secs < 0:
        rel = "overdue"
    elif secs < 3600:
        rel = f"in {max(1, int(secs // 60))} min"
    elif secs < 86400:
        rel = f"in {secs / 3600:.0f} h"
    else:
        rel = f"in {secs / 86400:.0f} d"
    return f"{rel} · {t:%a %d %b %H:%M}"


def repeat_text(seconds) -> str:
    if not seconds:
        return "once"
    s = int(seconds)
    for unit, n in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if s % n == 0:
            k = s // n
            return f"every {unit}" if k == 1 else f"every {k} {unit}s"
    return f"every {s} s"


class TasksPage(Page):
    title = "Reminders & tasks"
    subtitle = "Reminders that survive restarts, and the long-running task Prometheus keeps across conversations."
    scroll = True

    def __init__(self, core, parent=None, companion=None):
        super().__init__(core, parent)
        self.companion = companion
        top = QHBoxLayout()
        top.setSpacing(14)

        add = Card("New reminder", icon_name="clock")
        self.text = QLineEdit()
        self.text.setPlaceholderText("What to remind you about")
        self.text.setAccessibleName("Reminder text")
        add.body.addWidget(self.text)
        row = QHBoxLayout()
        self.when = QLineEdit()
        self.when.setPlaceholderText("In: 10m, 2h, 1d…")
        self.when.setAccessibleName("When")
        self.recurring = QCheckBox("Repeat at that interval")
        go = QPushButton(icons.icon("plus", T.ON_ACCENT), " Add")
        go.setObjectName("primary")
        go.clicked.connect(self._add)
        self.when.returnPressed.connect(self._add)
        row.addWidget(self.when, 1)
        row.addWidget(self.recurring)
        row.addWidget(go)
        add.body.addLayout(row)
        self.msg = label("", "faint")
        add.body.addWidget(self.msg)
        top.addWidget(add, 1)

        work = Card("Current task", icon_name="tasks")
        self.goal = QLineEdit()
        self.goal.setPlaceholderText("Goal (for example: ship the rocket-sim drag model)")
        self.goal.setAccessibleName("Goal")
        work.body.addWidget(self.goal)
        self.steps = QPlainTextEdit()
        self.steps.setPlaceholderText("Steps, one per line")
        self.steps.setAccessibleName("Steps")
        self.steps.setFixedHeight(84)
        work.body.addWidget(self.steps)
        wrow = QHBoxLayout()
        self.status = QComboBox()
        self.status.setAccessibleName("Status")
        for s in STATUSES:
            self.status.addItem(s.replace("_", " ").capitalize(), s)
        wrow.addWidget(self.status)
        self.note = QLineEdit()
        self.note.setPlaceholderText("Add a note (optional)")
        self.note.setAccessibleName("Note")
        wrow.addWidget(self.note, 1)
        save = QPushButton("Save")
        save.clicked.connect(self._save_task)
        wrow.addWidget(save)
        work.body.addLayout(wrow)
        prow = QHBoxLayout()
        self.task_msg = label("", "faint")
        prow.addWidget(self.task_msg, 1)
        plan = QPushButton(icons.icon("chat", T.TEXT_SECONDARY), " Ask Prometheus to plan it")
        plan.setObjectName("ghost")
        plan.setToolTip("Sends the goal to the Companion and asks for steps; Prometheus records them with update_task_state")
        plan.clicked.connect(self._ask_plan)
        prow.addWidget(plan)
        work.body.addLayout(prow)
        top.addWidget(work, 1)
        self.content.addLayout(top)

        lst = Card("Reminders", icon_name="bell")
        vrow = QHBoxLayout()
        self.view = QButtonGroup(self)
        for i, (name, _) in enumerate(VIEWS):
            b = QPushButton(name)
            b.setCheckable(True)
            b.setObjectName("ghost")
            b.setChecked(i == 0)
            self.view.addButton(b, i)
            vrow.addWidget(b)
        self.view.idClicked.connect(lambda _: self.refresh())
        vrow.addStretch(1)
        cancel = QPushButton(icons.icon("trash", T.ERR), " Cancel selected")
        cancel.setObjectName("danger")
        cancel.clicked.connect(self._cancel)
        vrow.addWidget(cancel)
        lst.body.addLayout(vrow)
        self.table = QTableWidget(0, 4)
        tidy_table(self.table, 0)
        self.table.setHorizontalHeaderLabels(["Reminder", "When", "Repeats", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAccessibleName("Scheduled reminders")
        self.table.setMinimumHeight(260)
        lst.body.addWidget(self.table)
        lst.body.addWidget(label("Due reminders arrive as a notification (bell and system tray) and in the Companion. Ones that fell due while Prometheus was closed are delivered once when it next starts.", "faint"))
        self.content.addWidget(lst)
        self.notes = label("", "faint")
        self.content.addWidget(self.notes)
        self.jobs = []

    def refresh(self) -> None:
        now = datetime.datetime.now()
        wanted = VIEWS[max(0, self.view.checkedId())][1]
        jobs = self.core.p.scheduler_engine.list_jobs(include_delivered=True) if hasattr(self.core, "p") else self.core.scheduled()
        jobs = [j for j in jobs if wanted is None or j.get("status") in wanted]
        jobs.sort(key=lambda j: str(j.get("next_fire", "")), reverse=wanted is not None and "scheduled" not in wanted)
        self.jobs = jobs
        self.table.setRowCount(0)
        for j in jobs:
            r = self.table.rowCount()
            self.table.insertRow(r)
            st = j.get("status", "")
            self.table.setItem(r, 0, QTableWidgetItem(str(j.get("text", ""))))
            self.table.setItem(r, 1, QTableWidgetItem(when_text(j.get("next_fire", ""), now) if st == "scheduled" else str(j.get("next_fire", ""))[:16].replace("T", " ")))
            self.table.setItem(r, 2, QTableWidgetItem(repeat_text(j.get("recurrence_seconds"))))
            self.table.setCellWidget(r, 3, pill(st, {"scheduled": "accent", "delivered": "ok", "cancelled": "neutral"}.get(st, "neutral")))
        if not jobs:
            self.msg.setText(self.msg.text() or ("Nothing scheduled. Add a reminder above, or ask Prometheus in a conversation." if wanted and "scheduled" in wanted else ""))
        res = self.core.dispatch("read_task_state")
        state = res.get("task_state", {}) if isinstance(res, dict) else {}
        if not self.goal.hasFocus():
            self.goal.setText(state.get("goal") or "")
        if not self.steps.hasFocus():
            self.steps.setPlainText("\n".join(str(s) for s in state.get("steps") or []))
        i = self.status.findData(state.get("status") or "idle")
        self.status.setCurrentIndex(max(0, i))
        notes = state.get("notes") or []
        self.notes.setText(("Latest notes: " + " · ".join(f"{str(n.get('ts', ''))[:16].replace('T', ' ')} {n.get('note', '')}" for n in notes[-3:])) if notes else "")
        upd = state.get("updated")
        self.task_msg.setText(f"Last updated {str(upd)[:16].replace('T', ' ')}" if upd else "No task recorded yet.")

    def _add(self) -> None:
        if not self.text.text().strip() or not self.when.text().strip():
            self.msg.setText("Give the reminder a text and a time (for example 2h).")
            return
        res = self.core.dispatch("schedule_task", when=self.when.text().strip(), text=self.text.text().strip(), recurring=self.recurring.isChecked())
        if res.get("status") == "success":
            job = res.get("job", {})
            self.msg.setText(f"Scheduled: {when_text(job.get('next_fire', ''), datetime.datetime.now())}" + (f", {repeat_text(job.get('recurrence_seconds'))}" if job.get("recurrence_seconds") else ""))
            self.text.clear()
            self.when.clear()
        else:
            self.msg.setText(res.get("message") or str(res))
        self.refresh()

    def _cancel(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.jobs):
            self.msg.setText("Select a reminder first.")
            return
        job = self.jobs[row]
        res = self.core.dispatch("cancel_scheduled", job_id=job.get("id", ""))
        self.msg.setText("Cancelled." if res.get("status") == "success" else res.get("message", str(res)))
        self.refresh()

    def _save_task(self) -> None:
        steps = [s.strip() for s in self.steps.toPlainText().splitlines() if s.strip()]
        args = {"goal": self.goal.text().strip() or None, "steps": steps, "status": self.status.currentData()}
        if self.note.text().strip():
            args["note"] = self.note.text().strip()
        res = self.core.dispatch("update_task_state", **args)
        self.task_msg.setText("Saved. Prometheus sees this goal in every conversation while it is set." if res.get("status") == "success" else str(res))
        self.note.clear()
        self.refresh()

    def _ask_plan(self) -> None:
        goal = self.goal.text().strip()
        if not goal:
            self.task_msg.setText("Write a goal first.")
            return
        win = self.window()
        if hasattr(win, "go") and hasattr(win, "companion"):
            win.go("Companion")
            win.companion.send(f"Break this goal into a short list of concrete steps and record them as the current task with update_task_state (status in_progress): {goal}")
