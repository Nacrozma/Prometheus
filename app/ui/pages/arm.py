"""Robot arm: the kinematic SIMULATION from arm_sim.py. Nothing here talks to hardware.

The repository documents the arm as simulation-only until real hardware has been validated, so this
page has no hardware controls at all. That is deliberate, not missing."""

from __future__ import annotations

import json

from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtSvgWidgets import QSvgWidget
from PyQt6.QtWidgets import QDoubleSpinBox, QFormLayout, QHBoxLayout, QPlainTextEdit, QPushButton, QSlider, QWidget

from ..widgets import Card, Page, label

BANNER = "SIMULATION — not connected to any hardware. Real hardware has not been validated; serial control is not offered in this version."


class ArmPage(Page):
    title = "Robot arm"
    subtitle = "Forward and inverse kinematics, limits, collisions and holding torque for the 4-joint arm."

    def __init__(self, core, parent=None):
        super().__init__(core, parent)
        import arm_sim

        self.sim = arm_sim
        b = label(BANNER, "warn")
        b.setStyleSheet("font-weight: 600;")
        self.content.addWidget(b)
        row = QHBoxLayout()
        left = Card("Joints (degrees)")
        form = QFormLayout()
        self.sliders = []
        for j in arm_sim.DEFAULT_ARM.joints:
            s = QSlider(Qt.Orientation.Horizontal)
            lo, hi = j.min_deg, j.max_deg
            s.setRange(int(lo), int(hi))
            s.setValue(int(max(lo, min(hi, 0))))
            s.setAccessibleName(f"{j.name} angle")
            s.valueChanged.connect(self._forward)
            form.addRow(j.name, s)
            self.sliders.append(s)
        host = QWidget()
        host.setLayout(form)
        left.body.addWidget(host)
        ik = Card("Reach a point (metres)")
        f2 = QFormLayout()
        self.xyz = []
        for axis, default in (("x", 0.15), ("y", 0.0), ("z", 0.10)):
            sp = QDoubleSpinBox()
            sp.setRange(-1.0, 1.0)
            sp.setDecimals(3)
            sp.setSingleStep(0.01)
            sp.setValue(default)
            sp.setAccessibleName(axis)
            f2.addRow(axis, sp)
            self.xyz.append(sp)
        h2 = QWidget()
        h2.setLayout(f2)
        ik.body.addWidget(h2)
        solve = QPushButton("Solve inverse kinematics")
        solve.clicked.connect(self._inverse)
        ik.body.addWidget(solve)
        col = QWidget()
        from PyQt6.QtWidgets import QVBoxLayout

        cl = QVBoxLayout(col)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(left)
        cl.addWidget(ik)
        cl.addStretch(1)
        row.addWidget(col, 1)
        right = Card("Simulated pose")
        self.svg = QSvgWidget()
        self.svg.setMinimumSize(320, 260)
        right.body.addWidget(self.svg, 1)
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setMaximumHeight(170)
        right.body.addWidget(self.out)
        row.addWidget(right, 2)
        self.content.addLayout(row, 1)
        self._forward()

    def _q(self):
        return [float(s.value()) for s in self.sliders]

    def _show(self, q, target=None, extra=None) -> None:
        try:
            svg = self.sim.render_svg(q, target=target)
            self.svg.load(QByteArray(svg.encode("utf-8")))
        except Exception as e:
            self.out.setPlainText(f"Could not draw the pose: {e}")
        pts = self.sim.forward(q)
        info = {"end_effector_m": [round(v, 4) for v in pts["tip"]], "limit_issues": self.sim.within_limits(q), "collisions": self.sim.collisions(q), "simulation_only": True}
        if extra:
            info.update(extra)
        self.out.setPlainText(json.dumps(info, indent=2))

    def _forward(self) -> None:
        self._show(self._q())

    def _inverse(self) -> None:
        x, y, z = (s.value() for s in self.xyz)
        res = self.core.dispatch("arm_plan", x=x, y=y, z=z)
        if res.get("status") != "success":
            self.out.setPlainText(json.dumps(res, indent=2))
            return
        joints = res.get("joints_deg") or {}
        q = [joints[n] for n in ("yaw", "shoulder", "elbow", "wrist") if n in joints] if isinstance(joints, dict) else list(joints)
        if q:
            for s, v in zip(self.sliders, q):
                s.blockSignals(True)
                s.setValue(int(round(v)))
                s.blockSignals(False)
            self._show(list(q), target=(x, y, z), extra={"plan": {k: v for k, v in res.items() if k not in ("svg",)}})
