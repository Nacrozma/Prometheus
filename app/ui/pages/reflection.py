"""Reflection: Prometheus's performance, told as a story from its own records.

A written headline first (what happened, how reliably, what stands out). Then the evidence: a reliability
chart (success, failure and refusal shares per tool, with the number of calls, and tools with fewer than
5 calls marked as too few to judge), each tool's most recent outcomes in order (to see whether it is
getting better or worse), model usage per provider (a floor: streamed replies may not report usage), and
the offline evaluations in words, labelled synthetic. Suggestions are for the owner; nothing changes
automatically.
"""

from __future__ import annotations

import json
import os

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from .. import theme as T
from ..widgets import Page, label, run_bg

MIN_N = 5
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
        if calls >= MIN_N and fails / max(1, calls) >= 0.3:
            out.append(f"{tool} failed {fails} of {calls} times. " + (f"Recorded lesson: {lessons[tool]}" if lessons.get(tool) else (f"Last error: {s.get('last_error')}" if s.get("last_error") else "Check its inputs in the Trust & safety audit log.")))
        if s.get("refused", 0) >= 3:
            out.append(f"{tool} was refused {s['refused']} times by policy or by you; if it is never wanted, deny it in permissions.json so it is not attempted.")
        if s.get("avg_ms", 0) > 15000 and calls >= 3:
            out.append(f"{tool} takes {s['avg_ms'] / 1000:.0f} s on average; consider whether a faster route exists.")
    return out[:8]


def headline(stats: dict) -> str:
    calls = sum(s.get("calls", 0) for s in stats.values())
    if not calls:
        return "No tool has run yet. Once Prometheus uses its tools, this page shows how reliably each one works."
    succ = sum(s.get("successes", 0) for s in stats.values())
    fails = sum(s.get("failures", 0) for s in stats.values())
    counted = succ + fails
    judged = [t for t, s in stats.items() if s.get("calls", 0) >= MIN_N]
    worst = max(judged, key=lambda t: stats[t].get("failures", 0) / max(1, stats[t]["calls"]), default=None)
    text = f"Across {calls} tool calls on {len(stats)} tools, {succ / counted:.0%} of the calls that finished succeeded." if counted else f"{calls} tool calls recorded."
    if worst and stats[worst].get("failures", 0):
        text += f" {worst} is the least reliable ({stats[worst]['failures']} of {stats[worst]['calls']} failed)."
    elif judged:
        text += " No tool with enough calls to judge has failed."
    if len(judged) < len(stats):
        text += f" {len(stats) - len(judged)} tool{'s have' if len(stats) - len(judged) != 1 else ' has'} fewer than {MIN_N} calls: too few to judge."
    return text


class ReliabilityChart(QWidget):
    """Stacked bars per tool: success, failure, refused shares; n on the right; recent outcomes strip."""

    ROW = 30

    def __init__(self):
        super().__init__()
        self.rows = []
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName("Tool reliability chart")

    def set_data(self, stats: dict) -> None:
        self.rows = sorted(stats.items(), key=lambda kv: -kv[1].get("calls", 0))[:16]
        self.setMinimumHeight(max(60, 24 + self.ROW * len(self.rows)))
        desc = "; ".join(f"{t}: {s.get('successes', 0)} succeeded, {s.get('failures', 0)} failed, {s.get('refused', 0)} refused of {s.get('calls', 0)}" for t, s in self.rows)
        self.setAccessibleDescription(desc)
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        name_w, n_w, strip_w = 150, 70, 170
        bar_w = max(80, w - name_w - n_w - strip_w - 30)
        f = QFont(self.font())
        f.setPointSizeF(9)
        p.setFont(f)
        p.setPen(QColor(T.TEXT_FAINT))
        p.drawText(QRectF(name_w, 0, bar_w, 16), Qt.AlignmentFlag.AlignLeft, "share of calls: succeeded · failed · refused")
        p.drawText(QRectF(name_w + bar_w + 10, 0, n_w, 16), Qt.AlignmentFlag.AlignLeft, "calls")
        p.drawText(QRectF(name_w + bar_w + n_w + 20, 0, strip_w, 16), Qt.AlignmentFlag.AlignLeft, "recent (oldest → newest)")
        for i, (tool, s) in enumerate(self.rows):
            y = 22 + i * self.ROW
            n = max(1, s.get("calls", 0))
            few = s.get("calls", 0) < MIN_N
            p.setPen(QColor(T.TEXT if not few else T.TEXT_SECONDARY))
            p.drawText(QRectF(0, y, name_w - 8, 20), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, tool)
            x = name_w
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(T.SURFACE_ELEVATED))
            p.drawRoundedRect(QRectF(x, y + 4, bar_w, 12), 3, 3)
            for key, colour in (("successes", T.OK), ("failures", T.ERR), ("refused", T.WARN)):
                seg = bar_w * s.get(key, 0) / n
                if seg > 0:
                    c = QColor(colour)
                    c.setAlpha(110 if few else 220)
                    p.setBrush(c)
                    p.drawRect(QRectF(x, y + 4, seg, 12))
                    x += seg
            p.setPen(QColor(T.TEXT_SECONDARY))
            p.drawText(QRectF(name_w + bar_w + 10, y, n_w, 20), Qt.AlignmentFlag.AlignVCenter, f"{s.get('calls', 0)}" + ("  few" if few else ""))
            recent = str(s.get("recent", ""))[-20:]
            sx = name_w + bar_w + n_w + 20
            p.setPen(Qt.PenStyle.NoPen)
            for j, ch in enumerate(recent):
                p.setBrush(QColor({"S": T.OK, "F": T.ERR, "R": T.WARN}.get(ch, T.BORDER_STRONG)))
                p.drawRoundedRect(QRectF(sx + j * 8, y + 5, 6, 10), 1.5, 1.5)
        p.end()


class UsageBars(QWidget):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.setAccessibleName("Model usage per provider")

    def set_data(self, provs: dict) -> None:
        self.rows = sorted(provs.items(), key=lambda kv: -kv[1].get("requests", 0))
        self.setMinimumHeight(max(30, 28 * len(self.rows)))
        self.setAccessibleDescription("; ".join(f"{k}: {v.get('requests', 0)} requests" for k, v in self.rows))
        self.update()

    def paintEvent(self, _e) -> None:
        if not self.rows:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        top = max(1, max(v.get("requests", 0) for _, v in self.rows))
        w = self.width() - 260
        for i, (name, v) in enumerate(self.rows):
            y = i * 28
            p.setPen(QColor(T.TEXT))
            p.drawText(QRectF(0, y, 100, 20), Qt.AlignmentFlag.AlignVCenter, name)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(T.ACCENT))
            p.drawRoundedRect(QRectF(104, y + 5, max(2, w * v.get("requests", 0) / top), 10), 3, 3)
            p.setPen(QColor(T.TEXT_SECONDARY))
            p.drawText(QRectF(110 + w, y, 150, 20), Qt.AlignmentFlag.AlignVCenter, f"{v.get('requests', 0):,} req · {v.get('prompt_tokens', 0) + v.get('completion_tokens', 0):,} tok")
        p.end()


class ReflectionPage(Page):
    title = "Reflection"
    header = "none"
    scroll = True
    margins = (40, 30, 40, 24)

    def __init__(self, core, parent=None):
        super().__init__(core, parent)
        self.content.addWidget(label("REFLECTION", "eyebrow"))
        self.head = label("", "h1")
        self.head.setStyleSheet(f"font-size: 17pt; font-family: {T.FONT_DISPLAY};")
        self.head.setMaximumWidth(980)
        self.content.addWidget(self.head)
        self.sub = label("From Prometheus's own records on this computer. Synthetic evaluations are labelled as such.", "faint")
        self.content.addWidget(self.sub)

        self.content.addSpacing(10)
        self.content.addWidget(label("WHAT TO IMPROVE", "eyebrow"))
        self.sug = label("", "sub")
        self.sug.setMaximumWidth(980)
        self.content.addWidget(self.sug)

        self.content.addSpacing(10)
        self.content.addWidget(label("TOOL RELIABILITY", "eyebrow"))
        self.chart = ReliabilityChart()
        self.content.addWidget(self.chart)
        self.lessons = label("", "faint")
        self.content.addWidget(self.lessons)

        row = QHBoxLayout()
        row.setSpacing(40)
        a = QVBoxLayout()
        a.addWidget(label("MODEL USAGE · LAST 30 DAYS", "eyebrow"))
        self.usage = UsageBars()
        a.addWidget(self.usage)
        self.usage_note = label("", "faint")
        a.addWidget(self.usage_note)
        a.addStretch(1)
        b = QVBoxLayout()
        b.addWidget(label("EVALUATIONS (SYNTHETIC, OFFLINE)", "eyebrow"))
        self.evals = label("", "sub")
        b.addWidget(self.evals)
        b.addWidget(label("Scripted scenarios (evals/run_evals.py) against fixed cases: not a measure of real-world performance.", "faint"))
        b.addStretch(1)
        row.addLayout(a, 1)
        row.addLayout(b, 1)
        self.content.addLayout(row)
        self.content.addStretch(1)

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

        run_bg(load, self._fill, lambda m: self.head.setText("Could not read the records: " + m.splitlines()[0]), owner=self)

    def _fill(self, data) -> None:
        stats, lessons, usage, evals = data
        self.head.setText(headline(stats))
        sug = suggestions(stats, lessons)
        self.sug.setText("\n".join(f"→ {s}" for s in sug) if sug else ("Nothing stands out: no tool with enough calls fails repeatedly." if stats else "Suggestions appear once Prometheus has used its tools."))
        self.chart.set_data(stats)
        les = [f"{t}: {l}" for t, l in lessons.items() if l]
        self.lessons.setText(("Lessons recorded from repeated failures:\n" + "\n".join(les)) if les else "")
        provs = (usage or {}).get("providers", {}) if isinstance(usage, dict) else {}
        self.usage.set_data(provs)
        self.usage_note.setText("Counts from the usage log; streamed replies may not report usage, so these are a floor. No prices are shown: provider pricing is not verified here." if provs else ((usage.get("note") or usage.get("message")) if isinstance(usage, dict) else "") or "No model requests recorded in the last 30 days.")
        if "error" in evals:
            self.evals.setText(f"No evaluation results ({evals['error']}). Run python evals/run_evals.py.")
        else:
            items = []
            for k, fn in EVAL_LABELS.items():
                if k in evals:
                    try:
                        items.append(fn(evals[k]))
                    except Exception:
                        items.append(f"{k}: {json.dumps(evals[k])[:120]}")
            self.evals.setText("\n".join(f"• {i}" for i in items))
