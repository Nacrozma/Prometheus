# Engineering validation

What each engineering model in Prometheus has been checked against, how, and how strongly it can be trusted.
Updated 2026-11-21 (eng model version 1.0.0). Plots and numbers are regenerated with
`python tools/eng_benchmarks.py` into `docs/validation/` (`benchmarks.json` holds every number quoted here).

## Status classes

| Class | Meaning |
|---|---|
| **Analytically verified** | reproduces a closed-form solution or a published reference value within a stated tolerance |
| **Numerically verified** | passes convergence or consistency checks (refinement order, energy balance, symmetry, equilibrium) |
| **Simulation tested** | exercised end to end in simulation only |
| **Hardware tested** | measured on the physical system, with the data attached to an experiment record |
| **Awaiting physical validation** | software, procedure and analysis are ready; the physical experiment has not been done |

**No capability in this document is hardware tested.** No board, servo, camera or measuring instrument has been
connected during development; every physical check below is *awaiting physical validation*. The experiment store
refuses the "hardware tested" status unless the record is a hardware experiment with measured data attached.

## Summary

| Area | Model | Status | Evidence |
|---|---|---|---|
| Arm firmware protocol | CRC-8 framing, parser resync | analytically verified (CRC check value 0xF4 for "123456789"), simulation tested; **hardware: awaiting** | `tests/test_arm_bridge.py` |
| Arm firmware safety | boot disarmed, e-stop latch, hardware e-stop loop, watchdog, slew, clamping | simulation tested (Python model of the sketch + bench HIL harness); **hardware: awaiting** | `tests/test_arm_bridge.py`, `tests/test_eng_mechatronics.py`, `python -m eng.hil --sim` |
| Arm dynamics | recursive Newton–Euler, M(q), C q', G(q), friction | analytically verified (static case, pendulum), numerically verified (energy balance, SPD mass matrix); **physical parameters provisional** | `tests/test_eng_arm_dynamics.py` |
| Arm accuracy | simulation-to-real benchmark | **awaiting physical validation** (planner, sheet, analysis ready) | `eng/arm_benchmark.py` |
| Gesture control | stress suite, filter trade-off | simulation tested on synthetic landmarks; **real tracker: awaiting** | `tests/test_eng_arm_dynamics.py::GestureLab` |
| 2-D trusses | direct stiffness | analytically verified | `tests/test_eng_structures_machine.py` |
| 2-D frames | direct stiffness, Euler–Bernoulli | analytically verified | same |
| Fatigue / machine design | Kt, q, Kf, Marin, Goodman, Soderberg, Gerber, Basquin, shaft, bolts | analytically verified against the method's formulas and standard tabulated values | same |
| Design optimisation | sweep + Pareto front | numerically verified (non-domination, monotonicity) | same |
| Atmosphere | U.S. Standard Atmosphere 1976, 0–86 km | analytically verified (published layer and table values) | `tests/test_eng_aerospace.py` |
| Compressible flow | isentropic, normal/oblique shock, Prandtl–Meyer | analytically verified (NACA 1135 / textbook values) | same |
| Propulsion | ideal nozzle | analytically verified (CF limits, internal consistency); **not a measured engine** | same |
| Trajectory | planar 3-DOF point mass, RK4 | analytically verified (projectile, rocket equation, energy), numerically verified (4th-order convergence) | same |
| Control | discrete PID / state feedback | analytically verified (2nd-order overshoot), numerically verified (discrete eigenvalues vs Routh–Hurwitz) | same |
| Uncertainty | GUM linear, Monte Carlo, Type A/B | analytically verified (power-law propagation), numerically verified (MC vs linear) | `tests/test_eng_lab.py` |
| Experiments & reports | records, provenance hash, re-run, reports | simulation tested (bit-identical re-run) | same |

---

## Mechanical validation (robotic arm)

### Firmware safety (simulation model + bench harness)
Checks in `eng.hil.run_bench` (the same code runs against the real board with **servo power disconnected**):
boots disarmed; motion refused while disarmed; corrupted frame rejected and the parser resynchronises; arms only
on the deliberate command; slew ≤ 90 °/s; watchdog stops motion within 0.5 s of the last frame; the software e-stop
latches (heartbeats and motion commands do not clear it); a deliberate re-arm clears it; the hardware e-stop loop
latches and blocks re-arming. The harness is itself tested: it **fails** a firmware without a watchdog, one that
boots armed, and one that slews too fast (`tests/test_eng_mechatronics.py`).

| Check | Simulation model | Real board (servo power off) | Real board (servos powered) |
|---|---|---|---|
| all bench checks | pass | **awaiting** | — |
| watchdog stop time | 500 ms (by construction of the model) | **awaiting** | **awaiting** (video at known frame rate) |
| e-stop cuts servo power | n/a (hardware) | n/a | **awaiting** (procedure: `docs/hardware/ARM_BRINGUP.md` §5, §7) |

### Dynamic torque
* Static case (q' = q'' = 0) equals the existing holding-torque model `arm_sim.static_torques` to 1e-9 N m in four poses with and without payload.
* A single massive link reproduces I q'' + m g l_c cos q exactly.
* M(q) is symmetric positive definite at 20 random poses.
* Power balance along a quintic move: Σ τ·q' equals d(KE + PE)/dt to within 1e-4 of the peak power.
* Benchmark (`arm_torque_vs_time.svg`): a 0.5 s cubic shoulder move with 50 g payload needs a dynamic peak of
  0.90 N m against a static peak of 0.57 N m, and the feasibility check flags it against the MG996R torque–speed line.

**Limitations:** link lengths, masses and centre-of-mass positions are provisional placeholders; servo stall torque,
no-load speed, the 50 % continuous fraction and friction are unverified assumptions.

### Accuracy, repeatability, sag — awaiting physical validation
Method (ISO 9283 position accuracy AP and repeatability RP = l̄ + 3 S_l): `eng.arm_benchmark.make_plan` chooses
waypoints away from singular poses and the table, interleaves repeats, adds payload steps; `to_csv` writes the sheet;
a person measures the tip (e.g. calliper against a printed grid, dial indicator, or calibrated camera) and records the
instrument uncertainty; `analyse` computes radial error statistics, AP, RP, and sag-vs-payload regression with its
standard error. The analysis refuses to run without measured rows. There is **no simulated-vs-measured plot** yet
because there is no measurement.

### Gesture pipeline (synthetic landmarks)
Standard stress suite (noise, single-frame glitches, 10 % dropouts, 10 % occlusion, 2× speed, hand loss): no command
change while the hand is not usable in any scenario; on hand loss the controller holds for 15 frames then stops;
glitches and occlusions are rejected. Filter trade-off (`gesture_jitter_vs_lag.svg`): lower EMA alpha reduces jitter
and increases lag. Recordings of the real MediaPipe tracker (`arm_demo.py --camera --record`) are **awaiting**.

---

## Structural validation

| Case | Reference | Result |
|---|---|---|
| determinate 7-member truss | method of joints (`engineering.truss`) | member forces equal within 1e-6 of the load |
| symmetric three-bar truss (indeterminate, θ = 20…60°) | F_c = P/(1+2cos³θ), F_s = P cos²θ/(1+2cos³θ) | equal to 8 decimal places; displacement = F_c L/(EA) |
| support settlement | indeterminate truss must develop force | force ≠ 0 only when settled |
| cantilever tip load | δ = PL³/3EI, θ = PL²/2EI | exact (`structure_cantilever_deflection.svg`: max nodal error 5e-17 m) |
| simply supported UDL | M = wL²/8, δ_mid = 5wL⁴/384EI | exact (consistent loads give exact nodal values) |
| fixed–fixed UDL | M_end = wL²/12 | exact |
| propped cantilever UDL (indeterminate) | R_B = 3wL/8 | exact |
| portal frame | equilibrium, symmetry | residual < 1e-6 N, symmetric reactions |
| mechanism | must be refused | error names the free directions |

Every solution reports its equilibrium residual, degree of indeterminacy and condition number. **Limitations:** linear
elastic, small displacement, Euler–Bernoulli, no buckling / P-δ, no internal hinges; not a general FE package.

## Fatigue and machine design
ka = 4.51·520^-0.265 = 0.860 (machined, 520 MPa) and kb = 1.24·32^-0.107 = 0.856 (32 mm) — the standard Shigley
values; Se' = 0.5 Sut (≤ 1400 MPa) / 700 MPa; Inglis Kt = 3 for a circular hole; q in (0, 1) and Kf = 1 + q(Kt − 1)
< Kt; Goodman, Soderberg and Gerber factors satisfy their defining equations exactly, Soderberg < Goodman < Gerber;
Basquin line passes through f·Sut at 10³ and Se at 10⁶ cycles with f = 0.896 at 490 MPa (Shigley: ≈ 0.9);
DE-Goodman shaft sizing re-checked at the sized diameter returns the target factor of safety; ISO metric tensile
stress areas 57.99 mm² (M10×1.5, ISO 58.0) and 84.27 mm² (M12×1.75, ISO 84.3). **Limitations:** educational
methods, steel coefficients, user-supplied Kt for real geometry; not certified design.

## Aerospace validation

| Model | Reference | Result |
|---|---|---|
| 1976 atmosphere | layer base pressures 22 632.06 … 3.956420 Pa; table values at 0, 11, 20, 32, 50, 86 km | within 1e-5 (bases), 2e-4 (p), 1e-3 (ρ); T within 0.01 K |
| isentropic M = 2 | p0/p = 7.8244, T0/T = 1.8, A/A* = 1.6875, μ = 30° | match |
| normal shock M = 2 | M2 = 0.5774, p2/p1 = 4.5, ρ2/ρ1 = 2.6667, T2/T1 = 1.6875, p02/p01 = 0.7209 | match |
| oblique shock M = 2, θ = 10° | β = 39.31°, M2 = 1.6405, p2/p1 = 1.7066; θ_max = 22.97° | match; detachment refused above θ_max |
| Prandtl–Meyer | ν(2) = 26.3798°; 10° expansion from M 2 → M 2.3849 | match |
| ideal nozzle | CF∞ = 2.2466 (γ 1.2), 1.8116 (γ 1.4); thrust = ṁ v_e + (p_e − p_a) A_e | match; internal identity to 1e-9 |
| trajectory, vacuum projectile | apex V²sin²γ/2g, range V²sin2γ/g, time 2V sinγ/g | within 1e-5 m / 1e-4 m / 1e-5 s |
| trajectory, vertical burn | v = v_e ln(m0/m) − g t, h(t) closed form | within 1e-6 m/s, 1e-5 m |
| trajectory, vacuum coast, spherical gravity | specific energy constant | drift < 1e-9 relative |
| RK4 order (vacuum) | 4 | observed 4.00, 3.97, 3.92 (`rk4_convergence.svg`) |
| RK4 order (with atmosphere + drag) | — | observed ≈ 2 (2.25, 2.14, 1.70): the 1976 temperature profile has kinks at layer boundaries, so density has a discontinuous derivative and the right-hand side is not smooth; apogee differences are already < 1 mm at dt = 0.05 s |
| control, state feedback ζ 0.7 | overshoot exp(−ζπ/√(1−ζ²)) = 4.599 % | 4.600 % |
| control, discrete poles | exp(s Ts) of the design | within 2e-5 (zero-order-hold effect O(ωn Ts)) |
| control, unstable PID | Routh–Hurwitz Kd Kp > J Ki violated | discrete loop also unstable; simulation diverges and is reported |

Example outputs (model, not measurement): the benchmark sounding rocket (50 kg, 25 kg propellant, 4 kN, Isp 220 s,
CD0 0.45, 150 mm diameter) reaches 22.96 km apogee, Mach 2.95, max q 270 kPa; the benchmark nozzle (7 MPa, 3300 K,
γ 1.2, 22 g/mol, ε 20) gives ideal Isp 268.8 s at sea level and 319.7 s in vacuum, c* 1722 m/s.

## Experimental methodology (for the physical tests still to come)
Every hardware experiment is recorded with `eng.experiments` (kind `hardware`): equipment and its calibration,
measurement method, units, instrument uncertainty (Type B) and repeat count (Type A via `eng.uncertainty.measurement_summary`),
environmental conditions, raw data (CSV, `DataLogger` for timestamped series), processing (the analysis function and
model version), and known limitations. Minimum repeat count: 3 per point (5 for repeatability). Results are reported
with expanded uncertainty U95. The status becomes *hardware tested* only with attached data.

## Known gaps and next validation steps
1. Run the bench HIL against the real board (servo power off) — first physical evidence.
2. Measure the arm parameters (calibration sheet) and replace the provisional values.
3. Measure watchdog stop time and e-stop behaviour with servos powered (video at a known frame rate).
4. Accuracy/repeatability/sag benchmark with a calibrated instrument.
5. Record real MediaPipe sessions under varied lighting and replay them through the gesture suite; tune alpha / dead-band on that data.
6. Characterise a servo (stall torque, no-load speed, continuous capability) to replace the listing values.
7. Event-locate atmosphere layer crossings in the trajectory integrator to restore 4th-order convergence with drag.
