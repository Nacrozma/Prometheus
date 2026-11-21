"""Engineering Lab: the eng/ models with their inputs, results, plots, experiment records and reports.

Who: someone checking a design or studying a model. First thing they see: the model library and a ready, valid
input (the model's example), so pressing Run immediately shows a real result and its plots. Primary action: Run;
"Run & record" keeps a re-runnable experiment (written through the audited engineering_lab tool). Secondary:
experiments list, re-run (reproducibility check), report (Markdown, HTML, PDF). Every result says what it is: a
model output with its assumptions, never a measurement.
"""

from __future__ import annotations

import html
import json
import os
from typing import Optional

from PyQt6.QtCore import QByteArray, Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton,
                             QSplitter, QTextBrowser, QVBoxLayout, QWidget)

from . import icons
from . import theme as T
from .feedback import notify
from .widgets import label, run_bg

CATEGORY_NAMES = {"structures": "Structures", "machine": "Machine design", "design": "Design optimisation", "aerospace": "Aerospace",
                  "control": "Control", "arm": "Robot arm", "method": "Uncertainty"}


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:,.6g}"
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, default=str)[:300]
    return str(v)


def result_html(out: dict) -> str:
    from eng.report import _flat

    e = html.escape
    if out.get("status") != "success":
        return f"<p style='color:{T.ERR}; font-size:11pt;'><b>Could not run.</b></p><p>{e(str(out.get('message', out)))}</p>"
    res = {k: v for k, v in (out.get("results") or {}).items() if k not in ("inputs", "material_properties")} if isinstance(out.get("results"), dict) else out.get("results", {})
    rows = "".join(f"<tr><td style='color:{T.TEXT_SECONDARY}; padding:3px 14px 3px 0;'>{e(str(k).replace('_', ' '))}</td>"
                   f"<td style='font-weight:600;'>{e(_fmt(v))}</td></tr>" for k, v in _flat(res)[:80])
    parts = [f"<p style='color:{T.TEXT_FAINT}; margin:0;'>Model output (software) · eng model {e(str(out.get('model_version', '?')))} · not a measurement</p>",
             f"<table>{rows}</table>"]
    if out.get("formula"):
        parts.append(f"<p style='color:{T.TEXT_SECONDARY}; margin-top:10px;'>Equations</p><pre style='color:{T.HIGHLIGHT}; white-space:pre-wrap;'>{e(str(out['formula']))}</pre>")
    if out.get("assumptions"):
        parts.append(f"<p style='color:{T.TEXT_SECONDARY}; margin-top:8px;'>Assumptions and limits</p><ul>" + "".join(f"<li>{e(str(a))}</li>" for a in out["assumptions"]) + "</ul>")
    for w in out.get("warnings", []) or []:
        parts.append(f"<p style='color:{T.WARN};'>⚠ {e(str(w))}</p>")
    return "".join(parts)


class EngineeringLab(QWidget):
    def __init__(self, core, parent=None):
        super().__init__(parent)
        from eng import registry

        self.core = core
        self.registry = registry
        self.current: Optional[str] = None
        self.last: Optional[dict] = None
        self.selected_exp: Optional[str] = None
        split = QSplitter(self)
        split.setHandleWidth(1)
        split.setChildrenCollapsible(False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(split)

        rail = QFrame()
        rail.setObjectName("rail")
        rail.setMinimumWidth(230)
        rail.setMaximumWidth(300)
        rl = QVBoxLayout(rail)
        rl.setContentsMargins(14, 14, 10, 12)
        self.models = QListWidget()
        self.models.setObjectName("rail")
        self.models.setAccessibleName("Engineering models")
        self.models.currentItemChanged.connect(lambda it, _p: self._pick(it.data(Qt.ItemDataRole.UserRole)) if it and it.data(Qt.ItemDataRole.UserRole) else None)
        rl.addWidget(self.models, 3)
        rl.addWidget(label("EXPERIMENTS", "eyebrow"))
        self.exps = QListWidget()
        self.exps.setObjectName("rail")
        self.exps.setAccessibleName("Recorded experiments")
        self.exps.itemClicked.connect(self._open_exp)
        rl.addWidget(self.exps, 2)
        split.addWidget(rail)

        mid = QWidget()
        ml = QVBoxLayout(mid)
        ml.setContentsMargins(24, 18, 18, 14)
        ml.setSpacing(8)
        self.title = label("", "h2")
        self.title.setStyleSheet("font-size: 14pt;")
        ml.addWidget(self.title)
        self.doc = label("", "faint", selectable=True)
        ml.addWidget(self.doc)
        ml.addWidget(label("INPUTS (JSON, SI units)", "eyebrow"))
        self.params = QPlainTextEdit()
        self.params.setAccessibleName("Model inputs as JSON")
        f = QFont("Consolas")
        f.setStyleHint(QFont.StyleHint.Monospace)
        f.setPointSizeF(9.5)
        self.params.setFont(f)
        ml.addWidget(self.params, 1)
        self.exp_title = QLineEdit()
        self.exp_title.setPlaceholderText("Experiment title (used by Run & record)")
        self.exp_title.setAccessibleName("Experiment title")
        ml.addWidget(self.exp_title)
        row = QHBoxLayout()
        self.run_btn = QPushButton(icons.icon("bolt", T.ON_ACCENT), " Run")
        self.run_btn.setObjectName("primary")
        self.run_btn.clicked.connect(lambda: self.run(record=False))
        row.addWidget(self.run_btn)
        self.rec_btn = QPushButton(icons.icon("check", T.TEXT_SECONDARY), " Run && record")
        self.rec_btn.setToolTip("Run and keep an experiment record (inputs, model version, results, plots) that can be re-run")
        self.rec_btn.clicked.connect(lambda: self.run(record=True))
        row.addWidget(self.rec_btn)
        row.addStretch(1)
        reset = QPushButton("Example")
        reset.setObjectName("ghost")
        reset.setToolTip("Restore the example input for this model")
        reset.clicked.connect(lambda: self._pick(self.current) if self.current else None)
        row.addWidget(reset)
        ml.addLayout(row)
        ml.addWidget(label("Educational and experimental engineering models with stated assumptions. Not certified design; "
                           "no result here is a physical measurement. Validation status: docs/VALIDATION.md.", "faint"))
        split.addWidget(mid)

        right = QFrame()
        right.setObjectName("inspector")
        right.setMinimumWidth(380)
        rr = QVBoxLayout(right)
        rr.setContentsMargins(18, 18, 18, 14)
        rr.addWidget(label("RESULT", "eyebrow"))
        self.out = QTextBrowser()
        self.out.setObjectName("conversation")
        self.out.setAccessibleName("Result")
        self.out.setHtml(f"<p style='color:{T.TEXT_FAINT};'>Pick a model; its example input is ready. Press Run.</p>")
        rr.addWidget(self.out, 3)
        prow = QHBoxLayout()
        prow.addWidget(label("PLOT", "eyebrow"))
        self.plot_pick = QComboBox()
        self.plot_pick.setAccessibleName("Plot")
        self.plot_pick.currentIndexChanged.connect(self._show_plot)
        prow.addWidget(self.plot_pick, 1)
        rr.addLayout(prow)
        from PyQt6.QtSvgWidgets import QSvgWidget

        self.plot = QSvgWidget()
        self.plot.setMinimumHeight(230)
        self.plot.setAccessibleName("Plot of the result")
        rr.addWidget(self.plot, 3)
        arow = QHBoxLayout()
        self.rerun_btn = QPushButton(icons.icon("retry", T.TEXT_SECONDARY), " Re-run")
        self.rerun_btn.setObjectName("ghost")
        self.rerun_btn.setToolTip("Run the selected experiment again with its stored inputs and compare")
        self.rerun_btn.setEnabled(False)
        self.rerun_btn.clicked.connect(self.rerun)
        arow.addWidget(self.rerun_btn)
        self.report_btn = QPushButton(icons.icon("export", T.TEXT_SECONDARY), " Report")
        self.report_btn.setObjectName("ghost")
        self.report_btn.setToolTip("Write Markdown, HTML and PDF reports of the selected experiment")
        self.report_btn.setEnabled(False)
        self.report_btn.clicked.connect(self.report)
        arow.addWidget(self.report_btn)
        self.ask_btn = QPushButton(icons.icon("chat", T.TEXT_SECONDARY), " Explain")
        self.ask_btn.setObjectName("ghost")
        self.ask_btn.setEnabled(False)
        self.ask_btn.clicked.connect(self._ask)
        arow.addWidget(self.ask_btn)
        rr.addLayout(arow)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        split.setSizes([250, 520, 470])
        self._fill_models()
        self.refresh_experiments()

    # ----- library -----
    def _fill_models(self) -> None:
        self.models.clear()
        groups = {}
        for name, (_fn, cat, _doc) in self.registry.MODELS.items():
            groups.setdefault(cat, []).append(name)
        for cat in ("structures", "machine", "design", "aerospace", "control", "arm", "method"):
            if cat not in groups:
                continue
            h = QListWidgetItem(CATEGORY_NAMES.get(cat, cat).upper())
            h.setFlags(Qt.ItemFlag.NoItemFlags)
            fnt = h.font()
            fnt.setBold(True)
            fnt.setPointSizeF(8)
            h.setFont(fnt)
            self.models.addItem(h)
            for n in groups[cat]:
                it = QListWidgetItem("   " + n.replace("_", " ").capitalize())
                it.setData(Qt.ItemDataRole.UserRole, n)
                self.models.addItem(it)
        for i in range(self.models.count()):
            if self.models.item(i).data(Qt.ItemDataRole.UserRole):
                self.models.setCurrentRow(i)
                break

    def _pick(self, name: str) -> None:
        self.current = name
        self.title.setText(name.replace("_", " ").capitalize())
        self.doc.setText(self.registry.MODELS[name][2])
        self.params.setPlainText(json.dumps(self.registry.EXAMPLES.get(name, {}), indent=2))

    def refresh_experiments(self) -> None:
        self.exps.clear()
        try:
            lst = self._store().list()[:60]
        except Exception:
            lst = []
        if not lst:
            it = QListWidgetItem("No experiments yet: Run & record keeps one")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.exps.addItem(it)
        for r in lst:
            it = QListWidgetItem(f"{r['title']}\n{r['model']} · {r['validation_status']}")
            it.setData(Qt.ItemDataRole.UserRole, r["id"])
            it.setToolTip(f"{r['id']} · {r['created_at']}")
            self.exps.addItem(it)

    def _store(self):
        from eng.experiments import ExperimentStore

        return ExperimentStore(os.path.join(self.core.p.ENG_DIR, "experiments"))

    # ----- run -----
    def _inputs(self) -> Optional[dict]:
        try:
            v = json.loads(self.params.toPlainText() or "{}")
        except ValueError as e:
            self.out.setHtml(f"<p style='color:{T.ERR};'>The inputs are not valid JSON: {html.escape(str(e))}</p>")
            return None
        if not isinstance(v, dict):
            self.out.setHtml(f"<p style='color:{T.ERR};'>The inputs must be a JSON object of named parameters.</p>")
            return None
        return v

    def run(self, record: bool = False) -> None:
        if not self.current:
            return
        params = self._inputs()
        if params is None:
            return
        name = self.current
        title = self.exp_title.text().strip() or f"{name.replace('_', ' ')} run"
        self.run_btn.setEnabled(False)
        self.rec_btn.setEnabled(False)
        self.out.setHtml(f"<p style='color:{T.TEXT_FAINT};'>Running {html.escape(name)}…</p>")

        def work():
            if record:
                res = self.core.engineering_lab("run", model=name, params=params, record=True, title=title)
                if res.get("status") != "success":
                    return res
                rec = self._store().get(res["experiment_id"])
                full = self.registry.run(name, **params)
                full["experiment_id"] = rec["id"]
                return full
            return self.registry.run(name, **params)

        run_bg(work, self._done, lambda m: self._done({"status": "error", "message": m}), owner=self)

    def _done(self, out: dict) -> None:
        self.run_btn.setEnabled(True)
        self.rec_btn.setEnabled(True)
        self.last = out
        self.out.setHtml(result_html(out))
        self.ask_btn.setEnabled(out.get("status") == "success")
        self._load_plots(out)
        if out.get("experiment_id"):
            self.selected_exp = out["experiment_id"]
            self.rerun_btn.setEnabled(True)
            self.report_btn.setEnabled(True)
            self.refresh_experiments()
            notify(self, "Experiment recorded", "ok", out["experiment_id"])
        elif out.get("status") != "success":
            notify(self, "Could not run the model", "err", str(out.get("message", ""))[:160])

    def _load_plots(self, out: dict) -> None:
        self.series = out.get("series") or {}
        self.plot_pick.blockSignals(True)
        self.plot_pick.clear()
        for k, s in self.series.items():
            self.plot_pick.addItem(f"{s.get('ylabel', k)} vs {s.get('xlabel', '')}", k)
        self.plot_pick.blockSignals(False)
        self.plot_pick.setEnabled(bool(self.series))
        self._show_plot()

    def _show_plot(self) -> None:
        from eng.report import plots_for

        key = self.plot_pick.currentData()
        if not key or key not in self.series:
            self.plot.load(QByteArray(b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>'))
            return
        w = max(420, self.plot.width())
        svgs = plots_for({"title": self.current or "", "series": {key: self.series[key]}, "id": (self.last or {}).get("experiment_id", "not recorded"),
                          "software": {"eng_model_version": (self.last or {}).get("model_version", "?")}, "validation_status": "model output"},
                         width=w, height=int(w * 0.62))
        if key in svgs:
            self.plot.load(QByteArray(svgs[key].encode("utf-8")))

    # ----- experiments -----
    def _open_exp(self, item) -> None:
        eid = item.data(Qt.ItemDataRole.UserRole)
        if not eid:
            return
        try:
            rec = self._store().get(eid)
        except Exception as e:
            notify(self, "Could not open the experiment", "err", str(e))
            return
        self.selected_exp = eid
        self.rerun_btn.setEnabled(bool(rec.get("model")))
        self.report_btn.setEnabled(True)
        out = {"status": "success", "results": rec.get("outputs", {}), "assumptions": rec.get("assumptions", []),
               "model_version": rec.get("software", {}).get("eng_model_version"), "series": rec.get("series") or {}, "experiment_id": eid}
        self.last = out
        if rec.get("model") in self.registry.MODELS:
            self.current = rec["model"]
            self.title.setText(f"{rec['title']} ({rec['model']})")
            self.params.setPlainText(json.dumps(rec.get("inputs", {}), indent=2))
        self.out.setHtml(f"<p style='color:{T.TEXT_SECONDARY};'>{html.escape(rec['id'])} · {html.escape(rec['validation_status'])} · {html.escape(rec.get('created_at', ''))}</p>"
                         + result_html(out))
        self.ask_btn.setEnabled(True)
        self._load_plots(out)

    def rerun(self) -> None:
        if not self.selected_exp:
            return
        res = self.core.engineering_lab("rerun", experiment_id=self.selected_exp)
        if res.get("status") == "success" and res.get("reproduced"):
            notify(self, "Reproduced exactly", "ok", f"max relative difference {res.get('max_relative_difference')}")
        else:
            notify(self, "Not reproduced", "warn", str(res.get("message") or res)[:200])

    def report(self) -> None:
        if not self.selected_exp:
            return
        res = self.core.engineering_lab("report", experiment_id=self.selected_exp, formats=["md", "html", "pdf"])
        if res.get("status") != "success":
            notify(self, "Could not write the report", "err", str(res.get("message", ""))[:200])
            return
        notify(self, "Report written", "ok", os.path.dirname(res["files"]["md"]))
        QDesktopServices.openUrl(QUrl.fromLocalFile(res["files"].get("html") or res["files"]["md"]))

    def _ask(self) -> None:
        if not self.last:
            return
        win = self.window()
        if hasattr(win, "go"):
            win.go("Companion")
            brief = {k: v for k, v in self.last.items() if k not in ("series", "candidates")}
            win.companion.send(f"Explain this engineering result in plain terms, including its assumptions, limits and validation status "
                               f"(it is a model output, not a measurement): model {self.current}, "
                               f"result {json.dumps(brief.get('results'), default=str)[:3000]}")
