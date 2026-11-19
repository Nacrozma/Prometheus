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
"outcome": "A tagged release people can install", "phases": ["Understand", "Build", "Verify", "Release"],
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
    win.go("ORBIT")
    steps = []

    def add(name, fn, wait=900):
        steps.append((name, fn, wait))

    add("01-orbit-empty", lambda: None)

    def proposed():
        orb._ensure_saved_session()
        conv = win.conversations.get(orb.session["conversation_id"])
        conv["messages"] += [{"role": "user", "content": "I want to publish rocket-sim properly, with docs and an installer."}, {"role": "assistant", "content": SAMPLE_REPLY}]
        win.conversations.save(conv)
        orb.session["title"] = "Rocket-sim public release"
        O.add_version(orb.session, O.extract_plan(SAMPLE_REPLY), "prometheus", "Proposed in conversation")
        orb._save()
        orb._fill_sessions()
        orb._render_transcript()
        orb.render_all()
        orb.set_state("SPEAKING")

    add("02-orbit-plan-proposed", proposed, 1400)

    def edited():
        orb.say("make add a drag model option low priority")
        orb.say("move Verify before Build")
        orb.say("undo")
        orb.stage.select("b1")
        orb.tabs.setCurrentIndex(1)
        orb.set_state("IDLE")

    add("03-orbit-edited-step", edited)

    def outline():
        orb.toggle_view()

    add("04-orbit-outline", outline)

    def workflow():
        orb.toggle_view()
        orb.autonomy.setCurrentIndex(orb.autonomy.findData("balanced"))
        orb.approve_plan()
        orb.build_workflow()
        wf = orb.session["workflow"]
        for nid in ("u1", "u2"):
            O.transition(wf, nid, "running")
            O.transition(wf, nid, "completed", "sample result")
        O.transition(wf, "b1", "running")
        orb.worker_kind = "b1"
        orb.stage.select("b1")
        orb._save()
        orb.render_all()
        orb.set_state("RUNNING")

    add("05-orbit-workflow-running", workflow, 1400)

    def approval():
        class W:
            def provide_confirmation(self, ok):
                pass

            def isRunning(self):
                return True

            def request_stop(self):
                pass

        orb.worker = W()
        orb._stream = "I will write the guide into docs/USER_GUIDE.md."
        orb._confirm("write_file", json.dumps({"path": "rocket-sim/docs/USER_GUIDE.md", "content": "# Rocket-sim user guide\n\nInstall, run, read the results.\n"}))
        orb.render_all()

    add("06-orbit-tool-approval", approval, 1200)

    def versions():
        orb._clear_card()
        orb.worker, orb.worker_kind = None, ""
        node = orb._node("b1")
        O.transition(orb.session["workflow"], "b1", "running") if node["status"] == "awaiting_approval" else None
        O.transition(orb.session["workflow"], "b1", "failed", "sample: the provider timed out")
        orb.render_all()
        orb.tabs.setCurrentIndex(2)
        orb.versions.setCurrentRow(orb.versions.count() - 1)
        orb.set_state("ERROR")

    add("07-orbit-versions-failed-step", versions)

    def immersive():
        orb.tabs.setCurrentIndex(0)
        orb.set_immersive(True)
        orb.set_state("LISTENING")
        orb.stage.set_level(0.55)

    add("08-orbit-immersive-listening", immersive, 1200)

    def small():
        orb.set_immersive(False)
        win.resize(1280, 800)
        orb.set_state("PLANNING")

    add("09-orbit-1280x800", small, 1400)

    def reduced():
        win.resize(1440, 900)
        orb.set_reduced_motion(True)
        orb.set_state("RUNNING")

    add("10-orbit-reduced-motion-executing", reduced, 900)

    def step(i=0):
        if i >= len(steps):
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
    QTimer.singleShot(3000, lambda: run(win))
    return _orig()


QApplication.exec = patched
sys.exit(A.main(["prometheus"]))
