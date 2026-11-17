"""Home: the command centre. Everything on it comes from Prometheus's own data on this computer:
the router, conversations, reminders, the task record, memory, skills, the audit log and tool stats.
Sections can be hidden (Customize); nothing here is a placeholder."""

from __future__ import annotations

import datetime
from typing import Any, Dict, List

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QLineEdit, QMenu, QPushButton, QVBoxLayout, QWidget

from .. import icons
from .. import theme as T
from ..sun import SolarGlyph
from ..widgets import Card, EmptyState, Page, label, pill, run_bg

SECTIONS = [
    ("conversations", "Recent conversations"),
    ("reminders", "Upcoming reminders"),
    ("task", "Current task"),
    ("providers", "Provider health"),
    ("engineering", "Engineering & Forge"),
    ("memory", "Memory"),
    ("activity", "Recent activity"),
]


def greeting(now: datetime.datetime) -> str:
    h = now.hour
    return "Good morning." if 5 <= h < 12 else "Good afternoon." if 12 <= h < 18 else "Good evening."


def gather(core, conversations) -> Dict[str, Any]:
    """Collect what Home shows (runs off the GUI thread). Each part fails on its own."""
    out: Dict[str, Any] = {}

    def part(key, fn):
        try:
            out[key] = fn()
        except Exception as e:
            out[key] = {"error": f"{type(e).__name__}: {e}"}

    part("conversations", lambda: [c for c in conversations.list() if c["messages"]][:5])
    part("reminders", lambda: sorted([j for j in core.scheduled() if j.get("status") == "scheduled"], key=lambda j: str(j.get("next_fire", "")))[:5])
    part("task", lambda: core.dispatch("read_task_state").get("task_state", {}))
    part("router", core.router_status)
    part("memory", core.memory_stats)
    part("skills", core.skills)
    part("patches", core.pending_patches)
    part("activity", lambda: list(reversed(core.audit_tail(6))))
    part("stats", core.tool_stats)
    return out


class HomePage(Page):
    title = "Command centre"
    subtitle = ""
    scroll = True

    def __init__(self, core, settings, conversations, window, parent=None):
        super().__init__(core, parent)
        self.settings, self.conversations, self.window_ref = settings, conversations, window
        customize = QPushButton(icons.icon("settings", T.TEXT_SECONDARY), " Customize")
        customize.setObjectName("ghost")
        menu = QMenu(customize)
        for key, name in SECTIONS:
            a = menu.addAction(name)
            a.setCheckable(True)
            a.setChecked(key not in settings.get("home_hidden"))
            a.toggled.connect(lambda on, k=key: self._toggle_section(k, on))
        customize.setMenu(menu)
        self.actions.addWidget(customize)

        # hero: the sun, a greeting, the real status, and a quick ask
        hero = Card()
        hero.setObjectName("hero")
        hl = QHBoxLayout()
        hl.setSpacing(22)
        self.sun = SolarGlyph(112)
        hl.addWidget(self.sun, 0, Qt.AlignmentFlag.AlignVCenter)
        col = QVBoxLayout()
        col.setSpacing(6)
        self.greet = label("", "h1")
        col.addWidget(self.greet)
        self.status = label("", "sub")
        col.addWidget(self.status)
        ask = QHBoxLayout()
        self.ask = QLineEdit()
        self.ask.setPlaceholderText("Ask Prometheus… (opens the Companion)")
        self.ask.setAccessibleName("Ask Prometheus")
        self.ask.returnPressed.connect(self._ask)
        ask.addWidget(self.ask, 1)
        go = QPushButton(icons.icon("send", T.ON_ACCENT), " Ask")
        go.setObjectName("primary")
        go.clicked.connect(self._ask)
        ask.addWidget(go)
        col.addLayout(ask)
        quick = QHBoxLayout()
        quick.setSpacing(6)
        for text, ic, target in (("New conversation", "plus", "new"), ("Engineering", "engineering", "Engineering"), ("Reminder", "clock", "Reminders & tasks"), ("Workspace", "workspace", "Workspace"), ("Trust & safety", "shield", "Trust & safety")):
            b = QPushButton(icons.icon(ic, T.TEXT_SECONDARY), f" {text}".replace("&", "&&"))
            b.setObjectName("ghost")
            b.clicked.connect(lambda _=False, t=target: self._quick(t))
            quick.addWidget(b)
        quick.addStretch(1)
        col.addLayout(quick)
        hl.addLayout(col, 1)
        hero.body.addLayout(hl)
        self.content.addWidget(hero)

        self.grid = QGridLayout()
        self.grid.setSpacing(14)
        self.content.addLayout(self.grid)
        self.content.addStretch(1)
        self.cards: Dict[str, Card] = {}
        icon_for = {"conversations": "chat", "reminders": "clock", "task": "tasks", "providers": "plug", "engineering": "forge", "memory": "memory", "activity": "shield"}
        for key, name in SECTIONS:
            c = Card(name, icon_name=icon_for[key])
            c.inner = QVBoxLayout()  # type: ignore[attr-defined]
            c.inner.setSpacing(6)  # type: ignore[attr-defined]
            c.body.addLayout(c.inner)  # type: ignore[attr-defined]
            self.cards[key] = c
        self._layout_cards()

    # ----- layout -----
    def _toggle_section(self, key: str, on: bool) -> None:
        hidden = [k for k in self.settings.get("home_hidden") if k != key] + ([] if on else [key])
        self.settings.set("home_hidden", hidden)
        self._layout_cards()

    def _layout_cards(self) -> None:
        for c in self.cards.values():
            self.grid.removeWidget(c)
            c.setVisible(False)
        hidden = set(self.settings.get("home_hidden"))
        shown = [k for k, _ in SECTIONS if k not in hidden]
        for i, key in enumerate(shown):
            self.grid.addWidget(self.cards[key], i // 2, i % 2)
            self.cards[key].setVisible(True)

    def set_reduced_motion(self, reduced: bool) -> None:
        self.sun.set_reduced_motion(reduced)

    # ----- actions -----
    def _ask(self) -> None:
        text = self.ask.text().strip()
        if not text:
            return
        self.ask.clear()
        self.window_ref.go("Companion")
        self.window_ref.companion.send(text)

    def _quick(self, target: str) -> None:
        if target == "new":
            self.window_ref._new_conversation()
        else:
            self.window_ref.go(target)

    # ----- data -----
    def refresh(self) -> None:
        now = datetime.datetime.now()
        self.greet.setText(greeting(now))
        r = self.core.router
        if r.configured:
            if r.last_used_provider:
                self.status.setText(f"{now:%A %d %B} · Last answered by {r.last_used_provider} · {r.last_used_model}")
            else:
                self.status.setText(f"{now:%A %d %B} · Provider: {r.provider} · {r.default_model} (not used yet this session)")
            self.sun.set_state("IDLE")
        else:
            self.status.setText(f"{now:%A %d %B} · No model provider yet: add a key in Settings, or start Ollama.")
            self.sun.set_state("OFFLINE")
        run_bg(lambda: gather(self.core, self.conversations), self._fill, lambda m: self.status.setText(f"Could not load Home: {m.splitlines()[0]}"), owner=self)

    @staticmethod
    def _clear(lay) -> None:
        while lay.count():
            it = lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
            elif it.layout() is not None:
                HomePage._clear(it.layout())

    def _row(self, lay, title: str, detail: str = "", on_click=None, tone: str = "") -> None:
        row = QHBoxLayout()
        if on_click:
            b = QPushButton(title)
            b.setObjectName("link")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(on_click)
            row.addWidget(b, 1)
        else:
            t = label(title)
            if tone:
                t.setStyleSheet(f"color: {T.TONES.get(tone, T.TEXT)};")
            row.addWidget(t, 1)
        if detail:
            row.addWidget(label(detail, "faint", wrap=False))
        lay.addLayout(row)

    def _error(self, lay, data) -> bool:
        if isinstance(data, dict) and "error" in data:
            lay.addWidget(label(f"Unavailable: {data['error']}", "err"))
            return True
        return False

    def _fill(self, d: Dict[str, Any]) -> None:
        for c in self.cards.values():
            self._clear(c.inner)  # type: ignore[attr-defined]

        lay = self.cards["conversations"].inner  # type: ignore[attr-defined]
        convs = d.get("conversations")
        if not self._error(lay, convs):
            if not convs:
                lay.addWidget(EmptyState("chat", "No conversations yet", "Ask something above to start one."))
            for c in convs or []:
                self._row(lay, c["title"], c["updated"][5:16].replace("T", " "), lambda _=False, cid=c["id"]: (self.window_ref.go("Companion"), self.window_ref.companion.open_conversation(cid)))

        lay = self.cards["reminders"].inner  # type: ignore[attr-defined]
        rem = d.get("reminders")
        if not self._error(lay, rem):
            if not rem:
                lay.addWidget(label("Nothing scheduled. Ask Prometheus to remind you, or add one in Reminders & tasks.", "faint"))
            for j in rem or []:
                self._row(lay, j.get("text", ""), str(j.get("next_fire", ""))[:16].replace("T", " ") + ("  ↻" if j.get("recurrence_seconds") else ""))

        lay = self.cards["task"].inner  # type: ignore[attr-defined]
        task = d.get("task")
        if not self._error(lay, task):
            goal = (task or {}).get("goal")
            if not goal:
                lay.addWidget(label("No long-running task is set. Prometheus records one when you start multi-step work.", "faint"))
            else:
                lay.addWidget(label(goal))
                steps = task.get("steps") or []
                status = str(task.get("status") or "idle").replace("_", " ")
                lay.addWidget(label(f"Status: {status} · {len(steps)} steps" if steps else f"Status: {status}", "faint"))
                for st in steps[:4]:
                    lay.addWidget(label(f"• {st}", "faint"))

        lay = self.cards["providers"].inner  # type: ignore[attr-defined]
        router = d.get("router") or {}
        if not self._error(lay, router):
            active = router.get("active_providers") or []
            cool = router.get("providers_on_cooldown") or {}
            if not active:
                lay.addWidget(label("No provider configured. Settings → Providers.", "warn"))
            for name in active:
                row = QHBoxLayout()
                row.addWidget(label(name), 1)
                secs = cool.get(name) if isinstance(cool, dict) else None
                row.addWidget(pill(f"cooling down {int(secs)}s" if secs else ("in use" if name == router.get("last_used_provider") else "available"), "warn" if secs else "ok" if name == router.get("last_used_provider") else "neutral"))
                lay.addLayout(row)
            if "ollama" in active:
                lay.addWidget(label("Ollama is listed when configured; it answers only if its server is running on this computer.", "faint"))

        lay = self.cards["engineering"].inner  # type: ignore[attr-defined]
        skills, patches = d.get("skills"), d.get("patches")
        if not self._error(lay, skills):
            enabled = [s for s in skills or [] if s.get("enabled", True)]
            self._row(lay, f"{len(enabled)} learned skills", "Forge", lambda _=False: self.window_ref.go("Forge"))
        if not self._error(lay, patches):
            self._row(lay, f"{len(patches or [])} self-patches waiting for review", "Forge", lambda _=False: self.window_ref.go("Forge"), tone="warn" if patches else "")
        self._row(lay, "17 engineering calculators", "Engineering", lambda _=False: self.window_ref.go("Engineering"))

        lay = self.cards["memory"].inner  # type: ignore[attr-defined]
        mem = d.get("memory")
        if not self._error(lay, mem):
            m = mem or {}
            active = (m.get("facts_by_status") or {}).get("active", m.get("facts", 0))
            self._row(lay, f"{active} active facts · {m.get('entities', 0)} entities · {m.get('relations', 0)} relations", "", lambda _=False: self.window_ref.go("Memory"))

        lay = self.cards["activity"].inner  # type: ignore[attr-defined]
        act = d.get("activity")
        if not self._error(lay, act):
            if not act:
                lay.addWidget(label("No tool has run yet. Every tool call is recorded in the audit log.", "faint"))
            for e in act or []:
                outcome = str(e.get("outcome", ""))
                tone = "ok" if outcome == "success" else "warn" if outcome in ("refused", "denied", "cancelled") else "err" if outcome == "error" else ""
                self._row(lay, f"{e.get('tool', '')} · {outcome}", str(e.get("ts", ""))[11:16], tone=tone)
            stats = d.get("stats")
            if isinstance(stats, dict) and stats and "error" not in stats:
                calls = sum(int(v.get("calls", 0)) for v in stats.values() if isinstance(v, dict))
                fails = sum(int(v.get("failures", 0)) for v in stats.values() if isinstance(v, dict))
                lay.addWidget(label(f"All time: {calls} tool calls, {fails} failed.", "faint"))
