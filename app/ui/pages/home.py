"""Home: the first expression of Prometheus. Not a dashboard of equal cards: a solar welcome with a real
ask box, then what matters, in order: what needs you, where to continue, today's reminders, and a quiet
line about Prometheus's state. Every item comes from Prometheus's own data on this computer; sections
can be hidden (Customize)."""

from __future__ import annotations

import datetime
from typing import Any, Dict, List

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLineEdit, QMenu, QPushButton, QVBoxLayout, QWidget

from .. import icons
from .. import theme as T
from ..sun import SolarGlyph
from ..widgets import Page, label, run_bg

SECTIONS = [("attention", "Needs you"), ("continue", "Continue"), ("today", "Today and next"), ("glance", "Prometheus at a glance")]
STARTERS = [("Plan", "Help me plan "), ("Calculate", "Calculate "), ("Review a project", "Review the project in my workspace called "), ("Remember", "Remember that ")]


def greeting(now: datetime.datetime) -> str:
    h = now.hour
    return "Good morning." if 5 <= h < 12 else "Good afternoon." if 12 <= h < 18 else "Good evening."


def gather(core, conversations, data_dir: str) -> Dict[str, Any]:
    """Collect what Home shows (off the GUI thread). Each part fails on its own."""
    out: Dict[str, Any] = {}

    def part(key, fn):
        try:
            out[key] = fn()
        except Exception as e:
            out[key] = {"error": f"{type(e).__name__}: {e}"}

    part("conversations", lambda: [c for c in conversations.list() if c["messages"]][:3])
    part("reminders", lambda: sorted([j for j in core.scheduled() if j.get("status") == "scheduled"], key=lambda j: str(j.get("next_fire", "")))[:6])
    part("task", lambda: core.dispatch("read_task_state").get("task_state", {}))
    part("patches", core.pending_patches)
    part("stats", core.tool_stats)
    part("memory", core.memory_stats)
    part("skills", core.skills)

    def missions():
        from ...services.forge_missions import MissionLog

        return MissionLog(data_dir).list()[:1]

    part("missions", missions)
    return out


def attention_items(d: Dict[str, Any], router, now: datetime.datetime) -> List[Dict[str, str]]:
    """Real things that need the owner, most important first."""
    items = []
    if not router.configured:
        items.append({"title": "No model provider yet", "body": "Add a key or start Ollama so Prometheus can think.", "go": "Settings", "tone": "warn"})
    for j in d.get("reminders") if isinstance(d.get("reminders"), list) else []:
        try:
            if datetime.datetime.fromisoformat(str(j.get("next_fire"))) < now:
                items.append({"title": f"Overdue: {j.get('text', '')}", "body": "It is delivered at the next check (every 15 s while Prometheus runs).", "go": "Reminders & tasks", "tone": "warn"})
        except ValueError:
            pass
    patches = d.get("patches")
    if isinstance(patches, list) and patches:
        items.append({"title": f"{len(patches)} self-patch{'es' if len(patches) > 1 else ''} waiting for review", "body": "Prometheus proposed changes to its own code.", "go": "Forge", "tone": "accent"})
    stats = d.get("stats")
    if isinstance(stats, dict) and "error" not in stats:
        for tool, s in stats.items():
            calls, fails = s.get("calls", 0), s.get("failures", 0)
            if calls >= 5 and fails / max(1, calls) >= 0.3:
                items.append({"title": f"{tool} keeps failing", "body": f"{fails} of {calls} calls failed.", "go": "Reflection", "tone": "err"})
    return items


class HomePage(Page):
    title = "Home"
    header = "none"
    scroll = True
    margins = (36, 28, 36, 24)

    def __init__(self, core, settings, conversations, window, parent=None):
        super().__init__(core, parent)
        self.settings, self.conversations, self.window_ref = settings, conversations, window

        # ----- the welcome -----
        hero = QFrame()
        hero.setObjectName("hero")
        hl = QHBoxLayout(hero)
        hl.setContentsMargins(30, 26, 30, 26)
        hl.setSpacing(28)
        self.sun = SolarGlyph(168)
        hl.addWidget(self.sun, 0, Qt.AlignmentFlag.AlignVCenter)
        col = QVBoxLayout()
        col.setSpacing(8)
        top = QHBoxLayout()
        self.greet = label("", "h1", wrap=False)
        self.greet.setStyleSheet(f"font-size: 24pt; font-family: {T.FONT_DISPLAY};")
        top.addWidget(self.greet, 1)
        customize = QPushButton(icons.icon("settings", T.TEXT_FAINT), " Customize")
        customize.setObjectName("ghost")
        customize.setToolTip("Choose which parts of Home you see")
        menu = QMenu(customize)
        for key, name in SECTIONS:
            a = menu.addAction(name)
            a.setCheckable(True)
            a.setChecked(key not in settings.get("home_hidden"))
            a.toggled.connect(lambda on, k=key: self._toggle_section(k, on))
        customize.setMenu(menu)
        top.addWidget(customize, 0, Qt.AlignmentFlag.AlignTop)
        col.addLayout(top)
        self.status = label("", "sub")
        col.addWidget(self.status)
        box = QFrame()
        box.setObjectName("composerBox")
        bl = QHBoxLayout(box)
        bl.setContentsMargins(14, 6, 6, 6)
        self.ask = QLineEdit()
        self.ask.setStyleSheet("QLineEdit { background: transparent; border: none; font-size: 11pt; padding: 6px 2px; }")
        self.ask.setPlaceholderText("Ask Prometheus anything…")
        self.ask.setAccessibleName("Ask Prometheus")
        self.ask.returnPressed.connect(self._ask)
        bl.addWidget(self.ask, 1)
        go = QPushButton(icons.icon("send", T.ON_ACCENT), " Ask")
        go.setObjectName("primary")
        go.clicked.connect(self._ask)
        bl.addWidget(go)
        col.addWidget(box)
        chips = QHBoxLayout()
        chips.setSpacing(6)
        for text, prefix in STARTERS:
            b = QPushButton(text)
            b.setObjectName("chip")
            b.setToolTip(f"Starts your message with “{prefix.strip()}…”")
            b.clicked.connect(lambda _=False, p=prefix: (self.ask.setText(p), self.ask.setFocus()))
            chips.addWidget(b)
        chips.addStretch(1)
        col.addLayout(chips)
        hl.addLayout(col, 1)
        self.content.addWidget(hero)

        # ----- what matters, in two unequal columns -----
        cols = QHBoxLayout()
        cols.setSpacing(28)
        left, right = QVBoxLayout(), QVBoxLayout()
        left.setSpacing(22)
        right.setSpacing(22)
        self.blocks: Dict[str, QWidget] = {}
        for key, name, where in (("continue", "Continue", left), ("today", "Today and next", left), ("attention", "Needs you", right), ("glance", "Prometheus at a glance", right)):
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(8)
            v.addWidget(label(name.upper(), "eyebrow"))
            inner = QVBoxLayout()
            inner.setSpacing(6)
            v.addLayout(inner)
            w.inner = inner  # type: ignore[attr-defined]
            where.addWidget(w)
            self.blocks[key] = w
        left.addStretch(1)
        right.addStretch(1)
        cols.addLayout(left, 3)
        cols.addLayout(right, 2)
        self.content.addLayout(cols)
        self.content.addStretch(1)
        self._apply_hidden()

    # ----- layout -----
    def _toggle_section(self, key: str, on: bool) -> None:
        hidden = [k for k in self.settings.get("home_hidden") if k != key] + ([] if on else [key])
        self.settings.set("home_hidden", hidden)
        self._apply_hidden()

    def _apply_hidden(self) -> None:
        hidden = set(self.settings.get("home_hidden"))
        for k, w in self.blocks.items():
            w.setVisible(k not in hidden)

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

    # ----- data -----
    def refresh(self) -> None:
        now = datetime.datetime.now()
        self.greet.setText(greeting(now))
        r = self.core.router
        if r.configured:
            who = f"{r.last_used_provider} · {r.last_used_model}" if r.last_used_provider else f"{r.provider} · {r.default_model} (not used yet this session)"
            self.status.setText(f"{now:%A %d %B}. Ready, thinking with {who}.")
            self.sun.set_state("IDLE")
        else:
            self.status.setText(f"{now:%A %d %B}. I can't think yet: no model provider is connected.")
            self.sun.set_state("OFFLINE")
        run_bg(lambda: gather(self.core, self.conversations, self.core.paths()["data"]), self._fill, lambda m: self.status.setText(f"Could not load Home: {m.splitlines()[0]}"), owner=self)

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

    def _item(self, lay, icon_name: str, title: str, body: str, action: str = "", on_click=None, tone: str = "accent") -> None:
        row = QFrame()
        row.setObjectName("homeRow")
        h = QHBoxLayout(row)
        h.setContentsMargins(14, 10, 12, 10)
        h.setSpacing(12)
        ic = label()
        ic.setPixmap(icons.pixmap(icon_name, T.TONES.get(tone, T.ACCENT), 18))
        h.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        v = QVBoxLayout()
        v.setSpacing(2)
        v.addWidget(label(title))
        if body:
            v.addWidget(label(body, "faint"))
        h.addLayout(v, 1)
        if action and on_click:
            b = QPushButton(action)
            b.setObjectName("ghost")
            b.setAccessibleName(f"{action}: {title}")
            b.clicked.connect(on_click)
            h.addWidget(b, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(row)

    def _fill(self, d: Dict[str, Any]) -> None:
        for w in self.blocks.values():
            self._clear(w.inner)  # type: ignore[attr-defined]
        now = datetime.datetime.now()
        go = self.window_ref.go

        lay = self.blocks["attention"].inner  # type: ignore[attr-defined]
        items = attention_items(d, self.core.router, now)
        if not items:
            calm = label("✓ All clear. Nothing is waiting for you.", "sub")
            calm.setStyleSheet(f"color: {T.OK};")
            lay.addWidget(calm)
        for it in items:
            self._item(lay, "alert" if it["tone"] in ("warn", "err") else "bell", it["title"], it["body"], "Open", lambda _=False, t=it["go"]: go(t), it["tone"])

        lay = self.blocks["continue"].inner  # type: ignore[attr-defined]
        convs = d.get("conversations") if isinstance(d.get("conversations"), list) else []
        task = d.get("task") if isinstance(d.get("task"), dict) else {}
        missions = d.get("missions") if isinstance(d.get("missions"), list) else []
        if convs:
            c = convs[0]
            self._item(lay, "chat", c["title"], c["preview"][:110] or f"{c['messages']} messages", "Resume", lambda _=False, cid=c["id"]: (go("Companion"), self.window_ref.companion.open_conversation(cid)))
        if task.get("goal"):
            steps = task.get("steps") or []
            done = sum(1 for s in steps if str(s).startswith("[x] "))
            status = str(task.get("status", "idle")).replace("_", " ")
            self._item(lay, "tasks", task["goal"], f"{done} of {len(steps)} steps done · {status}" if steps else status, "Open", lambda _=False: go("Reminders & tasks"))
        if missions:
            from ...services.forge_missions import DISCIPLINES

            m = missions[0]
            self._item(lay, "forge", f"{DISCIPLINES.get(m['discipline'], {}).get('name', m['discipline'])} mission · {m['project']}", m["objective"][:110], "Open", lambda _=False: go("Forge"))
        for c in convs[1:3]:
            self._item(lay, "chat", c["title"], "", "Open", lambda _=False, cid=c["id"]: (go("Companion"), self.window_ref.companion.open_conversation(cid)), "neutral")
        if not (convs or task.get("goal") or missions):
            lay.addWidget(label("Nothing to continue yet. Ask something above, or start a Forge mission on a project in your workspace.", "faint"))

        lay = self.blocks["today"].inner  # type: ignore[attr-defined]
        rem = d.get("reminders") if isinstance(d.get("reminders"), list) else []
        if not rem:
            lay.addWidget(label("No reminders scheduled. Say “remind me in 2 hours to…” in a conversation, or add one in Reminders & tasks.", "faint"))
        for j in rem:
            try:
                t = datetime.datetime.fromisoformat(str(j.get("next_fire")))
                day = "Today" if t.date() == now.date() else "Tomorrow" if t.date() == (now + datetime.timedelta(days=1)).date() else f"{t:%a %d %b}"
                when = f"{day} {t:%H:%M}"
            except ValueError:
                when = str(j.get("next_fire", ""))
            row = QHBoxLayout()
            tl = label(when, "mono", wrap=False)
            tl.setMinimumWidth(130)
            row.addWidget(tl)
            row.addWidget(label(str(j.get("text", "")) + ("   ↻ repeats" if j.get("recurrence_seconds") else "")), 1)
            lay.addLayout(row)

        lay = self.blocks["glance"].inner  # type: ignore[attr-defined]
        mem = d.get("memory") if isinstance(d.get("memory"), dict) else {}
        active = (mem.get("facts_by_status") or {}).get("active", mem.get("facts", 0))
        skills = d.get("skills") if isinstance(d.get("skills"), list) else []
        stats = d.get("stats") if isinstance(d.get("stats"), dict) and "error" not in d.get("stats") else {}
        calls = sum(int(v.get("calls", 0)) for v in stats.values())
        for text, target in ((f"Remembers {active} things about you and your work →", "Memory"), (f"Knows {len(skills)} learned skill{'s' if len(skills) != 1 else ''} →", "Forge"), (f"Has used its tools {calls} times; every call is in the audit log →", "Trust & safety")):
            b = QPushButton(text)
            b.setObjectName("link")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, t=target: go(t))
            lay.addWidget(b)
