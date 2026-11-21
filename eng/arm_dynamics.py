"""Dynamics of the 4-joint arm: trajectories, joint torques, servo limits.

Model
-----
Rigid multibody chain matching arm_sim.py: yaw (vertical axis), shoulder, elbow and wrist (horizontal axes
perpendicular to the arm plane). Joint torques come from the recursive Newton-Euler algorithm (RNEA), which
evaluates

    tau = M(q) q'' + C(q, q') q' + G(q) + tau_friction

without forming the matrices; `decompose()` forms M, C q' and G explicitly from RNEA calls for inspection.

Bodies (each a rigid composite):
    upper arm   uniform rod (m_link1, centre of mass at com_link1 x L1) + elbow servo as a point mass at the elbow
    forearm     uniform rod (m_link2, com_link2 x L2) + wrist servo as a point mass at the wrist
    tool        uniform rod (m_tool, com_tool x L3) + payload as a point mass at the tip
    turntable   optional yaw inertia I_base_zz (unknown on a hobby arm: default 0, so yaw torque covers the arm only)

Rod inertia about its own centre: (m L^2 / 12)(1 - u u^T) (thin rod). Servo bodies are point masses (their own
rotational inertia and the rotor inertia reflected through the gearbox are neglected). Friction per joint:
viscous b q' plus Coulomb tau_c tanh(q' / 0.01 rad/s) (smoothed sign). Defaults are zero: friction is unknown
until measured, and the result says so.

Servos: a linear torque-speed line, tau_avail(w) = tau_stall (1 - |w| / w_no_load). Datasheet stall torque is not
a usable continuous torque: continuous capability is taken as `continuous_fraction` x stall (default 0.5, a rule of
thumb) and peaks are allowed up to `peak_fraction` x the torque-speed line (default 0.8). All three numbers are
assumptions until the servo is characterised (eng.calibration: servo_stall_torque, servo_no_load_speed).

Validation (tests/test_eng_arm_dynamics.py): static case equals arm_sim.static_torques; a single link reproduces
the analytic pendulum torque I q'' + m g lc cos q; M(q) is symmetric positive definite; along a trajectory the
joint power sum(tau q') equals d(kinetic + potential energy)/dt.
"""
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

import arm_sim

from . import EngError

G = 9.80665
JOINTS = ("yaw", "shoulder", "elbow", "wrist")


# ------------------------------------------------------------------------------ parameters
@dataclass(frozen=True)
class Inertial:
    """Mass properties not in arm_sim.Masses (centre-of-mass fractions, payload, base inertia)."""
    com_link1: float = 0.5
    com_link2: float = 0.5
    com_tool: float = 0.5
    payload_kg: float = 0.0
    I_base_zz: float = 0.0

    def __post_init__(self):
        for n in ("com_link1", "com_link2", "com_tool"):
            if not 0.0 <= getattr(self, n) <= 1.0:
                raise EngError(f"{n} is a fraction of the link length: 0..1")
        if self.payload_kg < 0 or self.I_base_zz < 0:
            raise EngError("payload and base inertia must not be negative")


@dataclass(frozen=True)
class Friction:
    viscous_Nms: Tuple[float, ...] = (0.0, 0.0, 0.0, 0.0)
    coulomb_Nm: Tuple[float, ...] = (0.0, 0.0, 0.0, 0.0)

    def torque(self, qd: np.ndarray) -> np.ndarray:
        b, c = np.array(self.viscous_Nms, float), np.array(self.coulomb_Nm, float)
        return b * qd + c * np.tanh(qd / 0.01)


@dataclass(frozen=True)
class ServoModel:
    name: str
    stall_torque_Nm: float
    no_load_speed_rad_s: float
    continuous_fraction: float = 0.5
    peak_fraction: float = 0.8
    source: str = "manufacturer listing at ~6 V, not verified"

    def available(self, w: float) -> float:
        return max(0.0, self.stall_torque_Nm * (1.0 - abs(w) / self.no_load_speed_rad_s))

    @property
    def continuous_Nm(self) -> float:
        return self.continuous_fraction * self.stall_torque_Nm


def _kgcm(v: float) -> float:
    return v * 0.0980665


def _speed(sec_per_60: float) -> float:
    return math.radians(60.0) / sec_per_60


SERVO_MODELS: Dict[str, ServoModel] = {
    "SG90": ServoModel("SG90", _kgcm(1.8), _speed(0.10), source="listing: 1.8 kg cm, 0.10 s/60 deg at 4.8 V; not verified"),
    "MG90S": ServoModel("MG90S", _kgcm(2.2), _speed(0.08), source="listing: 2.2 kg cm, 0.08 s/60 deg at 6 V; not verified"),
    "MG996R": ServoModel("MG996R", _kgcm(11.0), _speed(0.14), source="listing: 11 kg cm, 0.14 s/60 deg at 6 V; not verified"),
    "DS3218": ServoModel("DS3218", _kgcm(20.0), _speed(0.16), source="listing: ~20 kg cm, 0.16 s/60 deg at 5 V; not verified"),
}


# ------------------------------------------------------------------------------ kinematics of the chain (world frame)
def _skew_I_rod(m: float, L: float, u: np.ndarray) -> np.ndarray:
    return (m * L * L / 12.0) * (np.eye(3) - np.outer(u, u))


def _composite(parts: List[Tuple[float, np.ndarray, np.ndarray]]) -> Tuple[float, np.ndarray, np.ndarray]:
    """(mass, centre, inertia about own centre) for a list of (m, c, I_own)."""
    m = sum(p[0] for p in parts)
    if m <= 0:
        return 0.0, parts[0][1].copy(), np.zeros((3, 3))
    c = sum(p[0] * p[1] for p in parts) / m
    I = np.zeros((3, 3))
    for mk, ck, Ik in parts:
        d = ck - c
        I += Ik + mk * (np.dot(d, d) * np.eye(3) - np.outer(d, d))
    return m, c, I


def chain(q_rad: Sequence[float], arm: arm_sim.ArmSpec, masses: arm_sim.Masses, inertial: Inertial):
    """Joint origins p[i], axes z[i] and body (m, c, I) in the world frame for joint angles in radians."""
    yaw, a1, a2, a3 = q_rad
    e = np.array([math.cos(yaw), math.sin(yaw), 0.0])         # horizontal direction of the arm plane
    zhat = np.array([0.0, 0.0, 1.0])
    pitch_axis = np.cross(e, zhat)                              # positive rotation raises the link
    shoulder = np.array([0.0, 0.0, arm.L0])
    u1 = math.cos(a1) * e + math.sin(a1) * zhat
    u2 = math.cos(a1 + a2) * e + math.sin(a1 + a2) * zhat
    u3 = math.cos(a1 + a2 + a3) * e + math.sin(a1 + a2 + a3) * zhat
    elbow = shoulder + arm.L1 * u1
    wrist = elbow + arm.L2 * u2
    tip = wrist + arm.L3 * u3
    Z0 = np.zeros((3, 3))
    base = (0.0, np.zeros(3), np.diag([0.0, 0.0, inertial.I_base_zz]))
    b1 = _composite([(masses.link1, shoulder + inertial.com_link1 * arm.L1 * u1, _skew_I_rod(masses.link1, arm.L1, u1)),
                     (masses.elbow_servo, elbow.copy(), Z0)])
    b2 = _composite([(masses.link2, elbow + inertial.com_link2 * arm.L2 * u2, _skew_I_rod(masses.link2, arm.L2, u2)),
                     (masses.wrist_servo, wrist.copy(), Z0)])
    b3 = _composite([(masses.tool, wrist + inertial.com_tool * arm.L3 * u3, _skew_I_rod(masses.tool, arm.L3, u3)),
                     (inertial.payload_kg, tip.copy(), Z0)])
    p = [np.zeros(3), shoulder, elbow, wrist]
    z = [zhat, pitch_axis, pitch_axis, pitch_axis]
    return p, z, [base, b1, b2, b3], tip


@dataclass
class ArmModel:
    arm: arm_sim.ArmSpec = arm_sim.DEFAULT_ARM
    masses: arm_sim.Masses = arm_sim.Masses()
    inertial: Inertial = Inertial()
    friction: Friction = Friction()
    gravity: float = G

    @classmethod
    def from_calibration(cls, cal, payload_kg: float = 0.0) -> "ArmModel":
        return cls(cal.arm_spec(), cal.masses(), Inertial(cal.value("com_link1"), cal.value("com_link2"), cal.value("com_tool"), payload_kg))

    def with_payload(self, kg: float) -> "ArmModel":
        i = self.inertial
        return ArmModel(self.arm, self.masses, Inertial(i.com_link1, i.com_link2, i.com_tool, kg, i.I_base_zz), self.friction, self.gravity)

    # --- RNEA ---
    def rnea(self, q: Sequence[float], qd: Sequence[float], qdd: Sequence[float], gravity: Optional[float] = None,
             with_friction: bool = True) -> np.ndarray:
        """Joint torques [N m] (yaw, shoulder, elbow, wrist) for q [rad], q' [rad/s], q'' [rad/s^2]."""
        q, qd, qdd = (np.asarray(v, float) for v in (q, qd, qdd))
        if q.shape != (4,) or qd.shape != (4,) or qdd.shape != (4,):
            raise EngError("q, qd and qdd each need 4 values (yaw, shoulder, elbow, wrist)")
        if not (np.all(np.isfinite(q)) and np.all(np.isfinite(qd)) and np.all(np.isfinite(qdd))):
            raise EngError("joint states must be finite")
        g = self.gravity if gravity is None else gravity
        p, z, bodies, _tip = chain(q, self.arm, self.masses, self.inertial)
        n = 4
        w = [np.zeros(3)] * n
        dw = [np.zeros(3)] * n
        ap = [np.zeros(3)] * n                                    # acceleration of each joint origin
        ac = [np.zeros(3)] * n
        w_prev, dw_prev, a_prev, p_prev = np.zeros(3), np.zeros(3), np.array([0.0, 0.0, g]), np.zeros(3)   # base accelerates up at g
        for i in range(n):
            r = p[i] - p_prev
            a_i = a_prev + np.cross(dw_prev, r) + np.cross(w_prev, np.cross(w_prev, r))
            w_i = w_prev + qd[i] * z[i]
            dw_i = dw_prev + qdd[i] * z[i] + np.cross(w_prev, qd[i] * z[i])
            rc = bodies[i][1] - p[i]
            ac[i] = a_i + np.cross(dw_i, rc) + np.cross(w_i, np.cross(w_i, rc))
            w[i], dw[i], ap[i] = w_i, dw_i, a_i
            w_prev, dw_prev, a_prev, p_prev = w_i, dw_i, a_i, p[i]
        tau = np.zeros(n)
        f_next, n_next = np.zeros(3), np.zeros(3)
        for i in reversed(range(n)):
            m, c, I = bodies[i]
            F = m * ac[i]
            Nc = I @ dw[i] + np.cross(w[i], I @ w[i])
            f_i = F + f_next
            r_next = (p[i + 1] - p[i]) if i + 1 < n else np.zeros(3)
            n_i = n_next + np.cross(r_next, f_next) + np.cross(c - p[i], F) + Nc
            tau[i] = float(np.dot(n_i, z[i]))
            f_next, n_next = f_i, n_i
        if with_friction:
            tau = tau + self.friction.torque(qd)
        return tau

    def mass_matrix(self, q: Sequence[float]) -> np.ndarray:
        M = np.zeros((4, 4))
        for j in range(4):
            e = np.zeros(4)
            e[j] = 1.0
            M[:, j] = self.rnea(q, np.zeros(4), e, gravity=0.0, with_friction=False)
        return M

    def decompose(self, q, qd, qdd) -> Dict[str, np.ndarray]:
        Gq = self.rnea(q, np.zeros(4), np.zeros(4), with_friction=False)
        Cqd = self.rnea(q, qd, np.zeros(4), gravity=0.0, with_friction=False)
        M = self.mass_matrix(q)
        return {"M": M, "Cqd": Cqd, "G": Gq, "friction": self.friction.torque(np.asarray(qd, float)),
                "tau": M @ np.asarray(qdd, float) + Cqd + Gq + self.friction.torque(np.asarray(qd, float))}

    def energy(self, q, qd) -> Tuple[float, float]:
        """(kinetic, potential) energy [J]; used to verify the dynamics by power balance."""
        q, qd = np.asarray(q, float), np.asarray(qd, float)
        p, z, bodies, _ = chain(q, self.arm, self.masses, self.inertial)
        ke = pe = 0.0
        w = np.zeros(3)
        v_origin = np.zeros(3)
        p_prev = np.zeros(3)
        w_prev = np.zeros(3)
        for i in range(4):
            v_origin = v_origin + np.cross(w_prev, p[i] - p_prev)
            w = w_prev + qd[i] * z[i]
            m, c, I = bodies[i]
            vc = v_origin + np.cross(w, c - p[i])
            ke += 0.5 * m * float(vc @ vc) + 0.5 * float(w @ I @ w)
            pe += m * self.gravity * float(c[2])
            w_prev, p_prev = w, p[i]
        return ke, pe


# ------------------------------------------------------------------------------ trajectories
@dataclass
class Trajectory:
    kind: str
    t: np.ndarray                     # [s]
    q: np.ndarray                     # (N, 4) [rad]
    qd: np.ndarray
    qdd: np.ndarray

    @property
    def duration(self) -> float:
        return float(self.t[-1])


def _profile(kind: str, s: np.ndarray, T: float, accel_fraction: float = 0.25):
    """Normalised path s(t) in [0, 1] with first and second time derivatives, for duration T."""
    u = np.clip(s, 0.0, 1.0)
    if kind == "cubic":
        return 3 * u ** 2 - 2 * u ** 3, (6 * u - 6 * u ** 2) / T, (6 - 12 * u) / T ** 2
    if kind == "quintic":
        return 10 * u ** 3 - 15 * u ** 4 + 6 * u ** 5, (30 * u ** 2 - 60 * u ** 3 + 30 * u ** 4) / T, (60 * u - 180 * u ** 2 + 120 * u ** 3) / T ** 2
    if kind == "trapezoid":
        f = accel_fraction                                      # fraction of T spent accelerating (and decelerating)
        vmax = 1.0 / (1.0 - f)                                  # in normalised units (path per T)
        pos, vel, acc = np.zeros_like(u), np.zeros_like(u), np.zeros_like(u)
        a = vmax / f
        m1, m3 = u < f, u > 1 - f
        m2 = ~(m1 | m3)
        pos[m1] = 0.5 * a * u[m1] ** 2
        vel[m1] = a * u[m1]
        acc[m1] = a
        pos[m2] = 0.5 * a * f ** 2 + vmax * (u[m2] - f)
        vel[m2] = vmax
        d = 1.0 - u[m3]
        pos[m3] = 1.0 - 0.5 * a * d ** 2
        vel[m3] = a * d
        acc[m3] = -a
        return pos, vel / T, acc / T ** 2
    raise EngError("trajectory kind must be trapezoid, cubic or quintic")


def plan(q_start_deg: Sequence[float], q_end_deg: Sequence[float], kind: str = "trapezoid", duration: Optional[float] = None,
         max_speed_dps: float = 60.0, accel_fraction: float = 0.25, dt: float = 0.01, arm: arm_sim.ArmSpec = arm_sim.DEFAULT_ARM) -> Trajectory:
    """Synchronised joint-space move (all joints start and stop together, straight line in joint space).
    Without `duration`, the shortest duration that keeps every joint at or below max_speed_dps is used."""
    for label, qq in (("start", q_start_deg), ("end", q_end_deg)):
        if len(qq) != 4:
            raise EngError(f"{label} pose needs 4 joint angles")
        bad = arm_sim.within_limits(qq, arm)
        if bad:
            raise EngError(f"{label} pose: {'; '.join(bad)}")
    if not 0.0 < accel_fraction <= 0.5:
        raise EngError("accel_fraction must be in (0, 0.5]")
    if dt <= 0 or max_speed_dps <= 0:
        raise EngError("dt and max_speed_dps must be positive")
    q0, q1 = np.radians(q_start_deg), np.radians(q_end_deg)
    delta = q1 - q0
    peak_norm = {"cubic": 1.5, "quintic": 1.875, "trapezoid": 1.0 / (1.0 - accel_fraction)}.get(kind)
    if peak_norm is None:
        raise EngError("trajectory kind must be trapezoid, cubic or quintic")
    T_min = peak_norm * float(np.max(np.abs(delta))) / math.radians(max_speed_dps)
    T = float(duration) if duration is not None else max(T_min, dt)
    if T <= 0 or not math.isfinite(T):
        raise EngError("duration must be positive")
    n = max(2, int(math.ceil(T / dt)) + 1)
    t = np.linspace(0.0, T, n)
    s, sd, sdd = _profile(kind, t / T, T, accel_fraction)
    q = q0 + np.outer(s, delta)
    for k in range(0, n, max(1, n // 50)):
        hit = arm_sim.collisions(np.degrees(q[k]), arm)
        if hit:
            raise EngError(f"the move collides at t={t[k]:.2f} s: {hit[0]}")
    return Trajectory(kind, t, q, np.outer(sd, delta), np.outer(sdd, delta))


# ------------------------------------------------------------------------------ analysis
def joint_torques(model: ArmModel, traj: Trajectory) -> np.ndarray:
    return np.array([model.rnea(traj.q[k], traj.qd[k], traj.qdd[k]) for k in range(len(traj.t))])


def evaluate(model: ArmModel, traj: Trajectory, servo_for: Dict[str, str]) -> dict:
    """Torques along the trajectory and a feasibility verdict per joint against its servo."""
    tau = joint_torques(model, traj)
    joints = {}
    flags: List[str] = []
    for j, name in enumerate(JOINTS):
        tj, wj, aj = tau[:, j], traj.qd[:, j], traj.qdd[:, j]
        row = {"peak_torque_Nm": float(np.max(np.abs(tj))), "rms_torque_Nm": float(np.sqrt(np.mean(tj ** 2))),
               "peak_speed_rad_s": float(np.max(np.abs(wj))), "peak_accel_rad_s2": float(np.max(np.abs(aj)))}
        model_name = servo_for.get(name)
        if model_name:
            sv = SERVO_MODELS.get(model_name)
            if sv is None:
                raise EngError(f"unknown servo '{model_name}'. Known: {', '.join(SERVO_MODELS)}")
            avail = np.array([sv.peak_fraction * sv.available(w) for w in wj])
            ratio = np.where(avail > 0, np.abs(tj) / np.maximum(avail, 1e-12), np.inf)
            peak_margin = float(np.min(np.where(np.abs(tj) > 1e-12, avail / np.maximum(np.abs(tj), 1e-12), np.inf)))
            cont_margin = sv.continuous_Nm / row["rms_torque_Nm"] if row["rms_torque_Nm"] > 0 else float("inf")
            speed_ok = row["peak_speed_rad_s"] < sv.no_load_speed_rad_s
            row.update({"servo": model_name, "servo_source": sv.source, "peak_margin": peak_margin, "continuous_margin": cont_margin,
                        "speed_fraction_of_no_load": row["peak_speed_rad_s"] / sv.no_load_speed_rad_s,
                        "feasible": bool(np.all(ratio <= 1.0) and cont_margin >= 1.0 and speed_ok)})
            if not speed_ok:
                flags.append(f"{name}: commanded speed {row['peak_speed_rad_s']:.2f} rad/s reaches the {model_name} no-load speed")
            if peak_margin < 1.0:
                k = int(np.argmax(ratio))
                flags.append(f"{name}: needs {abs(tj[k]):.3f} N m at {wj[k]:.2f} rad/s (t={traj.t[k]:.2f} s) but the {model_name} "
                             f"gives {avail[k]:.3f} N m there ({sv.peak_fraction:.0%} of its torque-speed line)")
            if cont_margin < 1.0:
                flags.append(f"{name}: RMS torque {row['rms_torque_Nm']:.3f} N m exceeds the assumed continuous {sv.continuous_Nm:.3f} N m")
        joints[name] = row
    return {"joints": joints, "feasible": not flags, "flags": flags, "tau": tau, "duration_s": traj.duration,
            "assumptions": ["rigid links, thin-rod inertia, servos as point masses, rotor inertia neglected",
                            "friction " + ("as configured" if any(model.friction.viscous_Nms) or any(model.friction.coulomb_Nm) else "neglected (not yet measured)"),
                            "linear servo torque-speed line from listed stall torque and no-load speed (not verified)",
                            f"continuous capability = {SERVO_MODELS['MG996R'].continuous_fraction:.0%} of stall; peaks limited to {SERVO_MODELS['MG996R'].peak_fraction:.0%} of the line",
                            "link lengths and masses: provisional unless loaded from a measured calibration"]}
