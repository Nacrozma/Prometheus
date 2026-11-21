"""Bench hardware-in-the-loop checks of the arm firmware.

The same scenarios run against two targets:

    simulation   arm_bridge.FirmwareSim on a virtual clock (automated tests; evidence class "simulation model")
    bench        the real board over a serial port WITH THE SERVO SUPPLY DISCONNECTED (firmware only; the board's
                 USB power runs the microcontroller, no servo can move). The firmware still integrates its slew
                 limiter and reports the commanded pose, so protocol, CRC rejection, arming, e-stop latch and
                 watchdog timing can all be measured without anything moving.

    python -m eng.hil --sim                                       # the model
    python -m eng.hil --port COM5 --servo-power-disconnected      # the board, servos unpowered

This module never powers or moves anything: refusing to run against a port unless the operator states that
the servo supply is disconnected is the point. Physical motion tests are a separate, supervised step in
docs/hardware/ARM_BRINGUP.md.
"""
import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Callable, List, Optional

import arm_bridge as br

YAW = 0
SAFE = (90.0, 90.0, 90.0, 90.0, 40.0)        # equals the default REST_DEG: any command near it is harmless


@dataclass
class Check:
    name: str
    passed: bool
    expected: str
    measured: str
    detail: str = ""


@dataclass
class BenchReport:
    target: str                               # "simulation model" | "bench: firmware only, servo power disconnected"
    checks: List[Check] = field(default_factory=list)
    started: str = ""
    duration_s: float = 0.0

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(c.passed for c in self.checks)

    def to_dict(self) -> dict:
        return {"target": self.target, "passed": self.passed, "started": self.started, "duration_s": round(self.duration_s, 3),
                "checks": [asdict(c) for c in self.checks]}


class _Clock:
    """Virtual time for SimTransport, wall time for a real port."""

    def __init__(self, transport):
        self.t = transport
        self.sim = isinstance(transport, br.SimTransport)

    def now(self) -> float:
        return self.t.now if self.sim else time.monotonic()

    def sleep(self, s: float) -> None:
        if self.sim:
            self.t.advance(s, step=0.005)
        else:
            time.sleep(s)


def _status(host: br.ArmBridge, clock: _Clock, timeout: float = 0.3) -> Optional[dict]:
    host.last_status = None
    host.transport.write(br.encode_frame(br.CMD_GET_STATUS))
    end = clock.now() + timeout
    while True:
        st = host.poll()
        if st is not None or clock.now() >= end:
            return st
        clock.sleep(0.01)


def _corrupt(frame: bytes) -> bytes:
    return frame[:-1] + bytes([frame[-1] ^ 0x5A])


def run_bench(transport, servo_power_disconnected: bool = False, ask: Optional[Callable[[str], bool]] = None) -> BenchReport:
    """Run every scenario. `ask` (optional) is how a person answers manual steps (the hardware e-stop button);
    without it those steps are reported as not run."""
    sim = isinstance(transport, br.SimTransport)
    if not sim and not servo_power_disconnected:
        raise PermissionError("bench checks against a real board run only with the servo supply disconnected; "
                              "disconnect it and pass servo_power_disconnected=True (--servo-power-disconnected)")
    clock = _Clock(transport)
    host = br.ArmBridge(transport)
    rep = BenchReport("simulation model" if sim else "bench: firmware only, servo power disconnected",
                      started=time.strftime("%Y-%m-%dT%H:%M:%S"))
    t0 = time.monotonic()
    add = rep.checks.append

    # 1. boot state
    st = _status(host, clock)
    state = None if st is None else st["state"]
    add(Check("boots disarmed", state == br.STATE_DISARMED, "state 3 (disarmed)",
              "no reply" if st is None else f"state {state} ({br.STATE_NAMES.get(state, '?')})",
              "state 2 means the hardware e-stop loop is open; close it and reset the board" if state == br.STATE_ESTOP else ""))
    if st is None:
        rep.duration_s = time.monotonic() - t0
        return rep
    rest = st["angles_deg"]

    # 2. motion refused while disarmed
    host.send_angles(tuple(min(hi, v + 10) if i == YAW else v for i, (v, (lo, hi)) in enumerate(zip(rest, br.LIMITS_DEG))))
    clock.sleep(0.3)
    st = _status(host, clock)
    moved = st is not None and abs(st["angles_deg"][YAW] - rest[YAW]) > 0.15
    add(Check("motion refused while disarmed", st is not None and not moved, "yaw unchanged",
              "no reply" if st is None else f"yaw {st['angles_deg'][YAW]:.1f} (rest {rest[YAW]:.1f})"))

    # 3. a corrupted arm frame must not arm; garbage must not wedge the parser
    transport.write(_corrupt(br.encode_frame(br.CMD_CLEAR_ESTOP)))
    transport.write(bytes([0x00, 0xA5, 0xFF, 0x13, 0x37, 0xA5, 0x02]))      # junk incl. stray start bytes
    clock.sleep(0.05)
    st = _status(host, clock)
    add(Check("corrupted frame rejected, parser resynchronises", st is not None and st["state"] == br.STATE_DISARMED,
              "still disarmed and answering", "no reply" if st is None else f"state {st['state']}"))

    # 4. the deliberate arm
    host.arm()
    clock.sleep(0.05)
    st = _status(host, clock)
    add(Check("arms on CLEAR_ESTOP", st is not None and st["state"] == br.STATE_OK, "state 0 (ok)",
              "no reply" if st is None else f"state {st['state']}"))

    # 5. slew limit: command +20 deg on yaw, sample progress
    start = _status(host, clock)
    if start is not None:
        a0 = start["angles_deg"][YAW]
        goal = min(br.LIMITS_DEG[YAW][1], a0 + 20.0)
        host.send_angles(tuple(goal if i == YAW else v for i, v in enumerate(start["angles_deg"])))
        tA = clock.now()
        clock.sleep(0.1)
        s1 = _status(host, clock)
        tB = clock.now()
        rate = (s1["angles_deg"][YAW] - a0) / max(1e-6, tB - tA) if s1 else float("nan")
        ok = s1 is not None and 0 < rate <= br.MAX_SLEW_DPS * 1.15
        add(Check("slew limited", ok, f"0 < rate <= {br.MAX_SLEW_DPS:.0f} deg/s (+15% timing tolerance)", f"{rate:.1f} deg/s"))
        clock.sleep(0.4)
        _status(host, clock)

    # 6. watchdog: a short silence keeps the link, a long one holds the pose
    st = _status(host, clock)
    if st is not None:
        a0 = st["angles_deg"][YAW]
        goal = br.LIMITS_DEG[YAW][0] + 1.0 if a0 > 90 else br.LIMITS_DEG[YAW][1] - 1.0     # a long move away
        host.send_angles(tuple(goal if i == YAW else v for i, v in enumerate(st["angles_deg"])))
        clock.sleep(0.3)
        mid = _status(host, clock)                                             # resets the watchdog
        short_ok = mid is not None and mid["state"] == br.STATE_OK
        add(Check("watchdog tolerates 0.3 s of silence", short_ok, "state 0", "no reply" if mid is None else f"state {mid['state']}"))
        if mid is not None:
            clock.sleep(1.2)
            late = _status(host, clock)
            if late is not None:
                travelled = abs(late["angles_deg"][YAW] - mid["angles_deg"][YAW])
                response = travelled / br.MAX_SLEW_DPS                         # time the joint kept moving after the last frame
                remaining = abs(goal - mid["angles_deg"][YAW])
                ok = travelled < remaining - 1.0 and response < 0.5 + 0.06
                add(Check("watchdog stops motion after link loss", ok,
                          "motion stops within 0.5 s (+60 ms tolerance)",
                          f"kept moving {response * 1000:.0f} ms after the last frame (estimated from {travelled:.1f} deg at "
                          f"{br.MAX_SLEW_DPS:.0f} deg/s); state at poll {late['state']}",
                          "the status poll itself re-establishes the link, so state may read 0 again; the frozen angle is the evidence"))

    # 7. software e-stop latch
    host.estop()
    clock.sleep(0.05)
    st = _status(host, clock)
    held = st["angles_deg"][YAW] if st else None
    if st is not None:
        host.heartbeat()
        host.send_angles(tuple(min(hi, max(lo, v + 5)) if i == YAW else v for i, (v, (lo, hi)) in enumerate(zip(st["angles_deg"], br.LIMITS_DEG))))
        clock.sleep(0.3)
    st2 = _status(host, clock)
    latched = st2 is not None and st2["state"] == br.STATE_ESTOP and held is not None and abs(st2["angles_deg"][YAW] - held) < 0.15
    add(Check("e-stop latches (heartbeat and motion do not clear it)", latched, "state 2, pose unchanged",
              "no reply" if st2 is None else f"state {st2['state']}"))
    host.arm()
    clock.sleep(0.05)
    st3 = _status(host, clock)
    add(Check("deliberate re-arm clears the e-stop", st3 is not None and st3["state"] == br.STATE_OK, "state 0",
              "no reply" if st3 is None else f"state {st3['state']}"))

    # 8. hardware e-stop loop (needs a person to press the button)
    if sim:
        transport.firmware.set_estop_loop(False, transport.now)
        st = _status(host, clock)
        host.arm()
        clock.sleep(0.05)
        st_b = _status(host, clock)
        transport.firmware.set_estop_loop(True, transport.now)
        ok = st is not None and st["state"] == br.STATE_ESTOP and st_b is not None and st_b["state"] == br.STATE_ESTOP
        add(Check("hardware e-stop loop latches and blocks re-arm (simulated button)", ok, "state 2 before and after an arm attempt",
                  f"{None if st is None else st['state']} / {None if st_b is None else st_b['state']}"))
    elif ask is not None:
        if ask("Press and HOLD the e-stop button, then answer yes"):
            st = _status(host, clock)
            host.arm()
            clock.sleep(0.05)
            st_b = _status(host, clock)
            ok = st is not None and st["state"] == br.STATE_ESTOP and st_b is not None and st_b["state"] == br.STATE_ESTOP
            add(Check("hardware e-stop loop latches and blocks re-arm", ok, "state 2 before and after an arm attempt",
                      f"{None if st is None else st['state']} / {None if st_b is None else st_b['state']}"))
            ask("Release the e-stop button, then answer yes")
    host.estop()                                                     # always leave it stopped
    rep.duration_s = time.monotonic() - t0
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--sim", action="store_true")
    g.add_argument("--port")
    ap.add_argument("--servo-power-disconnected", action="store_true", help="required with --port: the servo supply is unplugged")
    ap.add_argument("--json", metavar="FILE", help="write the report as JSON")
    args = ap.parse_args(argv)
    if args.port and not args.servo_power_disconnected:
        ap.error("unplug the servo supply first, then add --servo-power-disconnected")
    transport = br.SimTransport() if args.sim else br.SerialTransport(args.port)
    if not args.sim:
        time.sleep(2.0)                                              # most boards reset when the port opens
    try:
        rep = run_bench(transport, servo_power_disconnected=args.servo_power_disconnected,
                        ask=None if args.sim else (lambda q: input(q + " [yes/no] ").strip().lower().startswith("y")))
    finally:
        transport.close()
    for c in rep.checks:
        print(f"{'PASS' if c.passed else 'FAIL'}  {c.name}: expected {c.expected}; measured {c.measured}" + (f"  ({c.detail})" if c.detail else ""))
    print(f"\n{rep.target}: {'all checks passed' if rep.passed else 'FAILED'} in {rep.duration_s:.1f} s")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(rep.to_dict(), f, indent=2)
    return 0 if rep.passed else 1


if __name__ == "__main__":
    sys.exit(main())
