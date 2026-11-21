# Engineering audit (Phase 0) — 2026-11-21

Scope: everything in Prometheus that does engineering arithmetic, simulation or hardware control,
read from the code itself (not from older docs). Baseline before any change in this phase:
`python -m pytest tests -q` → **547 passed, 2 skipped** (Linux, Python 3.13).

## 1. What exists and works (in software)

| File | What it really does | Evidence |
|---|---|---|
| `engineering.py` (407 lines) | 18 pure SI calculators behind `calculate(name, **params)`: unit conversion, section properties, determinate beams (simply supported / cantilever, point / UDL), bending stress, factor of safety, torsion, Euler buckling, plane stress / von Mises, thermal expansion, **determinate 2-D truss by the method of joints**, ISA atmosphere **0–20 km**, lift, stall speed, Reynolds number, circular orbit, vis-viva, Hohmann, ideal rocket equation | `tests/test_engineering.py`, `tests/test_engineering_integration.py` (textbook values) |
| `arm_sim.py` (355) | 4-joint arm (yaw, shoulder, elbow, wrist): FK, closed-form IK (elbow up/down, lean-back), joint limits for 180° servos, floor/base keep-out, **static holding torque**, servo check at 50 % of stall, max payload (bisection), smoothstep joint moves, workspace sampling, SVG | `tests/test_arm_sim.py` (1,600+ FK↔IK round trips) |
| `arm_bridge.py` (268) | Binary protocol `0xA5 LEN CMD payload CRC8` (CRC-8 poly 0x07), resynchronising parser, host-side limits, `FirmwareSim` (model of the sketch: clamp, slew limit, 0.5 s watchdog, e-stop latch), `SimTransport` (virtual clock, drop/corrupt injection), `SerialTransport` (pyserial) | `tests/test_arm_bridge.py` (framing fuzz, safety rules, constant parity with the sketch) |
| `arduino/arm_controller/arm_controller.ino` | Firmware for 5 servos (incl. gripper): same protocol, clamps, 90 °/s slew, 500 ms watchdog, software e-stop | **Never compiled or run on a board.** A test parses its constants only |
| `arm_gesture.py` (235) | MediaPipe 21-landmark hand → target: validation, arming, outlier gate, EMA + dead-band, workspace clamping, hold-then-stop on hand loss | `tests/test_arm_gesture.py` (synthetic hands) |
| `arm_demo.py` (136) | `--synthetic` (tested), `--camera`, `--port` (**not tested**) | — |
| `prometheus.py` | Tools `engineering_calc` and `arm_plan` (simulation only) | `tests/test_engineering_integration.py` |
| `app/ui/pages/engineering.py`, `arm.py` | Desktop: calculator studio over `engineering.CALCULATIONS`, project intelligence; arm page (FK/IK, pose drawing) | window smoke test |

## 2. Simulation-only, placeholder or missing

* **Every arm parameter is a placeholder**: `ArmSpec` link lengths (70/120/120/100 mm), `Masses`, servo stall
  torques (datasheet, "treat as optimistic"), 50 % derate rule of thumb. No measured value exists anywhere.
* **Torque is static only** (no inertia, velocity, acceleration, friction, torque–speed curve).
* **No hardware has ever run**: firmware not compiled, `SerialTransport` never opened a port, camera mode untested.
* **Firmware safety gaps** (found in this audit, not by a failure on hardware):
  1. The e-stop latch lives in RAM. A board reset (e.g. a brown-out when servos draw current through a
     marginal supply — a common hobby-arm failure) clears it, and the next `SET_ANGLES` from a host that is
     still streaming moves the arm. There is no "disarmed at boot" state.
  2. The e-stop is software-only (a serial command). There is no hardware input, and nothing in the repository
     describes how to interrupt servo power.
  3. On power-up every servo jumps to `REST_DEG` at full speed (documented in a comment; unavoidable without
     position feedback, but the bring-up procedure must account for it).
* **Gesture**: MediaPipe detection/tracking confidence is fixed at 0.6 and the per-hand score is never used; there
  is no dry-run mode that shows commands while guaranteeing no serial port is opened.
* **Structures**: only statically determinate pin-jointed trusses (method of joints); no stiffness method, no
  indeterminate structures, no frames, no displacements.
* **Machine design**: no stress concentration, fatigue, shaft or bolted-joint calculations.
* **Aerospace**: atmosphere stops at 20 km; no compressible flow, shocks, expansions, nozzles, trajectory
  integration or control.
* **Method**: no uncertainty propagation, no experiment records, no report generation, no validation document,
  no engineering journal, no benchmark plots.

## 3. Constraints that shape the design

* Python core + PyQt6 desktop; JSON state written atomically through `state_io.py`; no SQLite.
* Dependencies already bundled: **numpy** (core requirement), PyQt6 (incl. QtSvg, QtGui PDF writer). No SciPy,
  no matplotlib (matplotlib is explicitly excluded from the installer). New work therefore uses numpy only,
  draws plots as SVG itself, and writes PDF through Qt — **no new third-party dependency**.
* Tools are exposed through `prometheus.py` (`TOOLS` schema + dispatcher); calculators registered in
  `engineering.CALCULATIONS` appear automatically in the desktop calculator studio.
* Root-level modules must be listed in `packaging/prometheus.spec` (`CORE_MODULES`) to reach the installer.
* Hardware: no board, servo, camera or measuring instrument is attached to this development environment, and
  none is reachable from CI. **Every physical measurement in this phase is pending.**

## 4. Licences

numpy (BSD-3), PyQt6 (GPL v3 / commercial), pyserial (BSD-3), opencv-python (Apache-2.0 / MIT),
mediapipe (Apache-2.0). Nothing new is added.

## 5. Plan (executed in this order)

1. **Arm safety and bring-up**: firmware boots *disarmed* and needs an explicit re-arm; optional fail-safe
   hardware e-stop input (normally-closed loop) as a second channel; `FirmwareSim` mirrors both; bench
   hardware-in-the-loop scenarios (CRC rejection, watchdog timing, e-stop latch, re-arm) that run with **servo
   power disconnected**; calibration records with provenance; wiring and step-by-step bring-up checklist.
2. **Arm modelling**: recursive Newton–Euler dynamics for the 4-joint arm, trapezoidal / cubic / quintic
   trajectories, servo torque–speed limits, feasibility report; simulation-to-real benchmark planner and
   analyser (waits for measured data); gesture confidence gate and dry-run.
3. **Mechanical**: direct-stiffness 2-D truss (determinate and indeterminate) and 2-D frame solvers;
   stress concentration, Marin-corrected endurance limit, Goodman / Soderberg, shaft sizing, bolted joints;
   mass vs. safety-factor design sweep with a Pareto front.
4. **Aerospace**: 1976 standard atmosphere to 86 km; isentropic, normal/oblique shock, Prandtl–Meyer; ideal
   nozzle performance; RK4 planar 3-DOF point-mass trajectory with timestep convergence; discrete PID / state
   feedback control sandbox with stability checks.
5. **Method**: uncertainty (GUM linear + Monte Carlo + sensitivity), experiment store with provenance and
   re-run, data logger, reports (Markdown, HTML, JSON, CSV, PDF), SVG benchmark plots.
6. **Validation and communication**: `docs/VALIDATION.md`, `docs/ENGINEERING_JOURNAL.md`, reference tests.
7. **Integration**: tools for Prometheus, calculators in the studio, an Engineering Lab view, docs, release.
