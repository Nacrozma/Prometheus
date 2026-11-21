# Prometheus Desktop 2.6.0 — the engineering laboratory

Released after every Windows check passed (standing owner authorisation). Unsigned installer. Earlier releases stay
published unchanged.

Prometheus gains an integrated mechanical and aerospace engineering lab, and the robot arm becomes ready for a safe,
supervised hardware bring-up. Full details: `docs/VALIDATION.md` (what is verified, how), `docs/ENGINEERING_JOURNAL.md`
(what went wrong and was fixed), `docs/ENGINEERING_AUDIT.md` (starting point), `docs/hardware/ARM_BRINGUP.md`.

## Software features implemented

* **Engineering lab** (Engineering → Engineering lab; the `engineering_lab` tool for Prometheus): 24 models with
  example inputs, plots, experiment records that can be re-run exactly, and reports (Markdown, HTML, JSON, CSV, PDF).
  * Structures: direct-stiffness 2-D trusses (indeterminate, support settlement) and 2-D rigid frames.
  * Machine design: Kt, notch sensitivity, Kf, Marin-corrected endurance limit, Goodman / Soderberg / Gerber,
    Basquin life, DE-Goodman shafts, bolted joints (ISO 898-1); 13 of these calculators are also in the calculation studio.
  * Design optimisation: mass vs safety factor vs deflection sweeps, constraint violations, Pareto front.
  * Aerospace: U.S. Standard Atmosphere 1976 to 86 km; isentropic, normal and oblique shocks, Prandtl–Meyer; ideal
    nozzle performance; planar 3-DOF point-mass RK4 trajectory with timestep-convergence study.
  * Control: discrete PID / state-feedback sandbox with noise, delay, saturation, rate limits and disturbances, with
    discrete-eigenvalue and Routh–Hurwitz stability checks.
  * Robot arm: recursive Newton–Euler joint torques along trapezoidal / cubic / quintic moves with servo torque–speed
    feasibility; ISO 9283 accuracy / repeatability benchmark planner and analyser; calibration records with provenance;
    gesture stress lab.
  * Method: GUM and Monte Carlo uncertainty, Type A/B measurement statistics, experiment store with provenance hash.
* **Arm safety**: the firmware now boots **disarmed** and moves only after a deliberate arm command, so a board reset
  never resumes motion by itself; an optional fail-safe hardware e-stop loop latches the stop and blocks re-arming;
  `arm_demo.py --port` asks you to type ARM; `--dry-run` never opens a port; a MediaPipe confidence gate; landmark recording.
* **Bench hardware-in-the-loop**: `python -m eng.hil --port <port> --servo-power-disconnected` checks the real board's
  protocol, CRC rejection, arming, slew limit, watchdog and e-stop latch with the servos unpowered.

## Automated tests passed

`python -m pytest tests -q` on Linux: 638 passed, 2 skipped (547 before this release): 86 tests in five new engineering
test files, 4 new firmware-safety tests, 1 tool integration test, and new Engineering lab checks in the window smoke
test. The Windows release workflow runs the same suite before publishing.

## Numerical verification completed

Reference comparisons against closed forms and published values (1976 standard atmosphere tables, NACA 1135 compressible
flow values, ideal-rocket thrust coefficient limits, beam and truss closed forms, Shigley factors, ISO tensile stress
areas); RK4 fourth-order convergence (observed 3.92–4.00 in vacuum); arm dynamics energy balance; control overshoot
matches second-order theory. Details and tolerances: `docs/VALIDATION.md`.

## Simulated tests completed

Firmware safety rules on the Python model of the sketch; bench HIL harness on the model (and proven to fail broken
firmware); gesture stress suite on synthetic landmarks; trajectory, control and arm-dynamics simulations.

## Physical hardware tests completed

**None.** No board, servo, camera or instrument was connected during development.

## Physical tests still pending

Compiling and running the firmware; bench HIL on the real board; servo power-up and e-stop power interruption;
watchdog stop time with servos powered; arm calibration measurements; servo characterisation; accuracy /
repeatability / sag benchmark; real MediaPipe recordings. Procedures: `docs/hardware/ARM_BRINGUP.md`, `docs/VALIDATION.md`.

## Also fixed

* A toast could raise an error at shutdown after its window was gone.

Not yet tried on a physical Windows PC.
