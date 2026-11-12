"""Engineering: forms for every calculator in engineering.py, built from their real signatures.
Calculations run through the engineering_calc tool, so they are audited like any other call."""

from __future__ import annotations

import inspect
import json

from PyQt6.QtWidgets import QComboBox, QFormLayout, QHBoxLayout, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from ..widgets import Card, Page, label

DISCLAIMER = "First-pass numbers from closed-form formulas (SI units unless a field says otherwise). Not finite-element analysis, not a certified design, not a code-compliance check."


def parse(text: str):
    """Numbers as numbers; JSON for structures (dicts, lists); otherwise the text itself."""
    t = text.strip()
    if t == "":
        return None
    try:
        return json.loads(t)
    except ValueError:
        return t


class EngineeringPage(Page):
    title = "Engineering"
    subtitle = "Structures, aerodynamics and orbital mechanics calculators."

    def __init__(self, core, parent=None):
        super().__init__(core, parent)
        self.content.addWidget(label(DISCLAIMER, "warn"))
        self.sigs = core.engineering_calcs()
        top = QHBoxLayout()
        self.pick = QComboBox()
        self.pick.setAccessibleName("Calculator")
        for name in self.sigs:
            self.pick.addItem(name.replace("_", " ").capitalize(), name)
        self.pick.currentIndexChanged.connect(self._build)
        top.addWidget(label("Calculator"))
        top.addWidget(self.pick, 1)
        self.content.addLayout(top)
        body = QHBoxLayout()
        left = Card("Inputs")
        self.doc = label("", "faint", selectable=True)
        left.body.addWidget(self.doc)
        self.form_host = QWidget()
        self.form = QFormLayout(self.form_host)
        left.body.addWidget(self.form_host)
        run = QPushButton("Calculate")
        run.setObjectName("primary")
        run.clicked.connect(self.calculate)
        left.body.addWidget(run)
        left.body.addStretch(1)
        right = Card("Result")
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setAccessibleName("Result")
        right.body.addWidget(self.out)
        body.addWidget(left, 1)
        body.addWidget(right, 1)
        self.content.addLayout(body, 1)
        self.fields = {}
        self._build()

    def _build(self) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)
        self.fields.clear()
        name = self.pick.currentData()
        if not name:
            return
        self.doc.setText(self.core.engineering_doc(name) or "")
        for pname, p in self.sigs[name].parameters.items():
            if p.kind in (p.VAR_POSITIONAL,):
                continue
            edit = QLineEdit()
            edit.setAccessibleName(pname)
            if p.kind == p.VAR_KEYWORD:
                edit.setPlaceholderText('extra dimensions as JSON, e.g. {"b": 0.1, "h": 0.2}')
                pname = "**dims"
            elif p.default is not inspect.Parameter.empty:
                edit.setPlaceholderText(f"optional (default {p.default})")
            else:
                edit.setPlaceholderText("required")
            self.form.addRow(pname, edit)
            self.fields[pname] = edit

    def calculate(self) -> None:
        name = self.pick.currentData()
        params = {}
        for pname, edit in self.fields.items():
            value = parse(edit.text())
            if value is None:
                continue
            if pname == "**dims":
                if not isinstance(value, dict):
                    self.out.setPlainText("Extra dimensions must be a JSON object.")
                    return
                params.update(value)
            else:
                params[pname] = value
        res = self.core.dispatch("engineering_calc", calc=name, params=params)
        self.out.setPlainText(json.dumps(res, indent=2, ensure_ascii=False) + "\n\n" + DISCLAIMER)
