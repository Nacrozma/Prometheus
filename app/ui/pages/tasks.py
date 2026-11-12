"""Tasks & scheduler: the core's persistent reminders (schedule.json) and the current task state.
Adding and cancelling go through the schedule_task / cancel_scheduled tools."""

from __future__ import annotations

import json

from PyQt6.QtWidgets import QAbstractItemView, QCheckBox, QHBoxLayout, QHeaderView, QLineEdit, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem

from ..widgets import Card, Page, label, tidy_table


class TasksPage(Page):
    title = "Tasks & schedule"
    subtitle = "Reminders and recurring jobs that survive restarts, and what Prometheus is working on."

    def __init__(self, core, parent=None):
        super().__init__(core, parent)
        add = Card("New reminder")
        row = QHBoxLayout()
        self.text = QLineEdit()
        self.text.setPlaceholderText("What to remind you about")
        self.text.setAccessibleName("Reminder text")
        self.when = QLineEdit()
        self.when.setPlaceholderText("When: 10m, 2h, 1d…")
        self.when.setAccessibleName("When")
        self.when.setMaximumWidth(160)
        self.recurring = QCheckBox("Repeat")
        go = QPushButton("Add")
        go.setObjectName("primary")
        go.clicked.connect(self._add)
        for w in (self.text,):
            row.addWidget(w, 1)
        for w in (self.when, self.recurring, go):
            row.addWidget(w)
        add.body.addLayout(row)
        self.msg = label("", "faint")
        add.body.addWidget(self.msg)
        self.content.addWidget(add)
        self.table = QTableWidget(0, 5)
        tidy_table(self.table, 0)
        self.table.setHorizontalHeaderLabels(["Reminder", "Next", "Repeats", "Status", "Id"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAccessibleName("Scheduled reminders")
        self.content.addWidget(self.table, 1)
        row2 = QHBoxLayout()
        row2.addWidget(label("Due reminders appear as a notification and in the Companion. Missed ones (while Prometheus was closed) are delivered once when it next starts.", "faint"), 1)
        cancel = QPushButton("Cancel selected")
        cancel.clicked.connect(self._cancel)
        row2.addWidget(cancel)
        self.content.addLayout(row2)
        st = Card("Current task state")
        self.state = QPlainTextEdit()
        self.state.setReadOnly(True)
        self.state.setMaximumHeight(160)
        st.body.addWidget(self.state)
        self.content.addWidget(st)

    def refresh(self) -> None:
        jobs = self.core.scheduled()
        self.table.setRowCount(0)
        for j in jobs:
            r = self.table.rowCount()
            self.table.insertRow(r)
            rec = j.get("recurrence_seconds")
            cells = [j.get("text", ""), str(j.get("next_fire", "")), f"every {rec}s" if rec else "no", j.get("status", ""), j.get("id", "")]
            for c, v in enumerate(cells):
                self.table.setItem(r, c, QTableWidgetItem(str(v)))
        res = self.core.dispatch("read_task_state")
        self.state.setPlainText(json.dumps(res.get("task_state", res), indent=2, ensure_ascii=False))

    def _add(self) -> None:
        if not self.text.text().strip() or not self.when.text().strip():
            self.msg.setText("Give the reminder a text and a time.")
            return
        res = self.core.dispatch("schedule_task", when=self.when.text().strip(), text=self.text.text().strip(), recurring=self.recurring.isChecked())
        self.msg.setText(res.get("message") or (f"Scheduled for {res.get('job', {}).get('next_fire', '')}" if res.get("status") == "success" else str(res)))
        if res.get("status") == "success":
            self.text.clear()
            self.when.clear()
        self.refresh()

    def _cancel(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            self.msg.setText("Select a reminder first.")
            return
        res = self.core.dispatch("cancel_scheduled", job_id=self.table.item(row, 4).text())
        self.msg.setText(f"{res.get('status')}: {res.get('message', '')}")
        self.refresh()
