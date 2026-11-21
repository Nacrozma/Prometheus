"""Discrete-time closed-loop control sandbox (simulation only).

Plants (linear, integrated EXACTLY over each sample with a zero-order hold, so the plant introduces no numerical
error):
    attitude   single-axis rigid body       J theta'' = u + d          output theta [rad], input torque [N m]
    altitude   vertical point mass          m z''     = u_total - m g + d,  u_total = m g (feed-forward) + u
               with thrust limits 0 <= u_total <= T_max

Controllers (sample period Ts):
    pid        u = Kp e + Ki I + Kd D, derivative on the MEASUREMENT (no derivative kick), first-order filter Tf,
               conditional-integration anti-windup (the integrator stops while the actuator saturates in the same sense)
    state      u = Kp (r - y) - Kd y_dot_measured   (proportional + rate feedback, e.g. a gyro); `place()` gives the
               gains for a chosen natural frequency and damping of J s^2 + Kd s + Kp

Sensor and actuator realism: Gaussian measurement noise (seeded, reproducible), an integer delay of N samples,
actuator saturation, actuator rate limit, step disturbance at a chosen time.

Metrics from the simulated response: rise time (10-90 %), overshoot, settling time (2 % band), steady-state error,
control effort (integral of u^2), peak |u|, disturbance peak deviation and recovery time.

Stability: the linear part of the implemented discrete loop (no saturation, rate limit or noise) is probed to build
its closed-loop state matrix; stable if every eigenvalue has |z| < 1. For PID on J s^2 the continuous-time Routh-Hurwitz
condition (Kd, Kp, Ki > 0 and Kd Kp > J Ki, derivative filter neglected) is also reported.
"""
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from . import EngError
from ._util import num

G0 = 9.80665


@dataclass
class Plant:
    kind: str = "attitude"           # attitude | altitude
    inertia: float = 0.05            # J [kg m^2] (attitude) or mass m [kg] (altitude)
    u_max: float = 0.5               # |u| limit (attitude torque) or T_max (altitude total thrust) [N m or N]
    rate_limit: Optional[float] = None   # max |du/dt| [N m/s or N/s]

    def validate(self):
        if self.kind not in ("attitude", "altitude"):
            raise EngError("plant kind must be attitude or altitude")
        num("inertia", self.inertia, positive=True)
        num("u_max", self.u_max, positive=True)
        if self.kind == "altitude" and self.u_max <= self.inertia * G0:
            raise EngError("maximum thrust must exceed the weight to hover")
        if self.rate_limit is not None:
            num("rate_limit", self.rate_limit, positive=True)


@dataclass
class Controller:
    kind: str = "pid"                # pid | state
    Kp: float = 1.0
    Ki: float = 0.0
    Kd: float = 0.2
    Tf: float = 0.02                 # derivative filter time constant [s]
    Ts: float = 0.01                 # sample period [s]

    def validate(self):
        if self.kind not in ("pid", "state"):
            raise EngError("controller kind must be pid or state")
        for k in ("Kp", "Ki", "Kd"):
            num(k, getattr(self, k), nonneg=True)
        num("Tf", self.Tf, nonneg=True)
        num("Ts", self.Ts, positive=True, hi=1.0)


@dataclass
class Scenario:
    reference: float = 0.2           # step size (rad or m)
    duration: float = 5.0
    noise_std: float = 0.0           # measurement noise std (rad or m)
    rate_noise_std: float = 0.0      # rate-sensor noise std (state feedback)
    delay_samples: int = 0
    disturbance: float = 0.0         # step disturbance (N m or N)
    disturbance_time: float = 3.0
    seed: int = 1


def place(J: float, wn: float, zeta: float) -> Dict[str, float]:
    """Gains of u = Kp e - Kd y_dot for closed-loop poles of J s^2 + Kd s + Kp with natural frequency wn and damping zeta."""
    J, wn, zeta = num("J", J, positive=True), num("wn", wn, positive=True), num("zeta", zeta, positive=True)
    return {"Kp": J * wn * wn, "Kd": 2 * zeta * wn * J}


def _zoh(J: float, Ts: float):
    A = np.array([[1.0, Ts], [0.0, 1.0]])
    B = np.array([Ts * Ts / (2 * J), Ts / J])
    return A, B


class _Loop:
    """One implementation used both for simulation (with nonlinearities) and, linearised, for the stability probe."""

    def __init__(self, plant: Plant, ctrl: Controller, delay: int):
        self.p, self.c, self.delay = plant, ctrl, int(delay)
        self.A, self.B = _zoh(plant.inertia, ctrl.Ts)
        # state: plant (y, ydot), integrator I, filtered derivative D, previous measurement, delay line of y and ydot
        self.n = 5 + 2 * self.delay

    def step(self, s: np.ndarray, r: float, d: float, noise: float, rnoise: float, u_prev: float, linear: bool):
        p, c = self.p, self.c
        y, yd = s[0], s[1]
        I, D, ym_prev = s[2], s[3], s[4]
        line = s[5:]
        if self.delay:
            ym, ydm = line[0], line[1]
            new_line = np.concatenate([line[2:], [y, yd]])
        else:
            ym, ydm, new_line = y, yd, line
        ym, ydm = ym + noise, ydm + rnoise
        e = r - ym
        if c.kind == "pid":
            a = c.Tf / (c.Tf + c.Ts)
            D_new = a * D - (1 - a) * (ym - ym_prev) / c.Ts            # filtered derivative of -y (= de/dt for a step r)
            u = c.Kp * e + c.Ki * I + c.Kd * D_new
        else:
            D_new = 0.0
            u = c.Kp * e - c.Kd * ydm + c.Ki * I
        sat = False
        if not linear:
            lo, hi = (-p.u_max, p.u_max) if p.kind == "attitude" else (-p.inertia * G0, p.u_max - p.inertia * G0)
            if p.rate_limit is not None:
                du = p.rate_limit * c.Ts
                u = min(u_prev + du, max(u_prev - du, u))
            if u > hi or u < lo:
                sat = (u > hi and e > 0) or (u < lo and e < 0)
                u = min(hi, max(lo, u))
        I_new = I if sat else I + c.Ts * e
        x = self.A @ np.array([y, yd]) + self.B * (u + d)
        return np.concatenate([x, [I_new, D_new, ym], new_line]), u

    def closed_loop_matrix(self) -> np.ndarray:
        M = np.zeros((self.n, self.n))
        for j in range(self.n):
            e = np.zeros(self.n)
            e[j] = 1.0
            M[:, j] = self.step(e, 0.0, 0.0, 0.0, 0.0, 0.0, linear=True)[0]
        return M


def stability(plant: Plant, ctrl: Controller, delay_samples: int = 0) -> Dict[str, object]:
    plant.validate()
    ctrl.validate()
    loop = _Loop(plant, ctrl, delay_samples)
    M = loop.closed_loop_matrix()
    if ctrl.Ki == 0:
        # the integrator state then never reaches the output: drop that unobservable mode (its eigenvalue is exactly 1)
        keep = [i for i in range(M.shape[0]) if i != 2]
        M = M[np.ix_(keep, keep)]
    eig = np.linalg.eigvals(M)
    rho = float(np.max(np.abs(eig)))
    out = {"spectral_radius": rho, "discrete_stable": rho < 1.0 - 1e-12, "eigenvalues": [complex(z) for z in eig]}
    if ctrl.kind == "pid":
        J = plant.inertia
        out["routh_hurwitz_continuous"] = {"stable": ctrl.Kd > 0 and ctrl.Kp > 0 and (ctrl.Ki == 0 or ctrl.Kd * ctrl.Kp > J * ctrl.Ki),
                                           "condition": "J s^3 + Kd s^2 + Kp s + Ki: all positive and Kd Kp > J Ki (filter neglected)"}
    return out


def simulate(plant: Plant, ctrl: Controller, sc: Scenario = Scenario()) -> Dict[str, object]:
    plant.validate()
    ctrl.validate()
    num("duration", sc.duration, positive=True)
    if sc.delay_samples < 0:
        raise EngError("delay_samples must be >= 0")
    loop = _Loop(plant, ctrl, sc.delay_samples)
    rng = np.random.default_rng(sc.seed)
    n = int(round(sc.duration / ctrl.Ts))
    s = np.zeros(loop.n)
    u = 0.0
    T, Y, U, E, R = [], [], [], [], []
    for k in range(n + 1):
        t = k * ctrl.Ts
        d = sc.disturbance if t >= sc.disturbance_time else 0.0
        s_next, u = loop.step(s, sc.reference, d, rng.normal(0, sc.noise_std) if sc.noise_std else 0.0,
                              rng.normal(0, sc.rate_noise_std) if sc.rate_noise_std else 0.0, u, linear=False)
        T.append(t)
        Y.append(s[0])
        U.append(u + (plant.inertia * G0 if plant.kind == "altitude" else 0.0))
        E.append(sc.reference - s[0])
        R.append(sc.reference)
        s = s_next
        if not np.all(np.isfinite(s)) or abs(s[0]) > 1e6:
            raise EngError(f"the response diverged at t = {t:.2f} s (unstable loop)")
    T, Y, U, E = (np.array(v) for v in (T, Y, U, E))
    return {"t": T, "y": Y, "u": U, "error": E, "reference": np.array(R),
            "metrics": metrics(T, Y, U - (plant.inertia * G0 if plant.kind == "altitude" else 0.0), sc), "stability": stability(plant, ctrl, sc.delay_samples),
            "assumptions": ["linear rigid plant, exact zero-order-hold discretisation", "Gaussian white measurement noise (seeded)",
                            "saturation and rate limit on the actuator", "simulation only: no hardware"]}


def metrics(t: np.ndarray, y: np.ndarray, u: np.ndarray, sc: Scenario) -> Dict[str, Optional[float]]:
    r = sc.reference
    pre = t < sc.disturbance_time if sc.disturbance else np.ones_like(t, bool)
    tt, yy = t[pre], y[pre]
    out: Dict[str, Optional[float]] = {}
    if r != 0:
        def first(level):
            idx = np.where(yy / r >= level)[0]
            return float(tt[idx[0]]) if len(idx) else None
        t10, t90 = first(0.1), first(0.9)
        out["rise_time_s"] = (t90 - t10) if (t10 is not None and t90 is not None) else None
        out["overshoot_pct"] = float(max(0.0, (np.max(yy) / r - 1) * 100))
        outside = np.where(np.abs(yy - r) > 0.02 * abs(r))[0]
        out["settling_time_s"] = (float(tt[outside[-1] + 1]) if len(outside) and outside[-1] + 1 < len(tt) else (0.0 if not len(outside) else None))
        tail = yy[int(0.9 * len(yy)):]
        out["steady_state_error"] = float(r - np.mean(tail)) if len(tail) else None
    dt = t[1] - t[0] if len(t) > 1 else 0.0
    out["control_effort"] = float(np.sum(u ** 2) * dt)
    out["peak_control"] = float(np.max(np.abs(u)))
    if sc.disturbance:
        post = t >= sc.disturbance_time
        base = float(np.mean(y[pre][-max(1, int(0.2 / dt)):])) if np.any(pre) else r
        dev = np.abs(y[post] - base)
        out["disturbance_peak_deviation"] = float(np.max(dev))
        band = max(0.02 * abs(r), 1e-9)
        outside = np.where(dev > band)[0]
        out["disturbance_recovery_s"] = (float(t[post][outside[-1]] - sc.disturbance_time) if len(outside) and outside[-1] + 1 < len(dev) else
                                         (0.0 if not len(outside) else None))
    return out
