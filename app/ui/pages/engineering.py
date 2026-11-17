"""Engineering: a workbench with two modes.

**Calculation studio** — a searchable library of the 17 calculators grouped by domain, a form built from
each calculator's real signature, and a result sheet that leads with the headline value, then the full
table with units, the formula and warnings. Calculations run through the engineering_calc tool (audited).

**Project intelligence** — for a project in the workspace: branch and changes (read-only Git), what it is
made of (languages, files, lines), entry points, the test files found, and plain-text code search whose
results open in the Workspace. "Review it" starts an Architect mission (read-only) in Forge.
"""

from __future__ import annotations

import inspect
import json
import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QButtonGroup, QComboBox, QFormLayout, QFrame, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSplitter, QStackedWidget, QTextBrowser, QVBoxLayout, QWidget

from .. import icons
from .. import theme as T
from ..feedback import notify
from ..widgets import Page, label, run_bg

DOMAINS = {
    "Units": ["convert_units"],
    "Structures": ["section_properties", "beam", "bending_stress", "safety_factor", "torsion_shear", "euler_buckling", "plane_stress", "thermal_expansion"],
    "Aerodynamics": ["isa_atmosphere", "lift", "stall_speed", "reynolds_number"],
    "Orbital mechanics": ["circular_orbit", "vis_viva", "hohmann", "rocket_equation"],
}
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


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:,.6g}"
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def _items(res: dict):
    out = res.get("results", {})
    items = out.items() if isinstance(out, dict) else [("result", out)]
    for k, v in items:
        if isinstance(v, dict) and "value" in v:
            yield str(k), v.get("value"), v.get("unit", "")
        else:
            yield str(k), v, ""


def result_html(res: dict, esc) -> str:
    """A calculator result as a readable sheet: headline value, then values with units, formula, warnings."""
    if res.get("status") != "success":
        return f"<p style='color:{T.ERR}; font-size:11pt;'><b>Could not calculate.</b></p><p>{esc(str(res.get('message') or res.get('error') or res))}</p>"
    items = list(_items(res))
    html = ""
    if items:
        k, v, u = items[0]
        html += f"<p style='color:{T.TEXT_SECONDARY}; margin:0;'>{esc(k.replace('_', ' '))}</p><p style='font-size:26pt; color:{T.HIGHLIGHT}; margin:0 0 12px 0;'>{esc(_fmt(v))} <span style='font-size:12pt; color:{T.TEXT_SECONDARY};'>{esc(str(u))}</span></p>"
    rows = "".join(f"<tr><td style='color:{T.TEXT_SECONDARY}; padding:4px 14px 4px 0;'>{esc(k.replace('_', ' '))}</td><td style='font-weight:600; padding:4px 6px 4px 0;'>{esc(_fmt(v))}</td><td style='color:{T.TEXT_FAINT};'>{esc(str(u))}</td></tr>" for k, v, u in items[1:])
    if rows:
        html += f"<table>{rows}</table>"
    if res.get("formula"):
        html += f"<p style='color:{T.TEXT_SECONDARY}; margin-top:12px;'>Formula</p><pre style='color:{T.HIGHLIGHT}; white-space:pre-wrap;'>{esc(str(res['formula']))}</pre>"
    for w in res.get("warnings", []) or []:
        html += f"<p style='color:{T.WARN};'>⚠ {esc(str(w))}</p>"
    return html


class EngineeringPage(Page):
    title = "Engineering"
    header = "none"
    margins = (0, 0, 0, 0)

    def __init__(self, core, parent=None):
        super().__init__(core, parent)
        import gui_markdown as md

        self.esc = md.esc
        self.sigs = core.engineering_calcs()
        self.fields = {}
        self.last = None
        top = QFrame()
        top.setObjectName("presence")
        tl = QHBoxLayout(top)
        tl.setContentsMargins(28, 16, 28, 12)
        tl.addWidget(label("Engineering", "h1"))
        tl.addSpacing(20)
        self.mode = QButtonGroup(self)
        for i, name in enumerate(("Calculation studio", "Project intelligence")):
            b = QPushButton(icons.icon("bolt" if i == 0 else "git", T.TEXT_SECONDARY, active=T.ACCENT), f" {name}")
            b.setObjectName("chip")
            b.setCheckable(True)
            b.setChecked(i == 0)
            self.mode.addButton(b, i)
            tl.addWidget(b)
        tl.addStretch(1)
        self.content.addWidget(top)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._studio())
        self.stack.addWidget(self._intel())
        self.mode.idClicked.connect(self._mode)
        self.content.addWidget(self.stack, 1)
        self._pick_first()

    def _mode(self, i: int) -> None:
        self.stack.setCurrentIndex(i)
        if i == 1:
            self._load_projects()

    # ----- calculation studio -----
    def _studio(self) -> QWidget:
        split = QSplitter()
        split.setHandleWidth(1)
        split.setChildrenCollapsible(False)
        lib = QFrame()
        lib.setObjectName("rail")
        lib.setMinimumWidth(230)
        lib.setMaximumWidth(300)
        ll = QVBoxLayout(lib)
        ll.setContentsMargins(14, 14, 10, 12)
        self.find = QLineEdit()
        self.find.setPlaceholderText("Find a calculator…")
        self.find.setAccessibleName("Find a calculator")
        self.find.setClearButtonEnabled(True)
        self.find.textChanged.connect(self._filter_lib)
        ll.addWidget(self.find)
        self.lib = QListWidget()
        self.lib.setObjectName("rail")
        self.lib.setAccessibleName("Calculators")
        self.lib.currentItemChanged.connect(lambda it, _p: self._build(it.data(Qt.ItemDataRole.UserRole)) if it and it.data(Qt.ItemDataRole.UserRole) else None)
        ll.addWidget(self.lib, 1)
        split.addWidget(lib)
        form = QWidget()
        fl = QVBoxLayout(form)
        fl.setContentsMargins(26, 18, 18, 14)
        fl.setSpacing(10)
        self.calc_title = label("", "h2")
        self.calc_title.setStyleSheet("font-size: 14pt;")
        fl.addWidget(self.calc_title)
        self.doc = label("", "faint", selectable=True)
        fl.addWidget(self.doc)
        host = QWidget()
        self.form = QFormLayout(host)
        self.form.setVerticalSpacing(10)
        fl.addWidget(host)
        run = QPushButton(icons.icon("bolt", T.ON_ACCENT), " Calculate")
        run.setObjectName("primary")
        run.clicked.connect(self.calculate)
        run.setMaximumWidth(200)
        fl.addWidget(run)
        fl.addWidget(label(DISCLAIMER, "faint"))
        fl.addStretch(1)
        split.addWidget(form)
        sheet = QFrame()
        sheet.setObjectName("inspector")
        sheet.setMinimumWidth(320)
        sl = QVBoxLayout(sheet)
        sl.setContentsMargins(20, 18, 18, 14)
        sl.addWidget(label("RESULT", "eyebrow"))
        self.out = QTextBrowser()
        self.out.setObjectName("conversation")
        self.out.setAccessibleName("Result")
        self.out.setHtml(f"<p style='color:{T.TEXT_FAINT};'>Fill in the inputs and press Calculate. The result appears here, with its formula.</p>")
        sl.addWidget(self.out, 2)
        self.explain = QPushButton(icons.icon("chat", T.TEXT_SECONDARY), " Ask Prometheus to check this")
        self.explain.setObjectName("ghost")
        self.explain.setEnabled(False)
        self.explain.clicked.connect(self._ask)
        sl.addWidget(self.explain)
        sl.addWidget(label("THIS SESSION", "eyebrow"))
        self.history = QListWidget()
        self.history.setObjectName("rail")
        self.history.setMaximumHeight(150)
        self.history.setAccessibleName("Calculation history")
        sl.addWidget(self.history)
        split.addWidget(sheet)
        split.setStretchFactor(1, 1)
        split.setSizes([250, 560, 380])
        self._fill_lib()
        return split

    def _fill_lib(self, q: str = "") -> None:
        self.lib.clear()
        q = q.lower().strip()
        for domain, names in DOMAINS.items():
            avail = [n for n in names if n in self.sigs and (not q or q in n.replace("_", " ") or q in domain.lower())]
            if not avail:
                continue
            h = QListWidgetItem(domain.upper())
            h.setFlags(Qt.ItemFlag.NoItemFlags)
            f = h.font()
            f.setBold(True)
            f.setPointSizeF(8)
            h.setFont(f)
            self.lib.addItem(h)
            for n in avail:
                it = QListWidgetItem("   " + n.replace("_", " ").capitalize())
                it.setData(Qt.ItemDataRole.UserRole, n)
                self.lib.addItem(it)

    def _filter_lib(self, q: str) -> None:
        self._fill_lib(q)

    def _pick_first(self) -> None:
        for i in range(self.lib.count()):
            if self.lib.item(i).data(Qt.ItemDataRole.UserRole):
                self.lib.setCurrentRow(i)
                return

    def _build(self, name: str) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)
        self.fields.clear()
        self.current_calc = name
        self.calc_title.setText(name.replace("_", " ").capitalize())
        self.doc.setText(self.core.engineering_doc(name) or "")
        for pname, p in self.sigs[name].parameters.items():
            if p.kind in (p.VAR_POSITIONAL,):
                continue
            edit = QLineEdit()
            edit.setAccessibleName(pname)
            edit.returnPressed.connect(self.calculate)
            if p.kind == p.VAR_KEYWORD:
                edit.setPlaceholderText('extra dimensions as JSON, e.g. {"b": 0.1, "h": 0.2}')
                pname = "**dims"
            elif p.default is not inspect.Parameter.empty:
                edit.setPlaceholderText(f"optional (default {p.default})")
            else:
                edit.setPlaceholderText("required")
            self.form.addRow(pname.replace("_", " "), edit)
            self.fields[pname] = edit

    def calculate(self) -> None:
        name = getattr(self, "current_calc", None)
        if not name:
            return
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
        self.out.setHtml(result_html(res, self.esc))
        self.last = (name, params, res)
        ok = res.get("status") == "success"
        self.explain.setEnabled(ok)
        if ok:
            k, v, u = next(_items(res), ("", "", ""))
            self.history.insertItem(0, f"{name.replace('_', ' ')}: {k.replace('_', ' ')} = {_fmt(v)} {u}")
        else:
            notify(self, "Could not calculate", "err", str(res.get("message") or res.get("error") or "")[:160])

    def _ask(self) -> None:
        if not self.last:
            return
        name, params, res = self.last
        win = self.window()
        if hasattr(win, "go"):
            win.go("Companion")
            win.companion.send(f"Check this {name.replace('_', ' ')} calculation and explain the result in plain terms. Inputs: {json.dumps(params)}. Result: {json.dumps(res.get('results'), default=str)}")

    # ----- project intelligence -----
    def _intel(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(28, 18, 28, 14)
        lay.setSpacing(10)
        row = QHBoxLayout()
        self.project = QComboBox()
        self.project.setAccessibleName("Project")
        self.project.setMinimumWidth(300)
        self.project.currentIndexChanged.connect(lambda _: self._analyse())
        row.addWidget(label("Project", "sub"))
        row.addWidget(self.project)
        row.addStretch(1)
        review = QPushButton(icons.icon("search", T.TEXT_SECONDARY), " Review it (Architect, read-only)")
        review.clicked.connect(self._review)
        row.addWidget(review)
        lay.addLayout(row)
        self.no_projects = label("No projects in the workspace yet. Put a project folder in the workspace (see the Workspace page for where it is).", "warn")
        lay.addWidget(self.no_projects)
        cols = QHBoxLayout()
        cols.setSpacing(30)
        left = QVBoxLayout()
        left.addWidget(label("REPOSITORY", "eyebrow"))
        self.repo = label("", "sub")
        left.addWidget(self.repo)
        left.addWidget(label("MADE OF", "eyebrow"))
        self.made = label("", "sub")
        left.addWidget(self.made)
        left.addWidget(label("ENTRY POINTS AND MANIFESTS", "eyebrow"))
        self.entry = label("", "mono")
        left.addWidget(self.entry)
        left.addWidget(label("TESTS FOUND", "eyebrow"))
        self.tests = label("", "mono")
        left.addWidget(self.tests)
        left.addStretch(1)
        cols.addLayout(left, 2)
        right = QVBoxLayout()
        right.addWidget(label("CODE SEARCH", "eyebrow"))
        self.q = QLineEdit()
        self.q.setPlaceholderText("Search the project's code and text (press Enter)…")
        self.q.setAccessibleName("Code search")
        self.q.returnPressed.connect(self._grep)
        right.addWidget(self.q)
        self.hits = QListWidget()
        self.hits.setObjectName("rows")
        self.hits.setAccessibleName("Search results")
        self.hits.itemActivated.connect(self._open_hit)
        self.hits.itemClicked.connect(self._open_hit)
        right.addWidget(self.hits, 1)
        cols.addLayout(right, 3)
        lay.addLayout(cols, 1)
        return w

    def _load_projects(self) -> None:
        from ...services import workspace_info as W

        root = self.core.paths()["workspace"]
        cur = self.project.currentData()
        self.project.blockSignals(True)
        self.project.clear()
        for p in W.projects(root):
            self.project.addItem(icons.icon("git" if p["git"] else "workspace", T.ACCENT if p["git"] else T.TEXT_SECONDARY), p["name"], p["path"])
        self.project.setCurrentIndex(max(0, self.project.findData(cur)) if cur else 0)
        self.project.blockSignals(False)
        self.no_projects.setVisible(self.project.count() == 0)
        self._analyse()

    def _analyse(self) -> None:
        from ...services import project_intel as P
        from ...services import workspace_info as W

        path = self.project.currentData()
        if not path:
            return
        root = self.core.paths()["workspace"]
        self.made.setText("Reading the project…")
        run_bg(lambda: (W.git_status(root, path), P.summary(root, path)), self._show_intel, lambda m: self.made.setText("Could not read the project: " + m.splitlines()[0]), owner=self)

    def _show_intel(self, data) -> None:
        git, s = data
        if git.get("error"):
            self.repo.setText(git["error"])
        elif not git.get("git"):
            self.repo.setText("Not a Git repository: there is no change history to show.")
        else:
            ch = git.get("changes", [])
            self.repo.setText(f"⎇ {git.get('branch', '')} · {len(ch)} changed file{'s' if len(ch) != 1 else ''}" + (" — clean" if not ch else "") + (f"\nLast commit: {git['commits'][0]['subject']} ({git['commits'][0]['when']})" if git.get("commits") else ""))
        if s.get("error"):
            self.made.setText(s["error"])
            return
        langs = ", ".join(f"{n} {c}" for n, c in s["languages"]) or "no recognised source files"
        self.made.setText(f"{s['files']} files · about {s['lines']:,} lines of text\n{langs}")
        self.entry.setText("\n".join(s["entry"]) or "none found")
        self.tests.setText(("\n".join(s["tests"][:15]) + (f"\n… and {len(s['tests']) - 15} more" if len(s["tests"]) > 15 else "")) if s["tests"] else "No test files found (looked for test_*, *_test.*, *.spec.*, tests/).")

    def _grep(self) -> None:
        from ...services import project_intel as P

        path = self.project.currentData()
        q = self.q.text()
        if not path or len(q.strip()) < 2:
            return
        root = self.core.paths()["workspace"]
        self.hits.clear()
        self.hits.addItem("Searching…")
        run_bg(lambda: P.grep(root, path, q), self._show_hits, owner=self)

    def _show_hits(self, hits) -> None:
        self.hits.clear()
        for h in hits:
            it = QListWidgetItem(f"{h['rel']}:{h['line']}\n{h['text']}")
            it.setData(Qt.ItemDataRole.UserRole, h["path"])
            self.hits.addItem(it)
        if not hits:
            it = QListWidgetItem("No matches.")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.hits.addItem(it)

    def _open_hit(self, item) -> None:
        p = item.data(Qt.ItemDataRole.UserRole)
        win = self.window()
        if p and hasattr(win, "pages"):
            win.go("Workspace")
            win.pages["Workspace"].reveal(p)

    def _review(self) -> None:
        path = self.project.currentData()
        win = self.window()
        if not path or not hasattr(win, "pages"):
            return
        forge = win.pages["Forge"]
        win.go("Forge")
        rel = os.path.relpath(path, self.core.paths()["workspace"])
        i = forge.project.findData(rel)
        if i >= 0:
            forge.project.setCurrentIndex(i)
        forge.disc.button(forge.keys.index("architect")).setChecked(True)
        forge._scope()
        forge._show_new()
        forge.objective.setPlainText("Review this project: architecture overview, risks and weak points, and the most valuable next improvements.")

    def refresh(self) -> None:
        if self.stack.currentIndex() == 1:
            self._load_projects()
