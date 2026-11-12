"""Reflection: how reliable each tool has actually been, lessons learned, and evaluation results.
Synthetic evaluation scores are labelled as such; they are not real-world performance."""

from __future__ import annotations

import json
import os

from PyQt6.QtWidgets import QAbstractItemView, QHeaderView, QPlainTextEdit, QTableWidget, QTableWidgetItem

from ..widgets import Card, Page, label, tidy_table


class ReflectionPage(Page):
    title = "Reflection"
    subtitle = "Tool reliability from real use, lessons from failures, and offline evaluation results."

    def __init__(self, core, parent=None):
        super().__init__(core, parent)
        self.table = QTableWidget(0, 6)
        tidy_table(self.table, -1)
        self.table.setHorizontalHeaderLabels(["Tool", "Calls", "Failures", "Success rate", "Avg latency (ms)", "Lesson"])
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAccessibleName("Tool reliability")
        self.content.addWidget(label("From real tool calls on this machine (tool_stats.json).", "faint"))
        self.content.addWidget(self.table, 2)
        ev = Card("Evaluation results (synthetic, offline)")
        ev.body.addWidget(label("Scripted scenarios run by evals/run_evals.py. They test behaviour against fixed cases; they are not a measure of real-world performance.", "faint"))
        self.evals = QPlainTextEdit()
        self.evals.setReadOnly(True)
        ev.body.addWidget(self.evals)
        self.content.addWidget(ev, 1)

    def refresh(self) -> None:
        stats = self.core.tool_stats()
        self.table.setRowCount(0)
        for tool, s in sorted(stats.items()):
            r = self.table.rowCount()
            self.table.insertRow(r)
            calls = s.get("calls", 0)
            fails = s.get("failures", 0)
            lesson = self.core.p.tool_stats.lesson_for(tool) or ""
            rate = s.get("success_rate")
            cells = [tool, str(calls), str(fails), f"{rate * 100:.0f}%" if rate is not None else "—", f"{s.get('avg_ms', 0):.0f}", lesson]
            for c, v in enumerate(cells):
                self.table.setItem(r, c, QTableWidgetItem(v))
        path = os.path.join(self.core.paths()["source"], "evals", "results.json")
        try:
            with open(path, encoding="utf-8") as f:
                self.evals.setPlainText(json.dumps(json.load(f), indent=2)[:20000])
        except Exception as e:
            self.evals.setPlainText(f"No evaluation results ({type(e).__name__}).")
