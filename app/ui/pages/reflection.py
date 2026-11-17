"""Reflection: how Prometheus has actually performed, from its own records on this computer.

Tool reliability (real calls, tool_stats.json), lessons from repeated failures, model usage (the usage
log: request and token counts are a floor, since streamed replies may not report usage), suggested
improvements derived from those numbers, and the offline evaluation results, labelled as synthetic.
Nothing here claims that Prometheus improves its own model; suggestions are for you to act on.
"""

from __future__ import annotations

import json
import os

from PyQt6.QtWidgets import QHBoxLayout, QHeaderView, QTableWidget, QTableWidgetItem, QTextBrowser

from .. import theme as T
from ..widgets import Card, Page, label, run_bg, stat_tile, tidy_table

EVAL_LABELS = {
    "memory_recall": lambda v: f"Memory recall: precision@1 {v['memory_graph']['p_at_1']:.0%} on {v['queries']} queries (vector baseline {v['legacy_vector_rag']['p_at_1']:.0%})",
    "dedupe": lambda v: f"Memory de-duplication: {v['false_merges']} false merges of {v['must_not_merge_pairs']}, {v['missed_merges']} missed of {v['should_merge_pairs']}",
    "entity_extraction": lambda v: f"Entity extraction: F1 {v['f1']:.2f} (precision {v['precision']:.2f}, recall {v['recall']:.2f})",
    "skill_gate": lambda v: f"Skill safety gate: {v['bad_rejected']} of {v['bad_skills']} unsafe skills rejected, {v['good_accepted']} of {v['good_skills']} good ones accepted",
    "engineering": lambda v: f"Engineering calculators: {v['passed']} of {v['known_answer_cases']} known-answer cases pass",
    "arm_ik": lambda v: f"Arm inverse kinematics: {v['solved']} of {v['poses_tried']} poses solved, max error {v['max_position_error_mm']:.1g} mm",
}


def suggestions(stats: dict, lessons: dict) -> list:
    """Plain suggestions from the numbers (for the owner; nothing is changed automatically)."""
    out = []
    for tool, s in sorted(stats.items(), key=lambda kv: -(kv[1].get("failures", 0))):
        calls, fails = s.get("calls", 0), s.get("failures", 0)
        if calls >= 5 and fails / max(1, calls) >= 0.3:
            out.append(f"{tool} failed {fails} of {calls} times. " + (f"Recorded lesson: {lessons[tool]}" if lessons.get(tool) else (f"Last error: {s.get('last_error')}" if s.get("last_error") else "Check its inputs in the Trust & safety audit log.")))
        if s.get("refused", 0) >= 3:
            out.append(f"{tool} was refused {s['refused']} times by policy or by you; if it is never wanted, deny it in permissions.json so it is not attempted.")
        if s.get("avg_ms", 0) > 15000 and calls >= 3:
            out.append(f"{tool} takes {s['avg_ms'] / 1000:.0f} s on average; consider whether a faster route exists.")
    return out[:8]


class ReflectionPage(Page):
    title = "Reflection"
    subtitle = "How Prometheus has performed, from its own records: tool reliability, lessons, model usage and evaluation results."
    scroll = True

    def __init__(self, core, parent=None):
        super().__init__(core, parent)
        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        self.t_calls = stat_tile("—", "tool calls recorded")
        self.t_rate = stat_tile("—", "succeeded")
        self.t_fail = stat_tile("—", "tools with repeated failures")
        self.t_req = stat_tile("—", "model requests in 30 days (at least)")
        for t in (self.t_calls, self.t_rate, self.t_fail, self.t_req):
            tiles.addWidget(t)
        self.content.addLayout(tiles)

        sug = Card("Suggested improvements", icon_name="bolt")
        self.sug = label("", "sub")
        sug.body.addWidget(self.sug)
        sug.body.addWidget(label("Derived from the numbers below. Prometheus does not change its permissions, safety rules or code by itself; you decide.", "faint"))
        self.content.addWidget(sug)

        rel = Card("Tool reliability (real calls on this computer)", icon_name="reflection")
        self.table = QTableWidget(0, 6)
        tidy_table(self.table, 5)
        self.table.setHorizontalHeaderLabels(["Tool", "Calls", "Failures", "Success rate", "Avg latency", "Lesson"])
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.setAccessibleName("Tool reliability")
        self.table.setMinimumHeight(240)
        rel.body.addWidget(self.table)
        self.content.addWidget(rel)

        row = QHBoxLayout()
        row.setSpacing(14)
        use = Card("Model usage, last 30 days", icon_name="plug")
        self.usage = QTextBrowser()
        self.usage.setMinimumHeight(170)
        use.body.addWidget(self.usage)
        row.addWidget(use, 1)
        ev = Card("Evaluation results (synthetic, offline)", icon_name="check")
        self.evals = QTextBrowser()
        self.evals.setMinimumHeight(170)
        ev.body.addWidget(self.evals)
        ev.body.addWidget(label("Scripted scenarios (evals/run_evals.py) against fixed cases: not a measure of real-world performance.", "faint"))
        row.addWidget(ev, 1)
        self.content.addLayout(row)

    def refresh(self) -> None:
        def load():
            stats = self.core.tool_stats()
            lessons = {t: self.core.p.tool_stats.lesson_for(t) for t in stats}
            usage = self.core.p.parse_usage_log(days=30)
            path = os.path.join(self.core.paths()["source"], "evals", "results.json")
            try:
                with open(path, encoding="utf-8") as f:
                    evals = json.load(f)
            except Exception as e:
                evals = {"error": type(e).__name__}
            return stats, lessons, usage, evals

        run_bg(load, self._fill, lambda m: self.sug.setText("Could not read the records: " + m.splitlines()[0]), owner=self)

    def _fill(self, data) -> None:
        stats, lessons, usage, evals = data
        calls = sum(s.get("calls", 0) for s in stats.values())
        succ = sum(s.get("successes", 0) for s in stats.values())
        counted = succ + sum(s.get("failures", 0) for s in stats.values())
        failing = [t for t, l in lessons.items() if l]
        self.t_calls.value_label.setText(f"{calls:,}")
        self.t_rate.value_label.setText(f"{succ / counted:.0%}" if counted else "—")
        self.t_fail.value_label.setText(str(len(failing)))
        self.t_fail.value_label.setStyleSheet(f"color: {T.WARN if failing else T.TEXT};")
        provs = (usage or {}).get("providers", {}) if isinstance(usage, dict) else {}
        self.t_req.value_label.setText(f"{sum(p.get('requests', 0) for p in provs.values()):,}")

        self.table.setRowCount(0)
        for tool, s in sorted(stats.items(), key=lambda kv: -kv[1].get("calls", 0)):
            r = self.table.rowCount()
            self.table.insertRow(r)
            rate = s.get("success_rate")
            cells = [tool, str(s.get("calls", 0)), str(s.get("failures", 0)), f"{rate * 100:.0f}%" if rate is not None else "—", f"{s.get('avg_ms', 0):.0f} ms", lessons.get(tool) or ""]
            for c, v in enumerate(cells):
                item = QTableWidgetItem(v)
                if c == 3 and rate is not None and rate < 0.7:
                    item.setForeground(__import__("PyQt6.QtGui", fromlist=["QColor"]).QColor(T.WARN))
                self.table.setItem(r, c, item)
        if not stats:
            self.table.setRowCount(1)
            self.table.setItem(0, 0, QTableWidgetItem("No tool calls recorded yet."))

        sug = suggestions(stats, lessons)
        self.sug.setText("\n".join(f"• {s}" for s in sug) if sug else ("Nothing stands out: no tool fails repeatedly." if stats else "No activity recorded yet. Suggestions appear once Prometheus has used its tools."))

        if provs:
            rows = "".join(f"<tr><td style='padding-right:14px;'>{p}</td><td style='padding-right:14px;'>{v.get('requests', 0):,} requests</td><td style='color:{T.TEXT_SECONDARY};'>{v.get('prompt_tokens', 0):,} in · {v.get('completion_tokens', 0):,} out tokens</td></tr>" for p, v in provs.items())
            self.usage.setHtml(f"<table>{rows}</table><p style='color:{T.TEXT_FAINT};'>Counts from the usage log. Streamed replies may not report usage, so treat these as a floor. Prometheus shows no prices: provider pricing changes and is not verified here.</p>")
        else:
            note = usage.get("note") or usage.get("message") if isinstance(usage, dict) else ""
            self.usage.setHtml(f"<p style='color:{T.TEXT_FAINT};'>{note or 'No model requests recorded in the last 30 days.'}</p>")

        if "error" in evals:
            self.evals.setHtml(f"<p style='color:{T.TEXT_FAINT};'>No evaluation results ({evals['error']}). Run python evals/run_evals.py.</p>")
        else:
            items = []
            for k, fn in EVAL_LABELS.items():
                if k in evals:
                    try:
                        items.append(fn(evals[k]))
                    except Exception:
                        items.append(f"{k}: {json.dumps(evals[k])[:120]}")
            self.evals.setHtml("<ul>" + "".join(f"<li style='margin-bottom:4px;'>{i}</li>" for i in items) + "</ul>")
