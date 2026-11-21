"""Screenshots of the Engineering Lab in the real Prometheus Desktop window (visual QA).

Runs the application against throwaway folders. Every number shown is a real model output from eng/ with the
model's example input; nothing is a measurement.

    xvfb-run -s "-screen 0 1600x1000x24" python tools/eng_screens.py docs/screenshots/engineering
"""

from __future__ import annotations

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs", "screenshots", "engineering"))
tmp = tempfile.mkdtemp(prefix="prometheus-eng-shots-")
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

os.makedirs(OUT, exist_ok=True)


def shoot(win, name):
    QApplication.processEvents()
    win.grab().save(os.path.join(OUT, f"{name}.png"))
    print("shot", name)


def run(win):
    if getattr(win, "launch", None) is not None:
        try:
            win.launch.finish()
        except RuntimeError:
            pass
    dlg = getattr(win, "onboarding", None)
    if dlg is not None and dlg.isVisible():
        dlg.accept()
    win.go("Engineering")
    page = win.pages["Engineering"]
    page.mode.button(1).setChecked(True)
    page._mode(1)
    lab = page.lab
    steps = []

    def select(model):
        for i in range(lab.models.count()):
            if lab.models.item(i).data(0x0100) == model:
                lab.models.setCurrentRow(i)
                return

    def run_model(model, plot=None, record=False, title=""):
        def go():
            select(model)
            if record:
                lab.exp_title.setText(title)
                res = lab.core.engineering_lab("run", model=model, params=lab.registry.EXAMPLES[model], record=True, title=title)
                full = lab.registry.run(model, **lab.registry.EXAMPLES[model])
                full["experiment_id"] = res["experiment_id"]
            else:
                full = lab.registry.run(model, **lab.registry.EXAMPLES[model])
            lab._done(full)
            if plot is not None:
                idx = lab.plot_pick.findData(plot)
                if idx >= 0:
                    lab.plot_pick.setCurrentIndex(idx)
        return go

    steps.append(("01-lab-trajectory", run_model("trajectory", "profile", record=True, title="Sounding rocket baseline")))
    steps.append(("02-lab-frame", run_model("frame")))
    steps.append(("03-lab-design-pareto", run_model("cantilever_optimisation", "mass_vs_sf", record=True, title="Cantilever trade study")))
    steps.append(("04-lab-control", run_model("control", "response")))
    steps.append(("05-lab-arm-torque", run_model("arm_trajectory", "torque_shoulder", record=True, title="Fast shoulder move")))
    steps.append(("06-lab-shock-sweep", run_model("mach_sweep", "p_ratio")))

    def at_1280():
        win.resize(1280, 800)
    steps.append(("07-lab-1280x800", at_1280))

    def step(i=0):
        if i >= len(steps):
            win.quit()
            return
        name, fn = steps[i]
        fn()
        QTimer.singleShot(700, lambda: (shoot(win, name), step(i + 1)))

    step()


_orig = QApplication.exec


def patched(self):
    win = next(w for w in QApplication.topLevelWidgets() if w.__class__.__name__ == "MainWindow")
    win.resize(1440, 900)
    win.settings.set("launch_animation", False)
    QTimer.singleShot(2500, lambda: run(win))
    return _orig()


QApplication.exec = patched
sys.exit(A.main(["prometheus"]))
