"""Reminders & tasks: a planner, not a form above a table.

Left, views with counts: Today, Upcoming, Overdue, Repeating, Done, Cancelled. At the top, one quick-add
line ("what" + "in how long", Enter adds it). The agenda groups reminders by day with times on the left.
Right, the current task as a checklist: ticking a step rewrites the step list through update_task_state
(so it is audited and Prometheus sees the same state in every conversation). Reminders go through the
schedule_task / cancel_scheduled tools.
"""

from __future__ import annotations

import datetime
from typing import Dict, List

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .. import icons
from .. import theme as T
from ..feedback import notify
from ..widgets import Page, label

STATUSES = ["idle", "in_progress", "blocked", "done"]
VIEWS = [("today", "Today", "sun"), ("upcoming", "Upcoming", "clock"), ("overdue", "Overdue", "alert"), ("repeating", "Repeating", "retry"), ("done", "Delivered", "check"), ("cancelled", "Cancelled", "trash")]
DONE_PREFIX = "[x] "


def when_text(iso: str, now: datetime.datetime) -> str:
    """'in 2 h · Tue 17 Nov 18:08' style; falls back to the raw value."""
    try:
        t = datetime.datetime.fromisoformat(str(iso))
    except ValueError:
        return str(iso)
    secs = (t - now).total_seconds()
    if secs < 0:
        rel = "overdue"
    elif secs < 3600:
        rel = f"in {max(1, int(secs // 60))} min"
    elif secs < 86400:
        rel = f"in {secs / 3600:.0f} h"
    else:
        rel = f"in {secs / 86400:.0f} d"
    return f"{rel} · {t:%a %d %b %H:%M}"


def repeat_text(seconds) -> str:
    if not seconds:
        return "once"
    s = int(seconds)
    for unit, n in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if s % n == 0:
            k = s // n
            return f"every {unit}" if k == 1 else f"every {k} {unit}s"
    return f"every {s} s"


def classify(jobs: List[dict], now: datetime.datetime) -> Dict[str, List[dict]]:
    out: Dict[str, List[dict]] = {k: [] for k, _, _ in VIEWS}
    for j in jobs:
        st = j.get("status")
        if st == "delivered":
            out["done"].append(j)
            continue
        if st == "cancelled":
            out["cancelled"].append(j)
            continue
        try:
            t = datetime.datetime.fromisoformat(str(j.get("next_fire")))
        except ValueError:
            continue
        if t < now:
            out["overdue"].append(j)
        elif t.date() == now.date():
            out["today"].append(j)
        else:
            out["upcoming"].append(j)
        if j.get("recurrence_seconds"):
            out["repeating"].append(j)
    for k in out:
        out[k].sort(key=lambda j: str(j.get("next_fire", "")), reverse=k in ("done", "cancelled"))
    return out


class TasksPage(Page):
    title = "Reminders & tasks"
    header = "none"
    margins = (0, 0, 0, 0)

    def __init__(self, core, parent=None):
        super().__init__(core, parent)
        self.view = "today"
        self.groups: Dict[str, List[dict]] = {}
        split = QSplitter()
        split.setHandleWidth(1)
        split.setChildrenCollapsible(False)

        rail = QFrame()
        rail.setObjectName("rail")
        rail.setMinimumWidth(200)
        rail.setMaximumWidth(250)
        rl = QVBoxLayout(rail)
        rl.setContentsMargins(16, 22, 12, 16)
        rl.setSpacing(10)
        rl.addWidget(label("Planner", "h1"))
        rl.addWidget(label("Reminders survive restarts. Missed ones arrive once, when Prometheus next starts.", "faint"))
        self.rail = QListWidget()
        self.rail.setObjectName("rail")
        self.rail.setIconSize(QSize(16, 16))
        self.rail.setAccessibleName("Reminder views")
        for key, name, ic in VIEWS:
            it = QListWidgetItem(icons.icon(ic, T.TEXT_SECONDARY), name)
            it.setData(Qt.ItemDataRole.UserRole, key)
            self.rail.addItem(it)
        self.rail.setCurrentRow(0)
        self.rail.currentItemChanged.connect(lambda it, _p: self._set_view(it.data(Qt.ItemDataRole.UserRole) if it else "today"))
        rl.addWidget(self.rail, 1)
        split.addWidget(rail)

        # agenda
        mid = QWidget()
        ml = QVBoxLayout(mid)
        ml.setContentsMargins(28, 22, 28, 16)
        ml.setSpacing(12)
        quick = QFrame()
        quick.setObjectName("composerBox")
        ql = QHBoxLayout(quick)
        ql.setContentsMargins(12, 6, 6, 6)
        ql.setSpacing(8)
        ic = label()
        ic.setPixmap(icons.pixmap("plus", T.ACCENT, 16))
        ql.addWidget(ic)
        self.text = QLineEdit()
        self.text.setStyleSheet("QLineEdit { background: transparent; border: none; padding: 6px 2px; }")
        self.text.setPlaceholderText("Remind me to…")
        self.text.setAccessibleName("Reminder text")
        ql.addWidget(self.text, 1)
        self.when = QLineEdit()
        self.when.setPlaceholderText("in 2h")
        self.when.setToolTip("How long from now: 10m, 2h, 1d (seconds s, minutes m, hours h, days d)")
        self.when.setAccessibleName("When")
        self.when.setMaximumWidth(110)
        ql.addWidget(self.when)
        self.recurring = QCheckBox("repeat")
        self.recurring.setToolTip("Repeat at that interval")
        ql.addWidget(self.recurring)
        add = QPushButton("Add")
        add.setObjectName("primary")
        add.clicked.connect(self._add)
        ql.addWidget(add)
        self.text.returnPressed.connect(lambda: self.when.setFocus() if not self.when.text().strip() else self._add())
        self.when.returnPressed.connect(self._add)
        ml.addWidget(quick)
        self.view_title = label("Today", "h2")
        self.view_title.setStyleSheet("font-size: 14pt;")
        ml.addWidget(self.view_title)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.Shape.NoFrame)
        self.agenda_host = QWidget()
        self.agenda = QVBoxLayout(self.agenda_host)
        self.agenda.setContentsMargins(0, 0, 8, 0)
        self.agenda.setSpacing(4)
        sa.setWidget(self.agenda_host)
        ml.addWidget(sa, 1)
        split.addWidget(mid)

        # current task
        side = QFrame()
        side.setObjectName("inspector")
        side.setMinimumWidth(300)
        side.setMaximumWidth(420)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(18, 22, 18, 16)
        sl.setSpacing(10)
        sl.addWidget(label("CURRENT TASK", "eyebrow"))
        sl.addWidget(label("The long-running work Prometheus keeps in mind in every conversation.", "faint"))
        self.goal = QLineEdit()
        self.goal.setPlaceholderText("Goal, for example: ship the rocket-sim drag model")
        self.goal.setAccessibleName("Goal")
        sl.addWidget(self.goal)
        self.status = QComboBox()
        self.status.setAccessibleName("Status")
        for s in STATUSES:
            self.status.addItem(s.replace("_", " ").capitalize(), s)
        sl.addWidget(self.status)
        self.steps_host = QVBoxLayout()
        self.steps_host.setSpacing(4)
        sl.addLayout(self.steps_host)
        self.new_step = QLineEdit()
        self.new_step.setPlaceholderText("Add a step and press Enter")
        self.new_step.setAccessibleName("New step")
        self.new_step.returnPressed.connect(self._add_step)
        sl.addWidget(self.new_step)
        self.note = QLineEdit()
        self.note.setPlaceholderText("Add a note (optional)")
        self.note.setAccessibleName("Note")
        sl.addWidget(self.note)
        row = QHBoxLayout()
        save = QPushButton("Save task")
        save.clicked.connect(self._save_task)
        row.addWidget(save)
        plan = QPushButton(icons.icon("chat", T.TEXT_SECONDARY), " Ask Prometheus to plan it")
        plan.setObjectName("ghost")
        plan.setToolTip("Sends the goal to the Companion; Prometheus records steps with update_task_state")
        plan.clicked.connect(self._ask_plan)
        row.addWidget(plan)
        sl.addLayout(row)
        self.task_msg = label("", "faint")
        sl.addWidget(self.task_msg)
        self.notes = label("", "faint")
        sl.addWidget(self.notes)
        sl.addStretch(1)
        split.addWidget(side)
        split.setStretchFactor(1, 1)
        split.setSizes([220, 700, 340])
        self.content.addWidget(split, 1)
        self.steps: List[str] = []

    # ----- reminders -----
    def _set_view(self, key: str) -> None:
        self.view = key
        self._render_agenda()

    def refresh(self) -> None:
        now = datetime.datetime.now()
        jobs = self.core.p.scheduler_engine.list_jobs(include_delivered=True) if hasattr(self.core, "p") else self.core.scheduled()
        self.groups = classify(jobs, now)
        for i in range(self.rail.count()):
            it = self.rail.item(i)
            key = it.data(Qt.ItemDataRole.UserRole)
            name = next(v[1] for v in VIEWS if v[0] == key)
            n = len(self.groups.get(key, []))
            it.setText(f"{name}   {n}" if n else name)
        self._render_agenda()
        self._load_task()

    def _clear(self, lay) -> None:
        while lay.count():
            it = lay.takeAt(0)
            if it.widget():
                it.widget().setParent(None)
            elif it.layout():
                self._clear(it.layout())

    def _render_agenda(self) -> None:
        now = datetime.datetime.now()
        self._clear(self.agenda)
        name = next(v[1] for v in VIEWS if v[0] == self.view)
        jobs = self.groups.get(self.view, [])
        self.view_title.setText(f"{name} · {len(jobs)}" if jobs else name)
        if not jobs:
            empty = {
                "today": "Nothing more today. Add a reminder above, or say “remind me in 2 hours to…” in a conversation.",
                "upcoming": "Nothing scheduled after today.",
                "overdue": "✓ Nothing overdue.",
                "repeating": "No repeating reminders. Tick “repeat” when adding one.",
                "done": "No delivered reminders yet.",
                "cancelled": "Nothing cancelled.",
            }[self.view]
            self.agenda.addWidget(label(empty, "sub"))
            self.agenda.addStretch(1)
            return
        last_day = None
        for j in jobs:
            try:
                t = datetime.datetime.fromisoformat(str(j.get("next_fire")))
            except ValueError:
                t = None
            day = (("Today" if t.date() == now.date() else "Tomorrow" if t.date() == (now + datetime.timedelta(days=1)).date() else f"{t:%A %d %B}") if t else "")
            if day != last_day and self.view not in ("done", "cancelled"):
                d = label(day.upper(), "eyebrow")
                d.setContentsMargins(0, 10, 0, 2)
                self.agenda.addWidget(d)
                last_day = day
            row = QFrame()
            row.setObjectName("homeRow")
            h = QHBoxLayout(row)
            h.setContentsMargins(12, 9, 10, 9)
            h.setSpacing(14)
            tm = label(f"{t:%H:%M}" if t else "—", "mono", wrap=False)
            tm.setMinimumWidth(48)
            if self.view == "overdue":
                tm.setStyleSheet(f"color: {T.WARN};")
            h.addWidget(tm)
            v = QVBoxLayout()
            v.setSpacing
            v.addWidget(label(str(j.get("text", ""))))
            meta = (when_text(j.get("next_fire", ""), now) if j.get("status") == "scheduled" else str(j.get("status", ""))) + (f" · {repeat_text(j.get('recurrence_seconds'))}" if j.get("recurrence_seconds") else "")
            v.addWidget(label(meta, "faint"))
            h.addLayout(v, 1)
            if j.get("status") == "scheduled":
                b = QPushButton("Cancel")
                b.setObjectName("ghost")
                b.setAccessibleName(f"Cancel reminder: {j.get('text', '')}")
                b.clicked.connect(lambda _=False, jid=j.get("id", ""), txt=j.get("text", ""): self._cancel(jid, txt))
                h.addWidget(b)
            self.agenda.addWidget(row)
        self.agenda.addStretch(1)

    def _add(self) -> None:
        text, when = self.text.text().strip(), self.when.text().strip().lower().removeprefix("in ").strip()
        if not text or not when:
            notify(self, "Write what and when", "warn", "For example: “Call the supplier” in 2h.")
            return
        res = self.core.dispatch("schedule_task", when=when, text=text, recurring=self.recurring.isChecked())
        if res.get("status") == "success":
            job = res.get("job", {})
            notify(self, "Reminder added", "ok", f"{text} — {when_text(job.get('next_fire', ''), datetime.datetime.now())}" + (f", {repeat_text(job.get('recurrence_seconds'))}" if job.get("recurrence_seconds") else ""))
            self.text.clear()
            self.when.clear()
            self.recurring.setChecked(False)
            self.text.setFocus()
        else:
            notify(self, "Reminder not added", "err", res.get("message") or str(res))
        self.refresh()

    def _cancel(self, job_id: str, text: str) -> None:
        res = self.core.dispatch("cancel_scheduled", job_id=job_id)
        notify(self, "Reminder cancelled" if res.get("status") == "success" else "Could not cancel", "ok" if res.get("status") == "success" else "err", text if res.get("status") == "success" else res.get("message", ""))
        self.refresh()

    # ----- current task -----
    def _load_task(self) -> None:
        res = self.core.dispatch("read_task_state")
        state = res.get("task_state", {}) if isinstance(res, dict) else {}
        if not self.goal.hasFocus():
            self.goal.setText(state.get("goal") or "")
        self.status.setCurrentIndex(max(0, self.status.findData(state.get("status") or "idle")))
        self.steps = [str(s) for s in state.get("steps") or []]
        self._render_steps()
        notes = state.get("notes") or []
        self.notes.setText(("Latest notes:\n" + "\n".join(f"• {str(n.get('ts', ''))[5:16].replace('T', ' ')}  {n.get('note', '')}" for n in notes[-3:])) if notes else "")
        upd = state.get("updated")
        done = sum(1 for s in self.steps if s.startswith(DONE_PREFIX))
        self.task_msg.setText((f"{done} of {len(self.steps)} steps done · " if self.steps else "") + (f"updated {str(upd)[:16].replace('T', ' ')}" if upd else "No task recorded yet."))

    def _render_steps(self) -> None:
        self._clear(self.steps_host)
        for i, s in enumerate(self.steps):
            done = s.startswith(DONE_PREFIX)
            cb = QCheckBox(s[len(DONE_PREFIX):] if done else s)
            cb.setChecked(done)
            if done:
                cb.setStyleSheet(f"color: {T.TEXT_FAINT}; text-decoration: line-through;")
            cb.toggled.connect(lambda on, idx=i: self._tick(idx, on))
            self.steps_host.addWidget(cb)
        if not self.steps:
            self.steps_host.addWidget(label("No steps yet. Add them below, or ask Prometheus to plan it.", "faint"))

    def _tick(self, idx: int, on: bool) -> None:
        s = self.steps[idx]
        base = s[len(DONE_PREFIX):] if s.startswith(DONE_PREFIX) else s
        self.steps[idx] = (DONE_PREFIX + base) if on else base
        res = self.core.dispatch("update_task_state", steps=self.steps)
        if res.get("status") == "success":
            all_done = all(x.startswith(DONE_PREFIX) for x in self.steps)
            notify(self, "Step done" if on else "Step reopened", "ok", "Every step is done: set the status to Done when you are ready." if on and all_done else base)
        self._load_task()

    def _add_step(self) -> None:
        t = self.new_step.text().strip()
        if not t:
            return
        self.steps.append(t)
        self.new_step.clear()
        self.core.dispatch("update_task_state", steps=self.steps)
        self._load_task()

    def _save_task(self) -> None:
        args = {"goal": self.goal.text().strip() or None, "steps": self.steps, "status": self.status.currentData()}
        if self.note.text().strip():
            args["note"] = self.note.text().strip()
        res = self.core.dispatch("update_task_state", **args)
        notify(self, "Task saved" if res.get("status") == "success" else "Task not saved", "ok" if res.get("status") == "success" else "err", "Prometheus sees this goal in every conversation while it is set." if res.get("status") == "success" else str(res))
        self.note.clear()
        self._load_task()

    def _ask_plan(self) -> None:
        goal = self.goal.text().strip()
        if not goal:
            notify(self, "Write a goal first", "warn")
            return
        win = self.window()
        if hasattr(win, "go") and hasattr(win, "companion"):
            win.go("Companion")
            win.companion.send(f"Break this goal into a short list of concrete steps and record them as the current task with update_task_state (status in_progress): {goal}")
