"""Robot arm: a laboratory studio for the kinematic SIMULATION in arm_sim.py. Nothing here talks to
hardware; the page says so permanently in its header.

A large viewport (side and top views) is the centre of attention. Left: joint controls with live degree
readouts (sliders take arrow keys and Page Up/Down; − / + nudge one degree). Right: telemetry from the
simulation — tip position, joint limits, self-collisions, holding torque — and a reach target solved
through the arm_plan tool (audited). Home resets the pose. Every change redraws immediately.
"""

from __future__ import annotations

from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtSvgWidgets import QSvgWidget
from PyQt6.QtWidgets import QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QPushButton, QSlider, QSplitter, QVBoxLayout, QWidget

from .. import icons
from .. import theme as T
from ..feedback import notify
from ..widgets import Page, label, pill

BANNER = "SIMULATION — not connected to any hardware. Real hardware has not been validated; serial control is not offered in this version."
HOME = {"yaw": 0, "shoulder": 90, "elbow": -90, "wrist": 0}


class ArmPage(Page):
    title = "Robot arm"
    header = "none"
    margins = (0, 0, 0, 0)

    def __init__(self, core, parent=None):
        super().__init__(core, parent)
        import arm_sim

        self.sim = arm_sim
        self.target = None
        split = QSplitter()
        split.setHandleWidth(1)
        split.setChildrenCollapsible(False)

        # joints
        left = QFrame()
        left.setObjectName("rail")
        left.setMinimumWidth(280)
        left.setMaximumWidth(340)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(16, 20, 14, 14)
        ll.setSpacing(10)
        ll.addWidget(label("Robot arm", "h1"))
        sim = pill("SIMULATION ONLY", "warn")
        sim.setToolTip(BANNER)
        ll.addWidget(sim)
        ll.addWidget(label(BANNER, "faint"))
        ll.addWidget(label("JOINTS", "eyebrow"))
        grid = QGridLayout()
        grid.setVerticalSpacing(12)
        self.sliders = []
        self.readouts = []
        for r, j in enumerate(arm_sim.DEFAULT_ARM.joints):
            grid.addWidget(label(j.name.capitalize(), wrap=False), r * 2, 0, 1, 2)
            val = label("", "mono", wrap=False)
            val.setAlignment(Qt.AlignmentFlag.AlignRight)
            grid.addWidget(val, r * 2, 2, 1, 2)
            minus = QPushButton("-")
            minus.setFixedWidth(30)
            minus.setStyleSheet("padding: 2px 0; font-weight: 600;")
            minus.setAccessibleName(f"{j.name} minus one degree")
            s = QSlider(Qt.Orientation.Horizontal)
            s.setRange(int(j.min_deg), int(j.max_deg))
            s.setValue(int(max(j.min_deg, min(j.max_deg, HOME.get(j.name, 0)))))
            s.setPageStep(10)
            s.setAccessibleName(f"{j.name} angle, {int(j.min_deg)} to {int(j.max_deg)} degrees")
            s.valueChanged.connect(self._forward)
            plus = QPushButton("+")
            plus.setFixedWidth(30)
            plus.setStyleSheet("padding: 2px 0; font-weight: 600;")
            plus.setAccessibleName(f"{j.name} plus one degree")
            minus.clicked.connect(lambda _=False, sl=s: sl.setValue(sl.value() - 1))
            plus.clicked.connect(lambda _=False, sl=s: sl.setValue(sl.value() + 1))
            grid.addWidget(minus, r * 2 + 1, 0)
            grid.addWidget(s, r * 2 + 1, 1, 1, 2)
            grid.addWidget(plus, r * 2 + 1, 3)
            self.sliders.append(s)
            self.readouts.append((val, j))
        ll.addLayout(grid)
        home = QPushButton(icons.icon("home", T.TEXT_SECONDARY), " Home pose")
        home.clicked.connect(self._home)
        ll.addWidget(home)
        ll.addStretch(1)
        split.addWidget(left)

        # viewport
        mid = QWidget()
        ml = QVBoxLayout(mid)
        ml.setContentsMargins(20, 20, 20, 16)
        vp = QFrame()
        vp.setObjectName("viewport")
        vl = QVBoxLayout(vp)
        vl.setContentsMargins(10, 10, 10, 10)
        self.svg = QSvgWidget()
        self.svg.setMinimumSize(480, 280)
        self.svg.setAccessibleName("Simulated arm, side and top view")
        vl.addWidget(self.svg, 1)
        ml.addWidget(vp, 1)
        self.verdict = label("", "sub")
        ml.addWidget(self.verdict)
        split.addWidget(mid)

        # telemetry + reach
        right = QFrame()
        right.setObjectName("inspector")
        right.setMinimumWidth(260)
        right.setMaximumWidth(340)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(16, 20, 16, 14)
        rl.setSpacing(8)
        rl.addWidget(label("TELEMETRY (SIMULATED)", "eyebrow"))
        self.tip = label("", "mono")
        rl.addWidget(self.tip)
        self.limits = label("", "sub")
        rl.addWidget(self.limits)
        self.torque = label("", "faint")
        rl.addWidget(self.torque)
        rl.addSpacing(8)
        rl.addWidget(label("REACH A POINT", "eyebrow"))
        rl.addWidget(label("Metres from the base; solved by inverse kinematics.", "faint"))
        self.xyz = []
        row = QHBoxLayout()
        for axis, default in (("x", 0.15), ("y", 0.0), ("z", 0.10)):
            sp = QDoubleSpinBox()
            sp.setRange(-1.0, 1.0)
            sp.setDecimals(3)
            sp.setSingleStep(0.01)
            sp.setValue(default)
            sp.setPrefix(f"{axis} ")
            sp.setAccessibleName(f"target {axis} in metres")
            row.addWidget(sp)
            self.xyz.append(sp)
        rl.addLayout(row)
        solve = QPushButton(icons.icon("bolt", T.ON_ACCENT), " Reach")
        solve.setObjectName("primary")
        solve.clicked.connect(self._inverse)
        rl.addWidget(solve)
        self.ik_msg = label("", "faint")
        rl.addWidget(self.ik_msg)
        rl.addStretch(1)
        from PyQt6.QtWidgets import QPlainTextEdit

        self.tech_btn = QPushButton("Show technical output")
        self.tech_btn.setObjectName("link")
        self.tech_btn.setCheckable(True)
        self.tech = QPlainTextEdit()
        self.tech.setReadOnly(True)
        self.tech.setVisible(False)
        self.tech.setMaximumHeight(200)
        self.tech.setAccessibleName("Technical output (JSON)")
        self.tech.setStyleSheet(f"font-family: {T.FONT_MONO}; font-size: 8pt;")
        self.tech_btn.toggled.connect(lambda on: (self.tech.setVisible(on), self.tech_btn.setText("Hide technical output" if on else "Show technical output")))
        rl.addWidget(self.tech_btn)
        rl.addWidget(self.tech)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        split.setSizes([300, 760, 300])
        self.content.addWidget(split, 1)
        self._forward()

    def _q(self):
        return [float(s.value()) for s in self.sliders]

    def _show(self, q) -> None:
        for (val, j), v in zip(self.readouts, q):
            val.setText(f"{v:+.0f}°  ({int(j.min_deg)}…{int(j.max_deg)})")
        try:
            svg = self.sim.render_svg(q, target=self.target)
            self.svg.load(QByteArray(svg.encode("utf-8")))
        except Exception as e:
            self.verdict.setText(f"Could not draw the pose: {e}")
        tip = self.sim.forward(q)["tip"]
        self.tip.setText(f"tip x {tip[0] * 1000:7.1f} mm\n    y {tip[1] * 1000:7.1f} mm\n    z {tip[2] * 1000:7.1f} mm")
        lim, col = self.sim.within_limits(q), self.sim.collisions(q)
        problems = lim + col
        self.limits.setText(("⚠ " + "; ".join(problems)) if problems else "✓ Within joint limits, no self-collision")
        self.limits.setStyleSheet(f"color: {T.WARN if problems else T.OK};")
        try:
            tq = self.sim.static_torques(q)
            self.torque.setText("Holding torque (static, no payload):\n" + "\n".join(f"  {k}: {v:.2f} N·m" for k, v in tq.items()))
        except Exception as e:
            self.torque.setText(f"Torque not available: {e}")
        self.verdict.setText("This pose is reachable in simulation." if not problems else "This pose breaks a limit or collides; a real arm must not be driven here.")
        import json as _json

        pts = self.sim.forward(q)
        self.tech.setPlainText(_json.dumps({"joints_deg": dict(zip(("yaw", "shoulder", "elbow", "wrist"), q)), "points_m": {k: [round(v, 4) for v in p] for k, p in pts.items()}, "limit_issues": lim, "collisions": col, "simulation_only": True, **({"last_plan": self.last_plan} if getattr(self, "last_plan", None) else {})}, indent=2))

    def _forward(self) -> None:
        self._show(self._q())

    def _home(self) -> None:
        self.target = None
        for s, j in zip(self.sliders, self.sim.DEFAULT_ARM.joints):
            s.blockSignals(True)
            s.setValue(int(max(j.min_deg, min(j.max_deg, HOME.get(j.name, 0)))))
            s.blockSignals(False)
        self._forward()
        self.ik_msg.setText("")

    def _inverse(self) -> None:
        x, y, z = (s.value() for s in self.xyz)
        res = self.core.dispatch("arm_plan", x=x, y=y, z=z)
        if res.get("status") != "success":
            self.ik_msg.setText(str(res.get("message") or res.get("reason") or "No solution."))
            self.ik_msg.setStyleSheet(f"color: {T.WARN};")
            notify(self, "That point cannot be reached", "warn", self.ik_msg.text())
            return
        self.last_plan = {k: v for k, v in res.items() if k != "svg"}
        joints = res.get("joints_deg") or {}
        q = [joints[n] for n in ("yaw", "shoulder", "elbow", "wrist") if n in joints] if isinstance(joints, dict) else list(joints)
        if q:
            self.target = (x, y, z)
            for s, v in zip(self.sliders, q):
                s.blockSignals(True)
                s.setValue(int(round(v)))
                s.blockSignals(False)
            self._show(list(q))
            err = res.get("position_error_mm") or res.get("error_mm")
            self.ik_msg.setText("Solved: " + ", ".join(f"{n} {v:+.1f}°" for n, v in zip(("yaw", "shoulder", "elbow", "wrist"), q)) + (f" · error {float(err):.2g} mm" if err is not None else ""))
            self.ik_msg.setStyleSheet(f"color: {T.OK};")
