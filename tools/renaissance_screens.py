"""Capture screenshots of the real Prometheus Desktop window (Renaissance visual QA).

Runs the actual application against throwaway data folders, seeds a little sample data through the
same code paths a person would use (conversations store, memory tool, scheduler tool), visits each
section and saves PNGs. Nothing is faked on screen; the sample data is labelled as such in the docs.

    xvfb-run -s "-screen 0 1600x1000x24" python tools/renaissance_screens.py docs/screenshots/renaissance

Use throwaway folders only: the script sets PROMETHEUS_HOME and PROMETHEUS_WORKSPACE itself.
"""

from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs", "screenshots", "renaissance"))
ONLY = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else set()
tmp = tempfile.mkdtemp(prefix="prometheus-shots-")
os.environ["PROMETHEUS_HOME"] = os.path.join(tmp, "home")
os.environ["PROMETHEUS_WORKSPACE"] = os.path.join(tmp, "workspace")
for k in ("OPENROUTER_API_KEY", "GROQ_API_KEY", "CEREBRAS_API_KEY", "MISTRAL_API_KEY", "ANTHROPIC_API_KEY"):
    os.environ.pop(k, None)
os.makedirs(os.environ["PROMETHEUS_WORKSPACE"], exist_ok=True)
sys.path.insert(0, ROOT)
os.chdir(tmp)

# a small sample project in the workspace, so Workspace and search have something real to show
ws = os.environ["PROMETHEUS_WORKSPACE"]
os.makedirs(os.path.join(ws, "rocket-sim", "src"), exist_ok=True)
with open(os.path.join(ws, "rocket-sim", "README.md"), "w") as f:
    f.write("# Rocket sim\n\nA small two-stage trajectory model.\n")
with open(os.path.join(ws, "rocket-sim", "src", "trajectory.py"), "w") as f:
    f.write("def delta_v(isp, m0, mf):\n    import math\n    return isp * 9.80665 * math.log(m0 / mf)\n")

from PyQt6.QtCore import QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

import app.application as A  # noqa: E402

os.makedirs(OUT, exist_ok=True)


def seed(win) -> None:
    core = win.core
    for fact, kind in (("The owner prefers SI units in engineering answers.", "preference"), ("Rocket-sim uses a two-stage model with Isp 311 s for stage one.", "fact"), ("Decided to keep Forge skills disabled until their tests pass.", "decision"), ("Always run the test suite before proposing a patch.", "lesson")):
        core.dispatch("update_memory", fact=fact, kind=kind, importance=0.7)
    core.dispatch("schedule_task", when="2h", text="Review the rocket-sim trajectory notes")
    core.dispatch("schedule_task", when="24h", text="Daily: check pending Forge patches", recurring=True)
    store = win.conversations
    store.create([{"role": "user", "content": "What delta-v does a stage with Isp 311 s and mass ratio 4 give?"}, {"role": "assistant", "content": "Using the rocket equation, **Δv = Isp · g₀ · ln(m₀/m_f)**:\n\n```python\nimport math\nprint(311 * 9.80665 * math.log(4))  # ≈ 4228 m/s\n```\n\nSo about **4.23 km/s** (ideal, no gravity or drag losses)."}])
    store.create([{"role": "user", "content": "Summarise the open Forge patches."}, {"role": "assistant", "content": "There are no pending self-patches right now."}])
    c = store.create([{"role": "user", "content": "Plan the next step for rocket-sim."}, {"role": "assistant", "content": "1. Add drag to the trajectory model.\n2. Write a test for `delta_v`.\n3. Compare with the two-stage reference case."}])
    win.companion.open_conversation(c["id"])


def shoot(win, name: str) -> None:
    if ONLY and name not in ONLY:
        return
    QApplication.processEvents()
    win.grab().save(os.path.join(OUT, f"{name}.png"))


def onboarding(win, then) -> None:
    dlg = getattr(win, "onboarding", None)
    if dlg is None or not dlg.isVisible():
        then()
        return

    def page(i=0):
        if i >= dlg.stack.count():
            dlg.accept()
            QTimer.singleShot(400, then)
            return
        dlg._go(i)
        QTimer.singleShot(700, lambda: ((not ONLY or f"00-onboarding-{i + 1}" in ONLY) and dlg.grab().save(os.path.join(OUT, f"00-onboarding-{i + 1}.png")), page(i + 1)))

    page()


def run(win) -> None:
    onboarding(win, lambda: run_main(win))


def run_main(win) -> None:
    seed(win)
    steps = [
        ("01-home", lambda: win.go("Home")),
        ("02-companion", lambda: win.go("Companion")),
        ("03-memory", lambda: win.go("Memory")),
        ("04-engineering", lambda: win.go("Engineering")),
        ("05-forge", lambda: win.go("Forge")),
        ("06-workspace", lambda: win.go("Workspace")),
        ("07-tasks", lambda: win.go("Reminders & tasks")),
        ("08-obsidian", lambda: win.go("Obsidian")),
        ("09-robot-arm", lambda: win.go("Robot arm (simulation)")),
        ("10-reflection", lambda: win.go("Reflection")),
        ("11-trust", lambda: win.go("Trust & safety")),
        ("12-settings", lambda: win.go("Settings")),
        ("13-nav-collapsed", lambda: (win.go("Home"), win.nav.set_collapsed(True))),
    ]

    def step(i=0):
        if i >= len(steps):
            win.nav.set_collapsed(False)
            extra(win)
            return
        name, fn = steps[i]
        fn()
        QTimer.singleShot(1400, lambda: (shoot(win, name), step(i + 1)))

    step()


def extra(win) -> None:
    """Dialogs and states that need a little set-up."""
    comp = win.companion
    win.go("Companion")

    class W:
        answer = None
        def provide_confirmation(self, ok): self.answer = ok
        def isRunning(self): return True
        def request_stop(self): pass

    comp.worker = W()
    comp._confirm("write_file", '{"path": "rocket-sim/notes.md", "content": "# Notes\\nDrag model next."}')
    QTimer.singleShot(1200, lambda: (shoot(win, "14-approval-card"), after_card(win)))


def after_card(win) -> None:
    comp = win.companion
    comp._answer("write_file", False)
    comp.worker = None
    states = ["THINKING", "BUILDING", "SPEAKING", "LISTENING", "ERROR", "OFFLINE"]

    def st(i=0):
        if i >= len(states):
            comp.set_state("IDLE")
            palette(win)
            return
        comp.set_state(states[i])
        if states[i] in ("SPEAKING", "LISTENING"):
            comp._audio_level(0.7)
        QTimer.singleShot(900, lambda: (shoot_orb(win, states[i]), st(i + 1)))

    st()


def shoot_orb(win, state: str) -> None:
    name = f"15-avatar-{state.lower()}"
    if ONLY and name not in ONLY:
        return
    w = win.companion.orb or win.companion.glyph
    QApplication.processEvents()
    w.grab().save(os.path.join(OUT, f"{name}.png"))


def palette(win) -> None:
    from app.ui.main_window import CommandPalette
    from app.services import search

    ws = win.core.paths()["workspace"]
    entries = [(f"Go to {n}", (lambda n=n: win.go(n)), "section") for n in win.pages]
    dlg = CommandPalette(entries, lambda q: search.search(win.core, win.conversations, q, ws), win.open_result, win)
    dlg.show()
    dlg.search.setText("rocket")
    def snap():
        QApplication.processEvents()
        if not ONLY or "16-search" in ONLY:
            dlg.grab().save(os.path.join(OUT, "16-search.png"))
        dlg.close()
        print("SHOTS DONE", OUT)
        win.quit()
    QTimer.singleShot(2200, snap)


_orig = QApplication.exec


def patched(self):
    win = next(w for w in QApplication.topLevelWidgets() if w.__class__.__name__ == "MainWindow")
    win.resize(1440, 900)
    QTimer.singleShot(1500, lambda: run(win))
    return _orig()


QApplication.exec = patched
sys.exit(A.main(["prometheus"]))
