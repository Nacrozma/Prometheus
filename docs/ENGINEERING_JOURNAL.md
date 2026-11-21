# Engineering journal

A record of genuine engineering development in Prometheus: what was expected, what actually happened, and what
changed. Only things that really happened are recorded; planned experiments are marked **PLANNED**. Dates are the
dates the work was done. All entries so far are software and simulation work: no physical experiment has been
performed yet.

Entry template: title · date · objective · hypothesis · model · expected · actual · difference · investigation ·
root cause · correction · retest · outcome · remaining limitations · lessons.

---

## 1. The e-stop latch did not survive a board reset
* **Date:** 2026-11-21 · **Kind:** design review of firmware (not a hardware observation)
* **Objective:** verify that the emergency stop latches and needs a deliberate re-arm.
* **Hypothesis:** the software ESTOP state latches until CLEAR_ESTOP.
* **Model:** `arm_controller.ino` state machine and its Python model `FirmwareSim`.
* **Expected:** after ESTOP, nothing moves until a person re-arms.
* **Actual:** the latch is a RAM variable. On reset the sketch started in "no link yet", and the first valid
  SET_ANGLES frame set it to OK and moved the arm. A brown-out reset caused by servo current is a common hobby-arm
  failure, and a host that keeps streaming commands would resume motion by itself.
* **Root cause:** boot state treated as "waiting for link" rather than "disarmed".
* **Correction:** new state DISARMED (3) at boot; motion only after CLEAR_ESTOP (the deliberate arm); optional
  normally-closed hardware e-stop loop on D2 that latches ESTOP and blocks re-arming while open (fail-safe default).
  Host: `ArmBridge.arm()`; `arm_demo.py --port` requires typing ARM.
* **Retest:** `test_a_board_reset_never_resumes_motion_by_itself`, `test_hardware_estop_loop_latches_and_blocks_rearming`,
  and the bench harness (`eng.hil`), which now fails any firmware that boots armed. All pass on the model.
* **Outcome:** fixed in software; **hardware behaviour unverified** (the sketch has never been compiled).
* **Lessons:** a safety latch must be held somewhere that survives the failure it protects against; boot is a failure path.

## 2. RK4 apogee converged at second order, not fourth
* **Date:** 2026-11-21 · **Kind:** numerical verification
* **Hypothesis:** halving dt reduces the apogee change about 16× (RK4 is 4th order).
* **Actual:** observed order 1.4–1.9.
* **Investigation:** the integrator itself was correct (vertical-burn and projectile cases matched closed forms to 1e-6).
* **Root cause:** apogee was taken as the largest *sampled* altitude; near a maximum the sampling error is O(dt²).
* **Correction:** locate apogee inside the step where dh/dt changes sign with cubic Hermite interpolation using h and
  dh/dt at both ends (consistent with 4th order).
* **Retest:** vacuum case observed order 4.00, 3.97, 3.92.
* **Remaining:** with the 1976 atmosphere and drag the observed order is ≈ 2: the temperature profile has kinks at layer
  boundaries, so density has a discontinuous derivative and the right-hand side is not smooth. Differences are < 1 mm
  at dt = 0.05 s. Next: step exactly onto layer crossings.
* **Lessons:** a convergence study tests the whole measurement chain, including how a result is extracted.

## 3. Dead-band does not reduce gesture jitter at realistic noise
* **Date:** 2026-11-21 · **Kind:** simulation experiment (synthetic landmarks)
* **Hypothesis:** a larger dead-band reduces the jitter reaching the arm while the hand is still.
* **Model:** `GestureController` (EMA alpha 0.35) on synthetic hands with landmark noise σ = 0.005 (image width units).
* **Expected:** jitter falls as the dead-band grows from 0 to 8 mm.
* **Actual:** 2.43, 2.44, 2.41, 2.37 mm for dead-bands 0, 2, 4, 8 mm: essentially no effect (tuning sweep values).
* **Investigation:** the dead-band compares each raw sample with the filtered position. At this noise level most raw
  samples are already farther than 8 mm from it, so the gate rarely holds, and when it does the result is stick-slip.
  The EMA alpha dominates: alpha 0.15 gives about 1.1 mm jitter but 14 frames of lag; alpha 0.7 gives low lag and more jitter.
* **Correction:** none yet: tuning without the real tracker's noise would be guesswork. The trade-off plot and the
  replay tool are ready.
* **Next:** **PLANNED** — record real MediaPipe sessions (dim/bright light, busy background, fast motion) and re-run the suite.
* **Lessons:** measure a filter on the noise it will really see before tuning it.

## 4. A wrong reference value in my own test
* **Date:** 2026-11-21 · **Kind:** verification process
* **Actual:** the atmosphere test failed at 50 km: model 79.78 Pa, test reference 75.94 Pa.
* **Investigation:** the model's layer base pressures matched the 1976 standard to 1e-5, and the same equations
  matched 0, 11, 20, 32 and 86 km.
* **Root cause:** the reference typed into the test was misremembered; the 1976 table gives 79.78 Pa at 50 km. Two
  other references in the same test file (p0/p at M 2 rounded to the wrong last digit; CF∞ for γ 1.4 written as 1.8114
  instead of 1.8116) were also errors in the test, not the code.
* **Correction:** references corrected from the source values; tolerances unchanged.
* **Lessons:** a failing test can be wrong. Check the reference before touching the model, and never loosen a
  tolerance to make it pass.

## 5. Frame bending-moment sign, caught by the closed form
* **Date:** 2026-11-21 · **Kind:** analytic verification during development
* **Actual:** the first frame solver had the wrong sign for the distributed-load term in M(x) and for the end moments
  used as the maximum.
* **Retest:** fixed before any test ran; simply supported UDL now gives wL²/8, cantilever PL, propped cantilever 3wL/8.
* **Lessons:** derive the free-body sign convention on paper and check the simplest case first.

## 6. The stability check reported a stable loop as marginal
* **Date:** 2026-11-21 · **Kind:** numerical verification
* **Actual:** state feedback with no integral action showed an eigenvalue of exactly 1.
* **Root cause:** the probe included the unused integrator state, which never reaches the output.
* **Correction:** that mode is removed when Ki = 0. The probe still uses the same `step()` code as the simulation.

## 7. Fast moves need dynamic, not static, torque analysis
* **Date:** 2026-11-21 · **Kind:** simulation result (provisional arm parameters)
* **Actual:** a 0.5 s cubic shoulder move with 50 g payload needs a peak of 0.90 N m against 0.57 N m static (+60 %),
  and exceeds 80 % of the MG996R's (listed) torque–speed line early in the move.
* **Consequence:** first physical motion tests use low speed (bring-up §7: slew limit lowered to 30 °/s); the feasibility
  check runs before any planned move.
* **Remaining:** depends on unmeasured masses and servo data.

## 8. Controller comparison in the sandbox
* **Date:** 2026-11-21 · **Kind:** simulation result
* **Actual:** with the benchmark gains, PID (Kp 0.8, Ki 0.4, Kd 0.15) overshoots 47 % under a 1-sample delay; state
  feedback (ωn 6, ζ 0.8) overshoots 1.3 % but keeps a steady offset after the 0.02 N m disturbance because it has no
  integral action.
* **Lessons:** the sandbox shows the textbook trade-off on the actual implementation; the gains are examples, not tuned values.

---

## PLANNED experiments (not done)
1. Bench HIL on the real board, servo power disconnected (`python -m eng.hil --port ... --servo-power-disconnected`).
2. First power-up with horns removed; servo direction check; e-stop power interruption.
3. Watchdog stop time with servos powered, filmed at a known frame rate.
4. Calibration: link lengths, masses, centre-of-mass positions, rest-pose offsets (with uncertainties).
5. Servo characterisation: stall torque (lever + scale), no-load speed (video), holding current.
6. Accuracy / repeatability / sag benchmark with a calibrated instrument.
7. Real gesture recordings under varied conditions; filter tuning on them.
