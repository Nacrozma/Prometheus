# Robot arm: hardware architecture and bring-up checklist

Status: **no step below has been performed by the author.** The firmware has never been compiled or run on a
board, and no servo has been powered. This document is the procedure for doing it safely, in order. Record every
result (pass/fail, measured values, date) — in the Engineering Lab (experiment records) or in
`docs/ENGINEERING_JOURNAL.md` — and only then mark a capability as hardware tested in `docs/VALIDATION.md`.

Hazards: pinch points at every joint and in the gripper; sudden motion at power-up (servos jump to `REST_DEG`
at full speed); high current in the servo supply (hot wires, burnt connectors); a dropped arm when power is cut.
Keep hands, hair and loose objects out of reach whenever the servo supply is on.

## 1. Architecture

```
            USB (data + 5 V for the microcontroller only)
  PC ───────────────────────────────── Arduino Uno/Nano (5 V logic)
                                           │  D3 D5 D6 D9 D10  ── servo signal wires
                                           │  D2 ── e-stop loop (NC contact B) ── GND
                                           │  GND ────────────────┐   common ground (mandatory)
                                                                  │
  Mains ── regulated 6 V supply ── fuse ── E-STOP (NC contact A) ── servo power bus (+6 V) ── servo red wires
                                                                  └──────────────── servo power bus (GND) ── servo brown/black wires
                                                    bulk capacitor 1000–2200 µF, low ESR, across the servo bus at the servos
```

* **Servo power never comes from the Arduino's 5 V pin or from USB.** A single MG996R can draw over 2 A at stall;
  USB ports supply 0.5–0.9 A. Drawing servo current through the board resets it (brown-out) and can damage it.
* **Common ground**: the servo supply's negative and the Arduino GND must be joined, or the signal pulses have no
  reference.
* **E-stop with two normally-closed (NC) contacts** (a standard mushroom-head e-stop with a 2-NC contact block):
  * contact A in series with the +6 V servo supply (or switching the coil of a relay/contactor rated for the
    supply current): pressing it **removes servo power** — this is the real emergency stop;
  * contact B wired from D2 to GND: pressing it (or a broken wire) opens the loop, the firmware latches ESTOP and
    refuses to re-arm until the loop is closed and the host deliberately re-arms. This is a second channel that
    makes the software know about the stop; it is not a substitute for contact A.
* **Fuse** on the supply output, slow-blow, rated above the expected continuous current and below the rating of
  the smallest wire it protects.

## 2. Power budget (fill in from YOUR servos' datasheets; then measure)

| Servo (joint) | Datasheet stall current at 6 V | Typical running current | Your value |
|---|---|---|---|
| MG996R (shoulder, elbow) | ~2.5 A (commonly published) | 0.5–0.9 A | |
| MG996R / MG90S (wrist, yaw) | 2.5 A / ~0.7 A | 0.2–0.9 A | |
| SG90 / MG90S (gripper) | ~0.65–0.7 A | 0.1–0.3 A | |

* Supply rating ≥ sum of running currents + one joint at stall, with margin: for 3×MG996R + 2 small servos,
  **≥ 6 A continuous at 6 V** is a reasonable starting point; 10 A gives comfortable margin. Use a supply whose
  voltage stays within the servo rating (most hobby servos: 4.8–6.0 V; check before using 6.8–7.4 V "HV" settings).
* Wire: **18 AWG (0.75–1 mm²)** or heavier for the supply bus over short runs (< 1 m); the servo leads' own
  thin wires are only for one servo each. Use connectors rated for the current (screw terminals, XT30/XT60);
  the 2.54 mm servo connectors are rated around 2–3 A each.
* Measure the real current during the first loaded moves (clamp meter or a bench supply with a current display).

## 3. Before anything is powered

- [ ] Arm unloaded, all servo horns **removed** (servos turn freely without moving the arm).
- [ ] Visual inspection: no bare conductors, no stray strands, connectors fully seated, polarity marked.
- [ ] Multimeter, supply **unplugged**: continuity of the common ground; no short between +6 V and GND on the
      servo bus; e-stop contact A opens the +6 V path when pressed; contact B opens D2–GND when pressed.
- [ ] In `arduino/arm_controller/arm_controller.ino`: `PINS`, `LIMIT_MIN/MAX` and `REST_DEG` match your arm
      (`REST_DEG` is where every servo jumps at power-up: choose a pose that is clear of the table and of itself),
      and `USE_ESTOP_INPUT` is 1 if contact B is wired (with 1 and no loop wired the arm never arms — fail-safe).
      Keep `arm_bridge.py` `LIMITS_DEG` / `REST_DEG` identical (`tests/test_arm_bridge.py` checks this).

## 4. Firmware only (servo supply disconnected)

- [ ] Compile and upload the sketch over USB with the servo supply **disconnected**. Record the IDE version,
      board, and any compiler warnings in the journal (the sketch has never been compiled before).
- [ ] Run the bench checks: `python -m eng.hil --port <COMx or /dev/ttyACMx> --servo-power-disconnected --json bench.json`.
      Expected: every check PASS — boots disarmed, refuses motion while disarmed, rejects a corrupted frame,
      arms on the deliberate command, slew ≤ 90 °/s, watchdog stops motion within 0.5 s, e-stop latches and needs
      a re-arm, and (when you press the button as prompted) the hardware e-stop loop latches and blocks re-arming.
- [ ] Unplug the USB cable while the bench test is sending; reconnect: the board must boot DISARMED again.
- [ ] Attach `bench.json` to an experiment record. This is evidence for *firmware behaviour*, not for motion.

## 5. First servo power (horns still removed)

- [ ] Person at the e-stop. Servo supply on. Every servo jumps to `REST_DEG` — expected.
- [ ] Press the e-stop: servo power must drop (servos go limp). Release, re-arm only by command.
- [ ] Send one small command per joint (2–5°, `ArmBridge(SerialTransport(port))`, `arm()`, `send_angles`):
      correct servo turns, correct direction. Fix pin order / direction in the sketch before going on.
- [ ] Watchdog with power: start a slow move, pull the USB cable: motion stops within ~0.5 s (film it at a known
      frame rate to measure; record the measured stop time).

## 6. Assemble at the rest pose

- [ ] Servo supply **off**. Fit the horns so each joint sits at its rest angle; fasten.
- [ ] Measure the calibration parameters (link lengths, masses, centre-of-mass positions, rest-pose angle errors)
      with `eng.calibration.template()` as the sheet; enter them with `Calibration.set_measured(...)` including
      method, equipment, uncertainty and date.

## 7. Supervised motion, low speed, no load

- [ ] Lower `MAX_SLEW_DPS` to 30 for the first runs (and in `arm_bridge.py`).
- [ ] One joint at a time, small moves, then the full range of each joint inside its limits. Watch for binding,
      cable snag, collisions with the base or table; adjust limits.
- [ ] E-stop test under motion: press during a move; power must drop; record what the arm does when it goes
      limp (does it fall? how far?). If it falls dangerously, add mechanical support or counterbalancing.
- [ ] Only then the gesture pipeline: `python arm_demo.py --camera --dry-run` first (prints commands, opens no
      port), then `--camera --port <port>` (asks you to type ARM).

## 8. Loaded and accuracy tests

- [ ] Payload steps (e.g. 0, 20, 50 g): holding current, temperature after 60 s, sag at the tip.
- [ ] Simulation-to-real benchmark: `eng.arm_benchmark` plans the waypoints and analyses your measured tip
      positions (see `docs/VALIDATION.md`, *Arm*).

Any FAIL stops the procedure: investigate, fix, record the discrepancy in the engineering journal, and repeat
the step.
