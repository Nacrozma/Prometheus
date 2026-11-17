"""Engineering: forms for every calculator in engineering.py, built from their real signatures.
Calculations run through the engineering_calc tool, so they are audited like any other call."""

from __future__ import annotations

import inspect
import json

from PyQt6.QtWidgets import QComboBox, QFormLayout, QHBoxLayout, QLineEdit, QListWidget, QPushButton, QTextBrowser, QWidget

from .. import icons
from .. import theme as T
from ..widgets import Card, Page, label

DOMAINS = {
    "Units": ["convert_units"],
    "Structures": ["section_properties", "beam", "bending_stress", "safety_factor", "torsion_shear", "euler_buckling", "plane_stress", "thermal_expansion"],
    "Aerodynamics": ["isa_atmosphere", "lift", "stall_speed", "reynolds_number"],
    "Orbital mechanics": ["circular_orbit", "vis_viva", "hohmann", "rocket_equation"],
}


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:,.6g}"
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def result_html(res: dict, esc) -> str:
    """A calculator result as a readable table: values with units, the formula, warnings."""
    if res.get("status") != "success":
        return f"<p style='color:{T.ERR};'><b>Could not calculate.</b> {esc(str(res.get('message') or res.get('error') or res))}</p>"
    out = res.get("results", {})
    rows = []
    items = out.items() if isinstance(out, dict) else [("result", out)]
    for k, v in items:
        if isinstance(v, dict) and "value" in v:
            val, unit = v.get("value"), v.get("unit", "")
        else:
            val, unit = v, ""
        rows.append(f"<tr><td style='color:{T.TEXT_SECONDARY}; padding:4px 14px 4px 0;'>{esc(str(k).replace('_', ' '))}</td><td style='font-weight:600; padding:4px 6px 4px 0;'>{esc(_fmt(val))}</td><td style='color:{T.TEXT_FAINT};'>{esc(str(unit))}</td></tr>")
    html = f"<table>{''.join(rows)}</table>"
    if res.get("formula"):
        html += f"<p style='color:{T.TEXT_SECONDARY}; margin-top:10px;'>Formula</p><pre style='color:{T.HIGHLIGHT}; white-space:pre-wrap;'>{esc(str(res['formula']))}</pre>"
    for w in res.get("warnings", []) or []:
        html += f"<p style='color:{T.WARN};'>⚠ {esc(str(w))}</p>"
    if res.get("inputs"):
        html += f"<p style='color:{T.TEXT_FAINT}; margin-top:10px;'>Inputs: {esc(json.dumps(res['inputs'], ensure_ascii=False))}</p>"
    return html

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
        import gui_markdown as md

        self.esc = md.esc
        top = QHBoxLayout()
        self.pick = QComboBox()
        self.pick.setAccessibleName("Calculator")
        listed = set()
        for domain, names in DOMAINS.items():
            avail = [n for n in names if n in self.sigs]
            if not avail:
                continue
            self.pick.addItem(f"— {domain} —", None)
            self.pick.model().item(self.pick.count() - 1).setEnabled(False)
            for name in avail:
                self.pick.addItem("   " + name.replace("_", " ").capitalize(), name)
                listed.add(name)
        for name in self.sigs:
            if name not in listed:
                self.pick.addItem(name.replace("_", " ").capitalize(), name)
        self.pick.setCurrentIndex(1)
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
        run = QPushButton(icons.icon("bolt", T.ON_ACCENT), " Calculate")
        run.setObjectName("primary")
        run.clicked.connect(self.calculate)
        left.body.addWidget(run)
        left.body.addStretch(1)
        right = Card("Result")
        self.out = QTextBrowser()
        self.out.setAccessibleName("Result")
        right.body.addWidget(self.out, 2)
        arow = QHBoxLayout()
        self.explain = QPushButton(icons.icon("chat", T.TEXT_SECONDARY), " Ask Prometheus to check this")
        self.explain.setObjectName("ghost")
        self.explain.setEnabled(False)
        self.explain.clicked.connect(self._ask)
        arow.addStretch(1)
        arow.addWidget(self.explain)
        right.body.addLayout(arow)
        right.body.addWidget(label("This session's calculations", "faint"))
        self.history = QListWidget()
        self.history.setObjectName("plain")
        self.history.setMaximumHeight(130)
        self.history.setAccessibleName("Calculation history")
        right.body.addWidget(self.history)
        self.last = None
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
                    self.out.setHtml(f"<p style='color:{T.ERR};'>Extra dimensions must be a JSON object.</p>")
                    return
                params.update(value)
            else:
                params[pname] = value
        res = self.core.dispatch("engineering_calc", calc=name, params=params)
        self.out.setHtml(result_html(res, self.esc) + f"<p style='color:{T.TEXT_FAINT}; margin-top:12px;'>{self.esc(DISCLAIMER)}</p>")
        self.last = (name, params, res)
        self.explain.setEnabled(res.get("status") == "success")
        summary = ", ".join(f"{k}={_fmt(v.get('value') if isinstance(v, dict) else v)}" for k, v in list((res.get("results") or {}).items())[:3]) if isinstance(res.get("results"), dict) else res.get("status", "")
        self.history.insertItem(0, f"{name.replace('_', ' ')}: {summary}")

    def _ask(self) -> None:
        if not self.last:
            return
        name, params, res = self.last
        win = self.window()
        if hasattr(win, "go"):
            win.go("Companion")
            win.companion.send(f"Check this {name.replace('_', ' ')} calculation and explain the result in plain terms. Inputs: {json.dumps(params)}. Result: {json.dumps(res.get('results'), default=str)}")
