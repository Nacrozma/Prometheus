"""
arm_sim.py - kinematics, torque and motion planning for a 4-joint hobby robot arm, in simulation.

Geometry (the arm lives in a vertical plane that rotates about the base axis):

    yaw  q0   rotation of the whole arm about the vertical base axis
    shoulder q1  upper-arm angle above horizontal            (link length L1)
    elbow    q2  forearm angle relative to the upper arm     (link length L2)
    wrist    q3  tool angle relative to the forearm          (tool length L3 = gripper reach)

    tool pitch phi = q1 + q2 + q3  (angle of the gripper axis above horizontal)
    r = L1 cos q1 + L2 cos(q1+q2) + L3 cos phi          z = L0 + L1 sin q1 + L2 sin(q1+q2) + L3 sin phi
    x = r cos q0,  y = r sin q0

Inverse kinematics is closed-form (two-link IK for the wrist point, then the wrist angle follows
from the requested tool pitch). Every joint has limits that fit a 180-degree hobby servo; the floor
and the base are keep-out zones.

STATUS: simulation only. Nothing here talks to hardware (that is arm_bridge.py, also unverified on
real hardware). Link lengths, masses and servo ratings below are placeholders for a typical
small arm: measure your own. Torque numbers use datasheet stall torque derated to 50%, which is a
rule of thumb, not a guarantee.
"""
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

G = 9.80665
TOL = 1e-9


@dataclass(frozen=True)
class Joint:
    name: str
    min_deg: float
    max_deg: float
    servo_offset_deg: float      # servo angle = joint angle + offset (all joints here have sign +1)

    def servo_range(self) -> Tuple[float, float]:
        return self.min_deg + self.servo_offset_deg, self.max_deg + self.servo_offset_deg


@dataclass(frozen=True)
class ArmSpec:
    L0: float = 0.07             # shoulder axis height above the table [m]
    L1: float = 0.12             # upper arm
    L2: float = 0.12             # forearm
    L3: float = 0.10             # wrist axis to gripper tip
    floor_clearance: float = 0.005
    joints: Tuple[Joint, ...] = (
        Joint("yaw", -90, 90, 90),
        Joint("shoulder", 0, 180, 0),
        Joint("elbow", -150, 30, 150),
        Joint("wrist", -90, 90, 90),
    )

    def __post_init__(self):
        for v in (self.L1, self.L2, self.L3):
            if not (v > 0 and math.isfinite(v)):
                raise ValueError("link lengths must be positive")
        for j in self.joints:
            lo, hi = j.servo_range()
            if lo < -TOL or hi > 180 + TOL:
                raise ValueError(f"joint '{j.name}' needs {lo:.0f}..{hi:.0f} deg of servo travel; a hobby servo gives 0..180")

    @property
    def max_reach(self) -> float:
        return self.L1 + self.L2 + self.L3


DEFAULT_ARM = ArmSpec()
# Datasheet stall torques [kg*cm] at ~6 V. Treat as optimistic: real parts often fall short.
SERVOS = {"SG90": 1.8, "MG90S": 2.2, "MG996R": 11.0, "DS3218": 20.0}


def _wrap(deg: float) -> float:
    return (deg + 180.0) % 360.0 - 180.0


# ------------------------------------------------------------------------------ forward kinematics
def forward(q: Sequence[float], arm: ArmSpec = DEFAULT_ARM) -> Dict[str, Tuple[float, float, float]]:
    """Joint angles in degrees (yaw, shoulder, elbow, wrist) -> 3-D points of base, shoulder, elbow, wrist, tip [m]."""
    if len(q) != 4:
        raise ValueError("expected 4 joint angles")
    yaw, a1, a2, a3 = (math.radians(v) for v in q)
    c0, s0 = math.cos(yaw), math.sin(yaw)

    def pt(r, z):
        return (r * c0, r * s0, z)
    r1, z1 = arm.L1 * math.cos(a1), arm.L0 + arm.L1 * math.sin(a1)
    r2, z2 = r1 + arm.L2 * math.cos(a1 + a2), z1 + arm.L2 * math.sin(a1 + a2)
    r3, z3 = r2 + arm.L3 * math.cos(a1 + a2 + a3), z2 + arm.L3 * math.sin(a1 + a2 + a3)
    return {"base": (0.0, 0.0, 0.0), "shoulder": pt(0.0, arm.L0), "elbow": pt(r1, z1), "wrist": pt(r2, z2), "tip": pt(r3, z3)}


def within_limits(q: Sequence[float], arm: ArmSpec = DEFAULT_ARM, tol_deg: float = 1e-6) -> List[str]:
    return [f"{j.name} {v:.1f} deg is outside {j.min_deg:.0f}..{j.max_deg:.0f}" for j, v in zip(arm.joints, q)
            if not (j.min_deg - tol_deg <= v <= j.max_deg + tol_deg)]


def collisions(q: Sequence[float], arm: ArmSpec = DEFAULT_ARM) -> List[str]:
    """Keep-out checks: the floor, and the base column (the arm may not fold through its own base)."""
    pts = forward(q, arm)
    out = []
    for name in ("elbow", "wrist", "tip"):
        if pts[name][2] < arm.floor_clearance - TOL:
            out.append(f"{name} would be {pts[name][2] * 1000:.0f} mm above the table (minimum {arm.floor_clearance * 1000:.0f} mm)")
    # a point is 'inside the base column' if it is within 25 mm of the axis and below the shoulder
    for name in ("elbow", "wrist", "tip"):
        x, y, z = pts[name]
        if math.hypot(x, y) < 0.025 and z < arm.L0:
            out.append(f"{name} would pass through the base")
    return out


# ------------------------------------------------------------------------------ inverse kinematics
@dataclass
class IKResult:
    reachable: bool
    joints_deg: Optional[Tuple[float, float, float, float]] = None
    pitch_deg: Optional[float] = None
    reason: str = ""
    position_error_m: Optional[float] = None
    elbow: str = ""                      # 'up' (elbow above the shoulder-wrist line) or 'down'
    singularity_margin: float = 0.0      # |sin(elbow angle)|: near 0 the arm is fully stretched or folded


PITCH_PREFERENCE = (-45, -30, -60, -15, -75, 0, -90, 15, 30, 45, 60, 75, 90)


def _ik_for_pitch(x: float, y: float, z: float, phi_deg: float, arm: ArmSpec, behind: bool = False):
    """All candidate solutions (elbow up/down) for one tool pitch, with why each fails, if it does.
    behind=True solves with the arm leaning back over its base: yaw points away from the target and
    the radial coordinate is negative (the same tip position, reached from the other side)."""
    r = math.hypot(x, y)
    yaw = math.degrees(math.atan2(y, x)) if r > 1e-9 else 0.0
    if behind:
        yaw, r = _wrap(yaw + 180.0), -r
    phi = math.radians(phi_deg)
    rw = r - arm.L3 * math.cos(phi)
    zw = z - arm.L0 - arm.L3 * math.sin(phi)
    d2 = rw * rw + zw * zw
    c2 = (d2 - arm.L1 ** 2 - arm.L2 ** 2) / (2 * arm.L1 * arm.L2)
    if c2 > 1 + 1e-9:
        return [], "out of reach: the wrist point is farther than the arm can stretch"
    if c2 < -1 - 1e-9:
        return [], "too close: the wrist point is inside the arm's minimum radius"
    c2 = max(-1.0, min(1.0, c2))
    cands = []
    for sign, label in ((-1.0, "up"), (1.0, "down")):
        q2 = sign * math.acos(c2)
        q1 = math.atan2(zw, rw) - math.atan2(arm.L2 * math.sin(q2), arm.L1 + arm.L2 * math.cos(q2))
        q = (yaw, _wrap(math.degrees(q1)), _wrap(math.degrees(q2)), _wrap(phi_deg - math.degrees(q1) - math.degrees(q2)))
        cands.append((q, label, abs(math.sin(q2))))
    return cands, ""


def inverse(x: float, y: float, z: float, pitch_deg: Optional[float] = None, arm: ArmSpec = DEFAULT_ARM) -> IKResult:
    """Joint angles that put the tip at (x, y, z) metres with the tool at `pitch_deg` above horizontal.
    pitch_deg=None tries a preference list (tool angled down first) and uses the first that fits the
    limits and keeps clear of the floor and base."""
    for name, v in (("x", x), ("y", y), ("z", z)):
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
            return IKResult(False, reason=f"{name} must be a finite number")
    if pitch_deg is not None and (not isinstance(pitch_deg, (int, float)) or not math.isfinite(pitch_deg)):
        return IKResult(False, reason="pitch must be a finite number")
    if math.hypot(x, y) < 1e-9 and abs(z) < 1e-9:
        return IKResult(False, reason="target is at the base origin")
    pitches = [float(pitch_deg)] if pitch_deg is not None else [float(p) for p in PITCH_PREFERENCE]
    last_reason = "no pitch gives a solution within the joint limits"
    for phi in pitches:
        for behind in (False, True):                  # in front of the base first; leaning back only if that fails
            cands, why = _ik_for_pitch(x, y, z, phi, arm, behind)
            if not cands:
                last_reason = why
                continue
            for q, label, margin in sorted(cands, key=lambda c: c[1] != "up"):     # prefer elbow-up
                problems = within_limits(q, arm) or collisions(q, arm)
                if problems:
                    last_reason = problems[0]
                    continue
                tip = forward(q, arm)["tip"]
                err = math.dist(tip, (x, y, z))
                return IKResult(True, tuple(round(v, 6) for v in q), phi, "", err, label, margin)
    return IKResult(False, reason=last_reason)


# ------------------------------------------------------------------------------ servos
def to_servo_angles(q: Sequence[float], arm: ArmSpec = DEFAULT_ARM) -> Tuple[float, ...]:
    bad = within_limits(q, arm)
    if bad:
        raise ValueError("; ".join(bad))
    return tuple(round(v + j.servo_offset_deg, 3) for j, v in zip(arm.joints, q))


def from_servo_angles(servo: Sequence[float], arm: ArmSpec = DEFAULT_ARM) -> Tuple[float, ...]:
    return tuple(round(v - j.servo_offset_deg, 3) for j, v in zip(arm.joints, servo))


def pulse_us(servo_deg: float, min_us: int = 500, max_us: int = 2500) -> int:
    """Typical hobby-servo pulse for an angle. Real servos differ: calibrate min/max per servo."""
    if not 0 <= servo_deg <= 180:
        raise ValueError("servo angle must be 0..180")
    return round(min_us + (max_us - min_us) * servo_deg / 180.0)


# ------------------------------------------------------------------------------ torque
@dataclass(frozen=True)
class Masses:
    link1: float = 0.04          # kg, uniform links (centre of mass at mid-length)
    link2: float = 0.03
    elbow_servo: float = 0.055   # servos sitting at the joints
    wrist_servo: float = 0.055
    tool: float = 0.06           # gripper including its servo, centre at mid tool length


def static_torques(q: Sequence[float], payload_kg: float = 0.0, arm: ArmSpec = DEFAULT_ARM,
                   masses: Masses = Masses()) -> Dict[str, float]:
    """Holding torque [N m] at the shoulder, elbow and wrist in pose q. Static, no friction, no
    acceleration; the shoulder servo's own mass and the base are ignored."""
    if payload_kg < 0:
        raise ValueError("payload must not be negative")
    if len(q) < 4:
        raise ValueError("expected 4 joint angles")
    a1, a2, a3 = (math.radians(v) for v in q[1:4])
    c1, c12, c123 = math.cos(a1), math.cos(a1 + a2), math.cos(a1 + a2 + a3)
    r_elbow = arm.L1 * c1
    r_wrist = r_elbow + arm.L2 * c12
    r_tip = r_wrist + arm.L3 * c123
    # (mass, radial position of its centre of mass, first joint that carries it: 0 shoulder, 1 elbow, 2 wrist)
    pieces = [
        (masses.link1, r_elbow / 2, 0),
        (masses.elbow_servo, r_elbow, 0),
        (masses.link2, r_elbow + arm.L2 * c12 / 2, 1),
        (masses.wrist_servo, r_wrist, 1),
        (masses.tool, r_wrist + arm.L3 * c123 / 2, 2),
        (payload_kg, r_tip, 2),
    ]
    pivots = {"shoulder": (0.0, 0), "elbow": (r_elbow, 1), "wrist": (r_wrist, 2)}
    return {name: abs(sum(m * G * (rc - pivot) for m, rc, first in pieces if first >= idx))
            for name, (pivot, idx) in pivots.items()}


def servo_check(torques: Dict[str, float], servo_for: Dict[str, str], derate: float = 0.5) -> Dict[str, Dict[str, float]]:
    """Compare holding torque with derated stall torque. margin > 1 means enough, with that much to spare."""
    out = {}
    for joint, t in torques.items():
        model = servo_for.get(joint)
        if model is None:
            continue
        if model not in SERVOS:
            raise ValueError(f"unknown servo '{model}'. Known: {', '.join(SERVOS)}")
        usable = SERVOS[model] * 0.0980665 * derate
        out[joint] = {"holding_Nm": t, "usable_Nm": usable, "margin": (usable / t) if t > 0 else float("inf"), "servo": model}
    return out


def max_payload(q: Sequence[float], servo_for: Dict[str, str], arm: ArmSpec = DEFAULT_ARM, derate: float = 0.5) -> float:
    """Largest payload [kg] every listed joint can hold in pose q (bisection; 0.0 if the arm can't even hold itself)."""
    def ok(p):
        return all(v["margin"] >= 1.0 for v in servo_check(static_torques(q, p, arm), servo_for, derate).values())
    if not ok(0.0):
        return 0.0
    lo, hi = 0.0, 5.0
    if ok(hi):
        return hi
    for _ in range(50):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if ok(mid) else (lo, mid)
    return lo


# ------------------------------------------------------------------------------ motion
def plan_move(q_start: Sequence[float], q_end: Sequence[float], arm: ArmSpec = DEFAULT_ARM,
              max_speed_dps: float = 60.0, dt: float = 0.02) -> List[Tuple[float, Tuple[float, ...]]]:
    """Joint-space move with a smoothstep profile (zero velocity at both ends), slow enough that no joint
    exceeds max_speed_dps. Raises ValueError if an endpoint breaks limits or any waypoint hits a keep-out zone."""
    for label, q in (("start", q_start), ("end", q_end)):
        bad = within_limits(q, arm)
        if bad:
            raise ValueError(f"{label} pose: {'; '.join(bad)}")
    if max_speed_dps <= 0 or dt <= 0:
        raise ValueError("speed and dt must be positive")
    delta = [e - s for s, e in zip(q_start, q_end)]
    # smoothstep peaks at 1.5x the mean speed, so size the duration for that peak
    duration = max(1.5 * max(abs(d) for d in delta) / max_speed_dps, dt)
    steps = max(1, math.ceil(duration / dt))
    path = []
    for i in range(steps + 1):
        u = i / steps
        s = u * u * (3 - 2 * u)
        q = tuple(a + d * s for a, d in zip(q_start, delta))
        hit = collisions(q, arm)
        if hit:
            raise ValueError(f"the move would collide at t={i * duration / steps:.2f}s: {hit[0]}")
        path.append((round(i * duration / steps, 6), q))
    return path


# ------------------------------------------------------------------------------ workspace & drawing
def workspace(arm: ArmSpec = DEFAULT_ARM, step: float = 0.01, pitch_deg: Optional[float] = None) -> Dict[str, object]:
    """Sample the vertical reach plane (yaw = 0). Returns reachable points and summary numbers."""
    pts = []
    n_r, n_z = int(arm.max_reach / step) + 1, int((arm.L0 + arm.max_reach) / step) + 1
    for i in range(n_r):
        for k in range(n_z):
            r, z = i * step, k * step
            if r < step / 2 and z < arm.L0 + step:
                continue
            if inverse(r, 0.0, z, pitch_deg, arm).reachable:
                pts.append((r, z))
    if not pts:
        return {"points": [], "max_radius_m": 0.0, "max_height_m": 0.0, "samples": n_r * n_z}
    return {"points": pts, "max_radius_m": max(p[0] for p in pts), "max_height_m": max(p[1] for p in pts),
            "samples": n_r * n_z, "reachable_fraction": len(pts) / (n_r * n_z)}


def render_svg(q: Sequence[float], arm: ArmSpec = DEFAULT_ARM, target: Optional[Tuple[float, float, float]] = None,
               points: Optional[List[Tuple[float, float]]] = None, title: str = "") -> str:
    """Side view (radial plane) and top view of the arm as a small standalone SVG string."""
    pts = forward(q, arm)
    scale = 520.0 / (arm.max_reach * 2.2)
    ox, oy = 60.0, 330.0

    def side(p):
        r = math.hypot(p[0], p[1]) * (1 if p[0] >= 0 else -1)
        return ox + r * scale, oy - p[2] * scale
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 700 400" font-family="monospace" font-size="12">',
             '<rect width="700" height="400" fill="#0b1020"/>',
             f'<line x1="20" y1="{oy}" x2="400" y2="{oy}" stroke="#46506e" stroke-width="2"/>']
    if points:
        for r, z in points[::2]:
            cx, cy = ox + r * scale, oy - z * scale
            parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="1.6" fill="#24406f"/>')
    chain = [side(pts[n]) for n in ("shoulder", "elbow", "wrist", "tip")]
    parts.append(f'<rect x="{ox - 14}" y="{oy - arm.L0 * scale:.1f}" width="28" height="{arm.L0 * scale:.1f}" fill="#2a3358"/>')
    parts.append('<polyline fill="none" stroke="#7fd4ff" stroke-width="7" stroke-linecap="round" stroke-linejoin="round" points="'
                 + " ".join(f"{x:.1f},{y:.1f}" for x, y in chain) + '"/>')
    for x, y in chain[:-1]:
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="#ffd166"/>')
    tx, ty = chain[-1]
    parts.append(f'<circle cx="{tx:.1f}" cy="{ty:.1f}" r="5" fill="#ef476f"/>')
    if target:
        gx, gy = side(target)
        parts.append(f'<circle cx="{gx:.1f}" cy="{gy:.1f}" r="9" fill="none" stroke="#06d6a0" stroke-width="2"/>')
    # top view
    tcx, tcy, ts = 550.0, 200.0, 520.0 / (arm.max_reach * 2.4) * 0.45
    parts.append(f'<circle cx="{tcx}" cy="{tcy}" r="{arm.max_reach * ts:.1f}" fill="none" stroke="#46506e" stroke-dasharray="4 4"/>')
    parts.append(f'<line x1="{tcx}" y1="{tcy}" x2="{tcx + pts["tip"][0] * ts:.1f}" y2="{tcy - pts["tip"][1] * ts:.1f}" stroke="#7fd4ff" stroke-width="5" stroke-linecap="round"/>')
    parts.append(f'<circle cx="{tcx}" cy="{tcy}" r="6" fill="#ffd166"/>')
    parts.append(f'<text x="20" y="24" fill="#cbd5ff">{title or "arm pose (side view, top view right)"}</text>')
    parts.append(f'<text x="20" y="44" fill="#8b95b8">joints deg: {", ".join(f"{v:.0f}" for v in q)}   tip: ' +
                 ", ".join(f"{v * 100:.1f}" for v in pts["tip"]) + ' cm</text>')
    parts.append("</svg>")
    return "\n".join(parts)
