"""Simulation-to-real accuracy benchmark for the arm.

Workflow (the measured columns are filled in by a person with a calibrated instrument; nothing here invents them):

    1. plan = make_plan(...)                 waypoints inside the safe workspace, payloads, speeds, repeats
    2. sheet = to_csv(plan)                  one row per trial: commanded and predicted tip, empty measured columns
    3. (optional) execute(bridge, plan, confirm)   steps the arm through the waypoints, one supervised move at a time
    4. measure the tip at each stop          e.g. a printed grid + calliper, a dial indicator, or a camera with a
                                             calibrated scale; record the method and its uncertainty
    5. stats = analyse(read_csv(filled))     accuracy and repeatability (ISO 9283 definitions), payload sag, timing

Definitions (ISO 9283:1998, pose accuracy and repeatability, position part):
    accuracy     AP = |mean attained position - commanded position|
    repeatability RP = l_mean + 3 S_l, where l_j = |attained_j - mean attained| and S_l their sample std
Additional: per-trial radial error |attained - predicted|, its mean / RMS / max; tip sag = predicted z - measured z,
regressed on payload (slope in m/kg with its standard error).
"""
import csv
import io
import math
import random
from dataclasses import asdict, dataclass
from typing import Callable, Dict, List, Optional, Sequence

import arm_sim

from . import EngError

FIELDS = ["trial_id", "waypoint", "repeat", "payload_kg", "speed_dps", "cmd_x_m", "cmd_y_m", "cmd_z_m",
          "q_yaw_deg", "q_shoulder_deg", "q_elbow_deg", "q_wrist_deg", "pred_x_m", "pred_y_m", "pred_z_m",
          "meas_x_m", "meas_y_m", "meas_z_m", "meas_uncertainty_m", "settle_time_s", "notes"]


@dataclass
class Trial:
    trial_id: str
    waypoint: int
    repeat: int
    payload_kg: float
    speed_dps: float
    cmd: tuple
    q_deg: tuple
    pred: tuple


def make_plan(arm: arm_sim.ArmSpec = arm_sim.DEFAULT_ARM, n_points: int = 8, payloads: Sequence[float] = (0.0, 0.02),
              speeds: Sequence[float] = (20.0,), repeats: int = 5, seed: int = 1, min_margin: float = 0.25,
              min_height: float = 0.04) -> List[Trial]:
    """Waypoints well inside the workspace (away from singular, stretched poses and the table). Deterministic for a seed.
    Trials of one waypoint are interleaved with others so repeatability includes approach from different poses."""
    if n_points < 1 or repeats < 1:
        raise EngError("need at least one waypoint and one repeat")
    if any(p < 0 for p in payloads) or any(s <= 0 or s > 60 for s in speeds):
        raise EngError("payloads must be >= 0 and speeds in (0, 60] deg/s for a supervised benchmark")
    rng = random.Random(seed)
    pts = []
    tries = 0
    while len(pts) < n_points:
        tries += 1
        if tries > 20000:
            raise EngError("could not find enough safe waypoints; relax min_margin or min_height")
        r = rng.uniform(0.35, 0.85) * arm.max_reach
        yaw = rng.uniform(-60, 60)
        z = rng.uniform(min_height, arm.L0 + 0.6 * (arm.L1 + arm.L2))
        x, y = r * math.cos(math.radians(yaw)), r * math.sin(math.radians(yaw))
        res = arm_sim.inverse(x, y, z, None, arm)
        if res.reachable and res.singularity_margin >= min_margin:
            if all(math.dist((x, y, z), p[0]) > 0.03 for p in pts):
                pts.append(((round(x, 4), round(y, 4), round(z, 4)), res.joints_deg))
    trials: List[Trial] = []
    k = 0
    for payload in payloads:
        for speed in speeds:
            for rep in range(repeats):
                order = list(range(len(pts)))
                rng.shuffle(order)
                for w in order:
                    cmd, q = pts[w]
                    tip = arm_sim.forward(q, arm)["tip"]
                    trials.append(Trial(f"T{k:04d}", w, rep, float(payload), float(speed), cmd, tuple(q), tuple(round(v, 5) for v in tip)))
                    k += 1
    return trials


def to_csv(trials: List[Trial]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, FIELDS)
    w.writeheader()
    for t in trials:
        w.writerow({"trial_id": t.trial_id, "waypoint": t.waypoint, "repeat": t.repeat, "payload_kg": t.payload_kg, "speed_dps": t.speed_dps,
                    "cmd_x_m": t.cmd[0], "cmd_y_m": t.cmd[1], "cmd_z_m": t.cmd[2],
                    "q_yaw_deg": t.q_deg[0], "q_shoulder_deg": t.q_deg[1], "q_elbow_deg": t.q_deg[2], "q_wrist_deg": t.q_deg[3],
                    "pred_x_m": t.pred[0], "pred_y_m": t.pred[1], "pred_z_m": t.pred[2],
                    "meas_x_m": "", "meas_y_m": "", "meas_z_m": "", "meas_uncertainty_m": "", "settle_time_s": "", "notes": ""})
    return buf.getvalue()


def read_csv(text: str) -> List[dict]:
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise EngError("the sheet has no rows")
    missing = [f for f in ("waypoint", "payload_kg", "cmd_x_m", "pred_x_m", "meas_x_m") if f not in rows[0]]
    if missing:
        raise EngError(f"the sheet is missing columns: {', '.join(missing)}")
    return rows


def _f(row: dict, key: str) -> Optional[float]:
    v = (row.get(key) or "").strip()
    if not v:
        return None
    try:
        x = float(v)
    except ValueError:
        raise EngError(f"{row.get('trial_id', '?')}: '{key}' is not a number ({v})") from None
    if not math.isfinite(x):
        raise EngError(f"{row.get('trial_id', '?')}: '{key}' must be finite")
    return x


def _mean(v):
    return sum(v) / len(v)


def _std(v):
    if len(v) < 2:
        return 0.0
    m = _mean(v)
    return math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))


def analyse(rows: List[dict]) -> dict:
    """Statistics from MEASURED rows only (rows without measured x, y, z are skipped and counted)."""
    done, skipped = [], 0
    for r in rows:
        meas = tuple(_f(r, k) for k in ("meas_x_m", "meas_y_m", "meas_z_m"))
        if any(v is None for v in meas):
            skipped += 1
            continue
        done.append({"wp": int(float(r["waypoint"])), "payload": _f(r, "payload_kg") or 0.0,
                     "cmd": tuple(_f(r, k) for k in ("cmd_x_m", "cmd_y_m", "cmd_z_m")),
                     "pred": tuple(_f(r, k) for k in ("pred_x_m", "pred_y_m", "pred_z_m")),
                     "meas": meas, "u": _f(r, "meas_uncertainty_m"), "settle": _f(r, "settle_time_s")})
    if not done:
        raise EngError("no measured rows yet: fill meas_x_m, meas_y_m, meas_z_m from a real measurement first")
    errs = [math.dist(d["meas"], d["pred"]) for d in done]
    out = {"evidence": "measured data (as entered)", "trials_measured": len(done), "trials_without_measurement": skipped,
           "radial_error_mean_m": _mean(errs), "radial_error_rms_m": math.sqrt(_mean([e * e for e in errs])), "radial_error_max_m": max(errs)}
    groups: Dict[tuple, List[dict]] = {}
    for d in done:
        groups.setdefault((d["wp"], d["payload"]), []).append(d)
    per = []
    for (wp, pl), ds in sorted(groups.items()):
        mean = tuple(_mean([d["meas"][i] for d in ds]) for i in range(3))
        ls = [math.dist(d["meas"], mean) for d in ds]
        per.append({"waypoint": wp, "payload_kg": pl, "n": len(ds), "accuracy_AP_m": math.dist(mean, ds[0]["cmd"]),
                    "repeatability_RP_m": (_mean(ls) + 3 * _std(ls)) if len(ds) >= 2 else None})
    out["per_waypoint"] = per
    rps = [p["repeatability_RP_m"] for p in per if p["repeatability_RP_m"] is not None]
    out["repeatability_RP_worst_m"] = max(rps) if rps else None
    out["accuracy_AP_worst_m"] = max(p["accuracy_AP_m"] for p in per)
    sag = [(d["payload"], d["pred"][2] - d["meas"][2]) for d in done]
    xs = [s[0] for s in sag]
    if len(set(xs)) >= 2:
        mx, my = _mean(xs), _mean([s[1] for s in sag])
        sxx = sum((x - mx) ** 2 for x in xs)
        slope = sum((x - mx) * (y - my) for x, y in sag) / sxx
        icpt = my - slope * mx
        resid = [y - (icpt + slope * x) for x, y in sag]
        se = math.sqrt(sum(e * e for e in resid) / max(1, len(sag) - 2) / sxx) if len(sag) > 2 else None
        out["sag_vs_payload"] = {"slope_m_per_kg": slope, "slope_std_error": se, "intercept_m": icpt, "points": sag}
    us = [d["u"] for d in done if d["u"] is not None]
    out["measurement_uncertainty_m"] = max(us) if us else None
    if not us:
        out["warning"] = "no measurement uncertainty entered: the errors cannot be compared with the instrument's resolution"
    settles = [d["settle"] for d in done if d["settle"] is not None]
    if settles:
        out["settle_time_mean_s"], out["settle_time_max_s"] = _mean(settles), max(settles)
    return out


def execute(bridge, trials: List[Trial], confirm: Callable[[Trial], bool], sleep: Callable[[float], None],
            arm: arm_sim.ArmSpec = arm_sim.DEFAULT_ARM, gripper_deg: float = 40.0, dt: float = 0.05) -> List[str]:
    """Step through the trials at their (low) speed. Before EVERY move `confirm(trial)` must return True (a person
    looked and pressed a key); False stops the run. The bridge must already be armed by that person: this function
    never arms. Heartbeats are sent throughout; the arm is e-stopped at the end and on any error."""
    done: List[str] = []
    current = None
    try:
        for t in trials:
            if not confirm(t):
                break
            q_goal = t.q_deg
            if current is None:
                path = [(0.0, q_goal)]
            else:
                path = arm_sim.plan_move(current, q_goal, arm, max_speed_dps=t.speed_dps, dt=dt)
            prev_t = 0.0
            for tt, q in path:
                bridge.send_angles(arm_sim.to_servo_angles(q, arm) + (gripper_deg,))
                sleep(max(0.0, tt - prev_t) or dt)
                prev_t = tt
            for _ in range(int(1.0 / dt)):                    # settle 1 s, keep the watchdog fed
                bridge.heartbeat()
                sleep(dt)
            current = q_goal
            done.append(t.trial_id)
    finally:
        bridge.estop()
    return done


def summary_rows(trials: List[Trial]) -> List[dict]:
    return [asdict(t) for t in trials]
