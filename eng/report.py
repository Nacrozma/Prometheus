"""Engineering reports from experiment records: Markdown, HTML (with SVG plots), JSON, CSV and PDF.

A report contains exactly what the record holds (title, objective, inputs with units, assumptions, the model and
its formula, results, plots drawn from the stored series, validation status, uncertainty, limitations, software and
model version, timestamps) so an earlier result can be understood and re-run. Nothing is added that the record does
not support. PDF is produced through Qt (QTextDocument + QPdfWriter, already part of the desktop app); plots are
rasterised into the PDF with QtSvg.
"""
import html
import json
import os
from typing import Dict, Optional

from . import EngError
from .plots import line_plot


def plots_for(rec: dict) -> Dict[str, str]:
    out = {}
    for name, s in (rec.get("series") or {}).items():
        series = [{"x": s["x"], "y": s["y"], "label": s.get("ylabel", name), "style": s.get("style", "line")}]
        if "ref" in s:
            series.append({"x": s["x"], "y": s["ref"], "label": "reference", "style": "dashed"})
        if "front_x" in s:
            series.append({"x": s["front_x"], "y": s["front_y"], "label": "Pareto front", "style": "line"})
        try:
            out[name] = line_plot(series, title=f"{rec.get('title', '')}: {name}", xlabel=s.get("xlabel", ""), ylabel=s.get("ylabel", ""),
                                  log_x=bool(s.get("log")), log_y=bool(s.get("log")),
                                  note=f"{rec.get('id', '')} · model {rec.get('software', {}).get('eng_model_version', '?')} · {rec.get('validation_status', '')}")
        except EngError:
            continue
    return out


def _flat(d, prefix=""):
    rows = []
    if isinstance(d, dict):
        for k, v in d.items():
            rows += _flat(v, f"{prefix}{k}." if not isinstance(v, (dict, list)) or isinstance(v, dict) else f"{prefix}{k}.")
            if not isinstance(v, (dict, list)):
                rows[-1] = (f"{prefix}{k}", v)
    elif isinstance(d, list) and d and not isinstance(d[0], (dict, list)) and len(d) <= 12:
        rows.append((prefix.rstrip("."), ", ".join(f"{x:.6g}" if isinstance(x, float) else str(x) for x in d)))
    elif isinstance(d, list):
        rows.append((prefix.rstrip("."), f"[{len(d)} items]"))
    else:
        rows.append((prefix.rstrip("."), d))
    return rows


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:.6g}"
    return str(v)


def markdown(rec: dict) -> str:
    lines = [f"# {rec['title']}", "", f"*Experiment {rec['id']} · {rec['kind']} · validation status: **{rec['validation_status']}***", ""]
    if rec.get("objective"):
        lines += ["## Objective", rec["objective"], ""]
    if rec.get("hypothesis"):
        lines += ["## Hypothesis", rec["hypothesis"], ""]
    lines += ["## Inputs", "", "| parameter | value | unit |", "|---|---|---|"]
    for k, v in _flat(rec.get("inputs", {})):
        lines.append(f"| {k} | {_fmt(v)} | {rec.get('units', {}).get(k, '')} |")
    lines += ["", "## Model", f"`{rec.get('model') or 'manual / measured data'}` (eng model version {rec.get('software', {}).get('eng_model_version', '?')})", ""]
    if rec.get("assumptions"):
        lines += ["## Assumptions and limitations"] + [f"- {a}" for a in rec["assumptions"]] + [""]
    lines += ["## Results", "", "| quantity | value |", "|---|---|"]
    for k, v in _flat(rec.get("outputs", {})):
        lines.append(f"| {k} | {_fmt(v)} |")
    if rec.get("series"):
        lines += ["", "## Plots", ""] + [f"- `{rec['id']}_{n}.svg`" for n in rec["series"]]
    lines += ["", "## Validation", f"Status: **{rec['validation_status']}**." + (f" Evidence: {rec['evidence']}" if rec.get("evidence") else "")]
    if rec["validation_status"] != "hardware tested":
        lines.append("No physical measurement supports this result unless stated above.")
    if rec.get("uncertainty"):
        lines += ["", "## Uncertainty"] + [f"- {k}: {_fmt(v)}" for k, v in _flat(rec["uncertainty"])]
    if rec.get("data_files"):
        lines += ["", "## Data files"] + [f"- {f}" for f in rec["data_files"]]
    if rec.get("notes"):
        lines += ["", "## Notes"] + [f"- {n['at']}: {n['text']}" for n in rec["notes"]]
    sw = rec.get("software", {})
    lines += ["", "## Reproducibility", f"- created {rec.get('created_at')}, updated {rec.get('updated_at')}",
              f"- software: Prometheus {sw.get('prometheus_version', '?')}, commit {sw.get('git_commit', '?')}, eng model {sw.get('eng_model_version', '?')}",
              f"- input hash (SHA-256 of model + inputs): `{rec.get('input_hash', '')}`",
              "- re-run: `ExperimentStore(...).rerun(id)` executes the same model with the same inputs and compares the outputs.", "",
              "*Prometheus is an educational and experimental engineering tool; this report is not a certified engineering analysis.*"]
    return "\n".join(lines)


def html_report(rec: dict, plots: Optional[Dict[str, str]] = None) -> str:
    plots = plots if plots is not None else plots_for(rec)
    md = markdown(rec)
    body = []
    in_table = False
    for line in md.splitlines():
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if set("".join(cells)) <= set("-"):
                continue
            if not in_table:
                body.append("<table>")
                in_table = True
                body.append("<tr>" + "".join(f"<th>{html.escape(c)}</th>" for c in cells) + "</tr>")
                continue
            body.append("<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in cells) + "</tr>")
            continue
        if in_table:
            body.append("</table>")
            in_table = False
        if line.startswith("# "):
            body.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            if line[3:] == "Plots":
                body.append("<h2>Plots</h2>" + "".join(f"<figure>{svg}<figcaption>{html.escape(n)}</figcaption></figure>" for n, svg in plots.items()))
                continue
            body.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("- `") and line.endswith(".svg`"):
            continue
        elif line.startswith("- "):
            body.append(f"<li>{html.escape(line[2:])}</li>")
        elif line.strip():
            body.append(f"<p>{html.escape(line).replace('**', '')}</p>")
    if in_table:
        body.append("</table>")
    css = ("body{font-family:Segoe UI,Helvetica,Arial,sans-serif;max-width:900px;margin:24px auto;color:#1d1f24}"
           "table{border-collapse:collapse;margin:8px 0}td,th{border:1px solid #d5d8e0;padding:3px 8px;font-size:13px;text-align:left}"
           "th{background:#f3f4f7}h1{font-size:22px}h2{font-size:16px;margin-top:22px;border-bottom:1px solid #e6e8ee}figure{margin:10px 0}")
    return f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(rec['title'])}</title><style>{css}</style></head><body>{''.join(body)}</body></html>"


def csv_outputs(rec: dict) -> str:
    rows = ["quantity,value"] + [f"{k},{_fmt(v)}" for k, v in _flat(rec.get("outputs", {}))]
    return "\n".join(rows) + "\n"


def to_pdf(rec: dict, path: str, plots: Optional[Dict[str, str]] = None) -> str:
    """Write a PDF with Qt. Needs a Qt application (created offscreen if none exists)."""
    from PyQt6.QtCore import QByteArray, QMarginsF, QSizeF, QUrl
    from PyQt6.QtGui import QGuiApplication, QImage, QPageLayout, QPageSize, QPainter, QPdfWriter, QTextDocument
    from PyQt6.QtSvg import QSvgRenderer
    if QGuiApplication.instance() is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        QPdfWriter._app = QGuiApplication([])                      # keep a reference for the process lifetime
    plots = plots if plots is not None else plots_for(rec)
    doc = QTextDocument()
    imgs = []
    for name, svg in plots.items():
        r = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        img = QImage(1440, 840, QImage.Format.Format_ARGB32)
        img.fill(0xFFFFFFFF)
        p = QPainter(img)
        r.render(p)
        p.end()
        doc.addResource(QTextDocument.ResourceType.ImageResource.value, QUrl(f"plot://{name}"), img)
        imgs.append(name)
    html_body = html_report(rec, {n: f"<img src='plot://{n}' width='640'>" for n in imgs})
    doc.setHtml(html_body)
    writer = QPdfWriter(path)
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageMargins(QMarginsF(15, 15, 15, 15), QPageLayout.Unit.Millimeter)
    writer.setResolution(110)
    doc.setPageSize(QSizeF(writer.width(), writer.height()))
    doc.print(writer)
    return path


def write_all(rec: dict, outdir: str, pdf: bool = False) -> Dict[str, str]:
    os.makedirs(outdir, exist_ok=True)
    plots = plots_for(rec)
    files = {}
    base = os.path.join(outdir, rec["id"])
    for ext, text in (("md", markdown(rec)), ("html", html_report(rec, plots)), ("json", json.dumps(rec, indent=2, default=str)), ("csv", csv_outputs(rec))):
        with open(f"{base}.{ext}", "w", encoding="utf-8") as f:
            f.write(text)
        files[ext] = f"{base}.{ext}"
    for n, svg in plots.items():
        with open(f"{base}_{n}.svg", "w", encoding="utf-8") as f:
            f.write(svg)
        files[f"svg:{n}"] = f"{base}_{n}.svg"
    if pdf:
        files["pdf"] = to_pdf(rec, f"{base}.pdf", plots)
    return files
