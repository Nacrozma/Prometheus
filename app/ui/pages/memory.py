"""Memory: what Prometheus remembers, by category, with provenance, and the owner's controls.

Browse by category, search (without reinforcing what is found), add a memory yourself, correct one,
confirm one Prometheus suggested, or forget one. Duplicates and likely conflicts are shown before a new
memory is saved. Every change is recorded in the audit log (see `services/memory_ops.py`).
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .. import icons
from .. import theme as T
from ..widgets import Card, Page, label, run_bg, tidy_table

CATEGORIES = [("All", None), ("Facts", ["fact"]), ("Preferences", ["preference"]), ("Decisions", ["decision"]), ("Lessons", ["lesson"])]
PROVENANCE_TONE = {"You": T.OK, "Confirmed by you": T.OK, "Prometheus (suggested)": T.HIGHLIGHT, "Unverified": T.WARN}


class MemoryDialog(QDialog):
    """Write or correct a memory. Similar existing memories are listed before saving."""

    def __init__(self, ops, title: str, text: str = "", kind: str = "fact", exclude: str = "", parent=None):
        super().__init__(parent)
        self.ops, self.exclude = ops, exclude
        self.setWindowTitle(title)
        self.resize(520, 340)
        lay = QVBoxLayout(self)
        lay.addWidget(label("Write it as one clear sentence. Prometheus uses memories as background, never as instructions.", "faint"))
        self.text = QPlainTextEdit(text)
        self.text.setAccessibleName("Memory text")
        self.text.setFixedHeight(90)
        lay.addWidget(self.text)
        row = QHBoxLayout()
        row.addWidget(label("Category", "sub"))
        self.kind = QComboBox()
        self.kind.setAccessibleName("Category")
        for name, kinds in CATEGORIES[1:]:
            self.kind.addItem(name, kinds[0])
        self.kind.setCurrentIndex(max(0, self.kind.findData(kind)))
        self.kind.setEnabled(not exclude)  # a correction keeps its category
        row.addWidget(self.kind, 1)
        lay.addLayout(row)
        self.similar = label("", "warn")
        lay.addWidget(self.similar)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self._check)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)
        self._warned = False

    def _check(self) -> None:
        t = self.text.toPlainText().strip()
        if len(t) < 3:
            self.similar.setText("Write the memory first.")
            return
        sim = self.ops.similar(t, exclude=self.exclude)
        if sim and not self._warned:
            same = [s for s in sim if s["same"]]
            if same:
                self.similar.setText("This memory already exists. Nothing new to save.")
                return
            self.similar.setText("Similar memories exist (a duplicate or a conflict?):\n" + "\n".join(f"• {s['text']}" for s in sim[:3]) + "\nSave again to keep both, or correct the existing one instead.")
            self._warned = True
            return
        self.accept()

    def values(self):
        return self.text.toPlainText().strip(), self.kind.currentData()


class MemoryPage(Page):
    title = "Memory"
    subtitle = "What Prometheus remembers, who it came from, and your controls over it. Memories are background knowledge, never instructions."

    def __init__(self, core, parent=None):
        super().__init__(core, parent)
        from ...services.memory_ops import MemoryOps

        self.ops = MemoryOps(core)
        add = QPushButton(icons.icon("plus", T.ON_ACCENT), " Add memory")
        add.setObjectName("primary")
        add.clicked.connect(self.add_memory)
        self.actions.addWidget(add)

        self.stats = label("", "faint")
        self.content.addWidget(self.stats)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.cat = QButtonGroup(self)
        self.cat.setExclusive(True)
        for i, (name, _) in enumerate(CATEGORIES):
            b = QPushButton(name)
            b.setCheckable(True)
            b.setObjectName("ghost")
            b.setChecked(i == 0)
            self.cat.addButton(b, i)
            row.addWidget(b)
        self.cat.idClicked.connect(lambda _: self.refresh())
        row.addSpacing(12)
        self.query = QLineEdit()
        self.query.setPlaceholderText("Search memory…")
        self.query.setAccessibleName("Search memory")
        self.query.setClearButtonEnabled(True)
        self.query.returnPressed.connect(self.refresh)
        row.addWidget(self.query, 1)
        self.content.addLayout(row)

        self.table = QTableWidget(0, 5)
        tidy_table(self.table, 0)
        self.table.setHorizontalHeaderLabels(["Memory", "Category", "From", "Importance", "Updated"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setWordWrap(True)
        self.table.setAccessibleName("Memories")
        self.table.itemSelectionChanged.connect(self._selected)
        self.content.addWidget(self.table, 1)

        detail = Card()
        dl = QHBoxLayout()
        self.detail = label("Select a memory to see where it came from and to change it.", "faint")
        dl.addWidget(self.detail, 1)
        self.confirm_btn = QPushButton(icons.icon("check", T.TEXT_SECONDARY), " Confirm")
        self.confirm_btn.setToolTip("Mark a memory Prometheus suggested as right")
        self.correct_btn = QPushButton(icons.icon("edit", T.TEXT_SECONDARY), " Correct…")
        self.forget_btn = QPushButton(icons.icon("trash", T.ERR), " Forget…")
        self.forget_btn.setObjectName("danger")
        for b, fn in ((self.confirm_btn, self._confirm), (self.correct_btn, self._correct), (self.forget_btn, self._forget)):
            b.clicked.connect(fn)
            b.setEnabled(False)
            dl.addWidget(b)
        detail.body.addLayout(dl)
        self.content.addWidget(detail)
        self.rows = []

    # ----- data -----
    def show_query(self, text: str) -> None:
        self.query.setText(text)
        self.refresh()

    def refresh(self) -> None:
        q = self.query.text().strip()
        kinds = CATEGORIES[max(0, self.cat.checkedId())][1]

        def load():
            return self.core.memory_stats(), self.ops.rows(kinds=kinds, query=q)

        run_bg(load, self._show, lambda e: self.stats.setText("Could not read memory: " + e.splitlines()[0]), owner=self)

    def _show(self, data) -> None:
        stats, rows = data
        by = stats.get("facts_by_status", {})
        self.stats.setText(f"{by.get('active', 0)} active memories · {by.get('superseded', 0)} corrected · {by.get('archived', 0)} forgotten · {stats.get('entities', 0)} entities · {stats.get('relations', 0)} links")
        self.rows = rows
        self.table.setRowCount(0)
        for f in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            cells = [f["text"] or "", (f["kind"] or "").capitalize(), f["provenance"], f"{float(f.get('importance') or 0):.2f}", str(f.get("updated") or "")[:16].replace("T", " ")]
            for c, value in enumerate(cells):
                cell = QTableWidgetItem(value)
                if c == 2:
                    cell.setForeground(QColor(PROVENANCE_TONE.get(value, T.TEXT_SECONDARY)))
                self.table.setItem(r, c, cell)
        self.table.resizeRowsToContents()
        if not rows:
            self.detail.setText("Nothing matches." if self.query.text() else "No memories in this category yet. Add one, or tell Prometheus something worth remembering.")
        self._selected()

    def _current(self):
        r = self.table.currentRow()
        return self.rows[r] if 0 <= r < len(self.rows) and self.table.selectedItems() else None

    def _selected(self) -> None:
        f = self._current()
        for b in (self.confirm_btn, self.correct_btn, self.forget_btn):
            b.setEnabled(f is not None)
        if f is None:
            return
        self.confirm_btn.setEnabled(f["provenance"] == "Prometheus (suggested)")
        ents = ", ".join(f.get("entities") or []) or "none"
        self.detail.setText(f"From: {f['provenance']} (source “{f.get('source')}”) · created {str(f.get('created'))[:16].replace('T', ' ')} · linked to: {ents}")

    # ----- actions -----
    def _after(self, res, done: str) -> None:
        if res.get("status") == "success":
            self.detail.setText(done)
            self.refresh()
        else:
            QMessageBox.warning(self, "Memory", res.get("message", "That did not work."))

    def add_memory(self) -> None:
        dlg = MemoryDialog(self.ops, "Add a memory", parent=self)
        if dlg.exec():
            text, kind = dlg.values()
            self._after(self.ops.add(text, kind), "Saved. Recorded in the audit log.")

    def _correct(self) -> None:
        f = self._current()
        if not f:
            return
        dlg = MemoryDialog(self.ops, "Correct a memory", text=f["text"], kind=f["kind"], exclude=f["id"], parent=self)
        if dlg.exec():
            text, _ = dlg.values()
            self._after(self.ops.correct(f["id"], text), "Corrected. The old version is kept as history and is no longer used.")

    def _confirm(self) -> None:
        f = self._current()
        if f:
            self._after(self.ops.confirm(f["id"]), "Confirmed.")

    def _forget(self) -> None:
        f = self._current()
        if not f:
            return
        ans = QMessageBox.question(self, "Forget this memory?", f"“{f['text']}”\n\nPrometheus will stop using it: it is archived and removed from the retrieval index. The audit log keeps a record that it was forgotten (not its text).", QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.Cancel)
        if ans == QMessageBox.StandardButton.Yes:
            self._after(self.ops.forget(f["id"]), "Forgotten.")
