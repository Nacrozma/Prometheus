"""Memory: the memory graph's facts, entities and lessons, with provenance and trust made visible."""

from __future__ import annotations

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem

from .. import theme as T
from ..widgets import Card, Page, label, run_bg, tidy_table

KINDS = [("All kinds", None), ("Facts", ["fact"]), ("Preferences", ["preference"]), ("Lessons", ["lesson"]), ("Skills", ["skill"])]


class MemoryPage(Page):
    title = "Memory"
    subtitle = "What Prometheus remembers, where it came from, and how sure it is. Imported or web-derived facts are marked unverified."

    def __init__(self, core, parent=None):
        super().__init__(core, parent)
        self.stats = label("", "faint")
        self.content.addWidget(self.stats)
        row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Search memory (recall)…")
        self.query.setAccessibleName("Search memory")
        self.query.returnPressed.connect(self.refresh)
        self.kind = QComboBox()
        self.kind.setAccessibleName("Kind")
        for name, _ in KINDS:
            self.kind.addItem(name)
        self.kind.currentIndexChanged.connect(self.refresh)
        go = QPushButton("Search")
        go.clicked.connect(self.refresh)
        row.addWidget(self.query, 1)
        row.addWidget(self.kind)
        row.addWidget(go)
        self.content.addLayout(row)
        self.table = QTableWidget(0, 6)
        tidy_table(self.table, 0)
        self.table.setHorizontalHeaderLabels(["Fact", "Kind", "Source", "Trust", "Confidence", "Importance"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setAccessibleName("Facts")
        self.content.addWidget(self.table, 1)
        card = Card("Correcting memory")
        card.body.addWidget(label("Ask in the Companion (for example “forget that I live in Leeds” or “update: my role is now…”). Changes go through the update_memory tool, so they are checked and recorded like any other action.", "faint"))
        self.content.addWidget(card)

    def refresh(self) -> None:
        q = self.query.text().strip()
        kinds = KINDS[self.kind.currentIndex()][1]

        def load():
            facts = self.core.recall(q, top_k=50) if q else self.core.facts(kinds=kinds, limit=200)
            if q and kinds:
                facts = [f for f in facts if (f.get("fact", f).get("kind") if isinstance(f.get("fact"), dict) else f.get("kind")) in kinds]
            return self.core.memory_stats(), facts

        run_bg(load, self._show, lambda e: self.stats.setText("Could not read memory: " + e.splitlines()[0]), owner=self)

    def _show(self, data) -> None:
        stats, facts = data
        by = stats.get("facts_by_status", {})
        self.stats.setText(f"{stats.get('facts', 0)} facts ({by.get('active', 0)} active, {by.get('archived', 0)} archived) · {stats.get('entities', 0)} entities · {stats.get('relations', 0)} relations")
        self.table.setRowCount(0)
        for item in facts:
            f = item.get("fact", item) if isinstance(item.get("fact"), dict) else item
            r = self.table.rowCount()
            self.table.insertRow(r)
            source = str(f.get("source", ""))
            untrusted = self.core.is_untrusted(source)
            cells = [str(f.get("text", "")), str(f.get("kind", "")), source, "unverified" if untrusted else "operator / verified", f"{float(f.get('confidence', 0)):.2f}", f"{float(f.get('importance', 0)):.2f}"]
            for c, value in enumerate(cells):
                cell = QTableWidgetItem(value)
                if c == 3:
                    cell.setForeground(QColor(T.WARN if untrusted else T.OK))
                self.table.setItem(r, c, cell)
        if not facts:
            self.stats.setText(self.stats.text() + " · nothing matches")
