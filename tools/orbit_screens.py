"""Capture screenshots of ORBIT in the real Prometheus Desktop window (ORBIT visual QA).

Runs the actual application against throwaway folders. No model is called: the plan shown is a sample
reply passed through the same parser a real reply goes through (`orbit.extract_plan`), recorded as a
version authored by Prometheus, and the workflow states are produced by the real state machine
(`orbit.transition`). The approval card is the real card raised by the real gate. Labelled as sample
data in docs/ORBIT_VISUAL_QA.md.

    xvfb-run -s "-screen 0 1600x1000x24" python tools/orbit_screens.py docs/screenshots/orbit
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs", "screenshots", "orbit"))
tmp = tempfile.mkdtemp(prefix="prometheus-orbit-shots-")
os.environ["HOME"] = tmp
os.environ["PROMETHEUS_HOME"] = os.path.join(tmp, ".prometheus")
os.environ["PROMETHEUS_WORKSPACE"] = os.path.join(tmp, "Documents", "Prometheus Workspace")
for k in ("OPENROUTER_API_KEY", "GROQ_API_KEY", "CEREBRAS_API_KEY", "MISTRAL_API_KEY", "ANTHROPIC_API_KEY"):
    os.environ.pop(k, None)
os.makedirs(os.environ["PROMETHEUS_WORKSPACE"], exist_ok=True)
sys.path.insert(0, ROOT)
os.chdir(tmp)

from PyQt6.QtCore import QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

import app.application as A  # noqa: E402
from app.services import orbit as O  # noqa: E402

os.makedirs(OUT, exist_ok=True)

SAMPLE_REPLY = """Here is a first plan. Two things I still need: which hosting you prefer, and the launch date.
```orbit-plan {"title": "Rocket-sim public release", "objective": "Publish rocket-sim with docs and a tested installer",
"outcome": "A tagged release people can install",
"brief": "Rocket-sim is a small two-stage trajectory model. This project turns it into something other people can install and trust: a guide, a tested installer and a tagged release.",
"ideas": ["Ship a one-file Windows installer", "Add a gallery of example trajectories", "Publish the docs as a static site", "Offer a drag model switch for advanced users"], "phases": ["Understand", "Build", "Verify", "Release"],
"tasks": [
 {"id": "u1", "title": "Review the trajectory model", "phase": "Understand", "detail": "Read src/trajectory.py and list assumptions."},
 {"id": "u2", "title": "List what users need", "phase": "Understand"},
 {"id": "b1", "title": "Write the user guide", "phase": "Build", "priority": "high"},
 {"id": "b2", "title": "Add a drag model option", "phase": "Build"},
 {"id": "b3", "title": "Package the installer", "phase": "Build"},
 {"id": "v1", "title": "Run the test suite", "phase": "Verify", "priority": "high"},
 {"id": "v2", "title": "Check the guide against the app", "phase": "Verify"},
 {"id": "r1", "title": "Tag and publish", "phase": "Release"}],
"deps": [{"from": "u1", "to": "b2"}, {"from": "u2", "to": "b1"}, {"from": "b2", "to": "v1"}, {"from": "b3", "to": "v1"}, {"from": "b1", "to": "v2"}, {"from": "v1", "to": "r1"}, {"from": "v2", "to": "r1"}],
"assumptions": ["The model code is the current source of truth"], "questions": ["Which hosting?", "Launch date?"], "risks": ["Installer signing is not set up"]}
```"""


def shoot(win, name: str) -> None:
    QApplication.processEvents()
    win.grab().save(os.path.join(OUT, f"{name}.png"))


def run(win) -> None:
    if getattr(win, "launch", None) is not None:
        try:
            win.launch.finish()
        except RuntimeError:
            pass
    dlg = getattr(win, "onboarding", None)
    if dlg is not None and dlg.isVisible():
        dlg.accept()
    orb = win.orbit
    ws = orb.core.paths()["workspace"]
    os.makedirs(os.path.join(ws, "rocket-sim", "docs"), exist_ok=True)
    with open(os.path.join(ws, "rocket-sim", "README.md"), "w") as f:
        f.write("# Rocket sim\n\nA small two-stage trajectory model.\n")
    steps = []

    def add(name, fn, wait=900):
        steps.append((name, fn, wait))

    # the real entry sequence, caught mid-way (first entry plays the long version)
    add("00-orbit-entry", lambda: win.go("ORBIT"), 1100)
    add("01-orbit-empty", lambda: None, 2600)

    def materialising():
        orb._ensure_saved_session()
        orb.universe._seen = {"sid": orb.session["id"], "versions": 0, "approved": 0, "done": 0, "wf": "", "files": 0, "waiting": 0}
        partial = O.partial_plan(SAMPLE_REPLY[: SAMPLE_REPLY.index('"phases"') + 60])
        orb.set_state("PLANNING")
        orb.universe.refresh(provisional=partial, materialise=True)

    add("02-orbit-project-materialising", materialising, 900)

    def proposed():
        conv = win.conversations.get(orb.session["conversation_id"])
        conv["messages"] += [{"role": "user", "content": "Let's create a new project: publish rocket-sim properly, with docs and an installer."}, {"role": "assistant", "content": SAMPLE_REPLY}]
        win.conversations.save(conv)
        orb.session["title"] = "Rocket-sim public release"
        O.add_version(orb.session, O.extract_plan(SAMPLE_REPLY), "prometheus", "Proposed in conversation")
        orb._save()
        orb._fill_sessions()
        orb._render_transcript()
        orb.render_all()
        orb.set_state("SPEAKING")
        orb.universe.core.set_level(0.6)

    add("03-orbit-command-project-created", proposed, 700)

    def intelligence():
        orb.set_state("RESEARCHING")
        orb.universe.set_env("intelligence", user=True)

    add("04-orbit-intelligence", intelligence, 1000)

    def design():
        orb.set_state("THINKING")
        orb.universe.set_env("design", user=True)
        orb.stage.select("b1")

    add("05-orbit-design", design, 1000)

    def operations():
        orb.approve_plan()
        orb.build_workflow()
        wf = orb.session["workflow"]
        for nid in ("u1", "u2"):
            O.transition(wf, nid, "running")
            O.transition(wf, nid, "completed", "sample result")
        wf["nodes"][0]["output"] = "Assumptions found: fixed Isp per stage, no wind, flat Earth below 30 km."
        O.transition(wf, "b1", "running")
        from app.services import orbit_space as SP

        SP.add_file(orb.session, ws, "rocket-sim/README.md", "written", "b1")
        orb._save()
        orb.universe.set_env("operations", user=True)
        orb.render_all()
        orb.set_state("RUNNING")

    add("06-orbit-operations-running", operations, 1100)

    def approval():
        class W:
            def provide_confirmation(self, ok):
                pass

            def isRunning(self):
                return True

            def request_stop(self):
                pass

        orb.worker = W()
        orb.worker_kind = "b1"
        orb._stream = "I will write the guide into docs/USER_GUIDE.md."
        orb._confirm("write_file", json.dumps({"path": "rocket-sim/docs/USER_GUIDE.md", "content": "# Rocket-sim user guide\n"}))
        orb.render_all()

    add("07-orbit-waiting-for-approval", approval, 1000)

    def file_preview():
        orb._clear_card()
        orb.worker, orb.worker_kind = None, ""
        n = orb._node("b1")
        if n["status"] == "awaiting_approval":
            O.transition(orb.session["workflow"], "b1", "running")
        orb.universe.set_env("command", user=True)
        orb.set_state("IDLE")
        orb._space_link("files", "file:rocket-sim/README.md")

    add("08-orbit-file-preview-expanded", file_preview, 900)

    def complete():
        p = orb.universe.panels["files"]
        if p.expanded:
            orb.universe._link("files", "back:")
            p.toggle_expand()
        wf = orb.session["workflow"]
        for n in wf["nodes"]:
            while n["status"] not in ("completed",):
                nxt = {"ready": "running", "waiting": "ready", "running": "completed", "paused": "ready", "awaiting_approval": "running"}.get(n["status"])
                if not nxt:
                    break
                O.transition(wf, n["id"], nxt, "sample")
        orb.universe.set_env("operations", user=True)
        orb.render_all()
        orb.set_state("SUCCESS")

    add("09-orbit-workflow-complete", complete, 600)

    def listening():
        orb.universe.set_env("command", user=True)
        orb.set_immersive(True)
        orb.set_state("LISTENING")
        orb.universe.core.set_level(0.55)

    add("10-orbit-immersive-listening", listening, 1200)

    def small():
        orb.set_immersive(False)
        win.resize(1280, 800)
        orb.set_state("THINKING")

    add("11-orbit-1280x800", small, 1300)

    def reduced():
        win.resize(1440, 900)
        win.settings.set("reduced_motion", True)
        orb.set_reduced_motion(True)
        orb.set_state("ERROR")

    add("12-orbit-reduced-motion-error", reduced, 900)

    def step(i=0):
        if i >= len(steps):
            win.settings.set("reduced_motion", False)
            win.quit()
            return
        name, fn, wait = steps[i]
        fn()
        QTimer.singleShot(wait, lambda: (shoot(win, name), step(i + 1)))

    step()


_orig = QApplication.exec


def patched(self):
    win = next(w for w in QApplication.topLevelWidgets() if w.__class__.__name__ == "MainWindow")
    win.resize(1440, 900)
    win.settings.set("launch_animation", False)
    win.go("Home")
    QTimer.singleShot(3000, lambda: run(win))
    return _orig()


QApplication.exec = patched
sys.exit(A.main(["prometheus"]))
