"""Memory: a personal knowledge library, not a database table.

Left, a rail of categories with counts and a **Review** queue (memories Prometheus suggested that you have
not confirmed). Centre, memories as readable rows. Right, an inspector for the selected memory: who it
came from, when, what it links to, its earlier versions, and the actions (confirm, correct, forget).
Search does not reinforce what it finds. Every change is audited (`services/memory_ops.py`).
"""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .. import icons
from .. import theme as T
from ..feedback import notify
from ..widgets import Page, label, run_bg

VIEWS = [("all", "All memories", None, "memory"), ("review", "Review suggestions", None, "bell"), ("fact", "Facts", ["fact"], "file"), ("preference", "Preferences", ["preference"], "sun"), ("decision", "Decisions", ["decision"], "check"), ("lesson", "Lessons", ["lesson"], "reflection")]
KIND_NAMES = [("Fact", "fact"), ("Preference", "preference"), ("Decision", "decision"), ("Lesson", "lesson")]
PROVENANCE_TONE = {"You": T.OK, "Confirmed by you": T.OK, "Prometheus (suggested)": T.HIGHLIGHT, "Unverified": T.WARN}


class MemoryDialog(QDialog):
    """Write or correct a memory. Similar existing memories are shown before saving."""

    def __init__(self, ops, title: str, text: str = "", kind: str = "fact", exclude: str = "", parent=None):
        super().__init__(parent)
        self.ops, self.exclude = ops, exclude
        self.setWindowTitle(title)
        self.resize(540, 340)
        lay = QVBoxLayout(self)
        lay.addWidget(label("One clear sentence. Prometheus uses memories as background knowledge, never as instructions.", "faint"))
        self.text = QPlainTextEdit(text)
        self.text.setAccessibleName("Memory text")
        self.text.setFixedHeight(90)
        lay.addWidget(self.text)
        row = QHBoxLayout()
        row.addWidget(label("Category", "sub"))
        self.kind = QComboBox()
        self.kind.setAccessibleName("Category")
        for name, k in KIND_NAMES:
            self.kind.addItem(name, k)
        self.kind.setCurrentIndex(max(0, self.kind.findData(kind)))
        self.kind.setEnabled(not exclude)
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
            if any(s["same"] for s in sim):
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
    header = "none"
    margins = (0, 0, 0, 0)

    def __init__(self, core, parent=None):
        super().__init__(core, parent)
        from ...services.memory_ops import MemoryOps

        self.ops = MemoryOps(core)
        self.rows = []
        self.view = "all"
        split = QSplitter()
        split.setHandleWidth(1)
        split.setChildrenCollapsible(False)

        # rail
        rail = QFrame()
        rail.setObjectName("rail")
        rail.setMinimumWidth(210)
        rail.setMaximumWidth(260)
        rl = QVBoxLayout(rail)
        rl.setContentsMargins(16, 22, 12, 16)
        rl.setSpacing(10)
        t = label("Memory", "h1")
        rl.addWidget(t)
        rl.addWidget(label("What Prometheus knows about you and your work.", "faint"))
        self.rail = QListWidget()
        self.rail.setObjectName("rail")
        self.rail.setIconSize(QSize(16, 16))
        self.rail.setAccessibleName("Memory views")
        for key, name, _, ic in VIEWS:
            it = QListWidgetItem(icons.icon(ic, T.TEXT_SECONDARY), name)
            it.setData(Qt.ItemDataRole.UserRole, key)
            self.rail.addItem(it)
        self.rail.setCurrentRow(0)
        self.rail.currentItemChanged.connect(lambda it, _p: self._set_view(it.data(Qt.ItemDataRole.UserRole) if it else "all"))
        rl.addWidget(self.rail, 1)
        add = QPushButton(icons.icon("plus", T.ON_ACCENT), " Add a memory")
        add.setObjectName("primary")
        add.clicked.connect(self.add_memory)
        rl.addWidget(add)
        self.stats = label("", "faint")
        rl.addWidget(self.stats)
        split.addWidget(rail)

        # library
        lib = QWidget()
        ll = QVBoxLayout(lib)
        ll.setContentsMargins(22, 22, 22, 16)
        ll.setSpacing(10)
        self.view_title = label("All memories", "h2")
        self.view_title.setStyleSheet("font-size: 14pt;")
        ll.addWidget(self.view_title)
        self.view_hint = label("", "faint")
        ll.addWidget(self.view_hint)
        self.query = QLineEdit()
        self.query.setPlaceholderText("Search what Prometheus remembers…")
        self.query.setAccessibleName("Search memory")
        self.query.setClearButtonEnabled(True)
        self.query.returnPressed.connect(self.refresh)
        self.query.textChanged.connect(lambda t: self.refresh() if not t else None)
        ll.addWidget(self.query)
        self.list = QListWidget()
        self.list.setObjectName("rows")
        self.list.setWordWrap(True)
        self.list.setAccessibleName("Memories")
        self.list.currentRowChanged.connect(self._selected)
        ll.addWidget(self.list, 1)
        split.addWidget(lib)

        # inspector
        ins = QFrame()
        ins.setObjectName("inspector")
        ins.setMinimumWidth(280)
        ins.setMaximumWidth(380)
        il = QVBoxLayout(ins)
        il.setContentsMargins(18, 22, 18, 16)
        il.setSpacing(10)
        il.addWidget(label("INSPECTOR", "eyebrow"))
        self.i_text = label("Select a memory to see where it came from, what it links to and how it changed.", "sub", selectable=True)
        self.i_text.setStyleSheet("font-size: 11pt;")
        il.addWidget(self.i_text)
        self.i_meta = label("", "faint", selectable=True)
        il.addWidget(self.i_meta)
        self.i_history = label("", "faint")
        il.addWidget(self.i_history)
        il.addStretch(1)
        self.confirm_btn = QPushButton(icons.icon("check", T.TEXT_SECONDARY), " Confirm it is right")
        self.correct_btn = QPushButton(icons.icon("edit", T.TEXT_SECONDARY), " Correct…")
        self.forget_btn = QPushButton(icons.icon("trash", T.ERR), " Forget…")
        self.forget_btn.setObjectName("danger")
        for b, fn in ((self.confirm_btn, self._confirm), (self.correct_btn, self._correct), (self.forget_btn, self._forget)):
            b.clicked.connect(fn)
            b.setEnabled(False)
            il.addWidget(b)
        split.addWidget(ins)
        split.setStretchFactor(1, 1)
        split.setSizes([230, 700, 320])
        self.content.addWidget(split, 1)

    # ----- data -----
    def show_query(self, text: str) -> None:
        self.query.setText(text)
        self.refresh()

    def _set_view(self, key: str) -> None:
        self.view = key
        self.refresh()

    def refresh(self) -> None:
        q = self.query.text().strip()
        view = next(v for v in VIEWS if v[0] == self.view)

        def load():
            rows = self.ops.rows(kinds=view[2], query=q)
            if self.view == "review":
                rows = [r for r in rows if r["provenance"] == "Prometheus (suggested)"]
            return self.core.memory_stats(), rows, self.ops.counts()

        run_bg(load, self._show, lambda e: self.view_hint.setText("Could not read memory: " + e.splitlines()[0]), owner=self)

    def _show(self, data) -> None:
        stats, rows, counts = data
        for i in range(self.rail.count()):
            it = self.rail.item(i)
            key = it.data(Qt.ItemDataRole.UserRole)
            name = next(v[1] for v in VIEWS if v[0] == key)
            it.setText(f"{name}   {counts.get(key, 0)}")
        by = stats.get("facts_by_status", {})
        self.stats.setText(f"{by.get('superseded', 0)} corrected · {by.get('archived', 0)} forgotten · {stats.get('entities', 0)} people, projects and topics")
        view = next(v for v in VIEWS if v[0] == self.view)
        self.view_title.setText(view[1])
        self.view_hint.setText({
            "review": "Things Prometheus decided to remember during conversations. Confirm what is right; correct or forget the rest.",
            "all": "Newest first. Search finds by meaning words and names, without reinforcing what it finds.",
        }.get(self.view, f"{view[1]} Prometheus keeps as background knowledge."))
        self.rows = rows
        self.list.clear()
        for f in rows:
            when = str(f.get("updated") or "")[:10]
            tone = PROVENANCE_TONE.get(f["provenance"], T.TEXT_SECONDARY)
            it = QListWidgetItem(f"{f['text']}\n{(f['kind'] or '').capitalize()} · from {f['provenance']} · {when}")
            it.setToolTip(f["text"])
            it.setForeground(__import__("PyQt6.QtGui", fromlist=["QColor"]).QColor(T.TEXT))
            it.setData(Qt.ItemDataRole.UserRole, tone)
            self.list.addItem(it)
        if not rows:
            msg = {
                "review": "✓ Nothing to review. Everything Prometheus remembers has been confirmed or came from you.",
            }.get(self.view, "Nothing matches your search." if self.query.text() else "Nothing here yet. Add a memory, or tell Prometheus something worth remembering.")
            it = QListWidgetItem(msg)
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(it)
        self._selected(self.list.currentRow())

    def _current(self):
        r = self.list.currentRow()
        return self.rows[r] if 0 <= r < len(self.rows) else None

    def _selected(self, _row: int = -1) -> None:
        f = self._current()
        for b in (self.confirm_btn, self.correct_btn, self.forget_btn):
            b.setEnabled(f is not None)
        if f is None:
            self.i_text.setText("Select a memory to see where it came from, what it links to and how it changed.")
            self.i_meta.setText("")
            self.i_history.setText("")
            return
        self.confirm_btn.setEnabled(f["provenance"] == "Prometheus (suggested)")
        self.i_text.setText(f["text"])
        ents = ", ".join(f.get("entities") or []) or "nothing yet"
        self.i_meta.setText(f"From: {f['provenance']}  (source “{f.get('source')}”)\nCategory: {(f['kind'] or '').capitalize()}\nRemembered: {str(f.get('created'))[:16].replace('T', ' ')}\nLast changed: {str(f.get('updated'))[:16].replace('T', ' ')}\nImportance now: {float(f.get('importance') or 0):.2f} (fades unless used)\nLinked to: {ents}")
        hist = self.ops.history(f["id"])
        self.i_history.setText(("Earlier versions:\n" + "\n".join(f"• {h['text']}  ({str(h['updated'])[:10]})" for h in hist)) if hist else "No earlier versions.")

    # ----- actions -----
    def _after(self, res, done: str, detail: str = "") -> None:
        if res.get("status") == "success":
            notify(self, done, "ok", detail)
            self.refresh()
        else:
            notify(self, "Memory not changed", "err", res.get("message", "That did not work."))

    def add_memory(self) -> None:
        dlg = MemoryDialog(self.ops, "Add a memory", parent=self)
        if dlg.exec():
            text, kind = dlg.values()
            self._after(self.ops.add(text, kind), "Memory saved", "Recorded in the audit log.")

    def _correct(self) -> None:
        f = self._current()
        if not f:
            return
        dlg = MemoryDialog(self.ops, "Correct a memory", text=f["text"], kind=f["kind"], exclude=f["id"], parent=self)
        if dlg.exec():
            text, _ = dlg.values()
            self._after(self.ops.correct(f["id"], text), "Memory corrected", "The old version is kept as history and no longer used.")

    def _confirm(self) -> None:
        f = self._current()
        if f:
            self._after(self.ops.confirm(f["id"]), "Memory confirmed")

    def _forget(self) -> None:
        f = self._current()
        if not f:
            return
        ans = QMessageBox.question(self, "Forget this memory?", f"“{f['text']}”\n\nPrometheus will stop using it: it is archived and removed from the retrieval index. The audit log keeps a record that it was forgotten (not its text).", QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.Cancel)
        if ans == QMessageBox.StandardButton.Yes:
            self._after(self.ops.forget(f["id"]), "Memory forgotten")
