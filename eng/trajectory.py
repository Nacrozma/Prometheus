"""Planar three-degree-of-freedom point-mass trajectory (educational sounding rocket / boost-glide), RK4.

This is a POINT-MASS flight-mechanics model: position and velocity in the vertical plane plus mass. There is no
rigid-body attitude dynamics (no moments, no stability, no 6-DOF): the angle of attack and the thrust direction
are prescribed by the pitch programme.

State y = [x downrange (m), h altitude (m), V speed (m/s), gamma flight-path angle (rad), m mass (kg)]

    dx/dt     = V cos(gamma) Re/(Re + h)
    dh/dt     = V sin(gamma)
    dV/dt     = (T cos(alpha) - D)/m - g sin(gamma)
    dgamma/dt = (T sin(alpha) + L)/(m V) - (g/V - V/(Re + h)) cos(gamma)
    dm/dt     = -mdot while burning

    g = g0 (Re/(Re + h))^2,  D = q S CD,  L = q S CL,  q = rho V^2 / 2,  CD = CD0(M) + k CL^2  (drag polar)
    thrust T = T_vac - pa(h) Ae  (or constant), mdot = T_vac / (Isp_vac g0)

Non-rotating spherical Earth (`flat=True`: Re -> infinity, constant g0). Atmosphere: U.S. Standard Atmosphere 1976
to 86 km, vacuum above. Pitch programmes:
    gravity_turn   vertical until `kick_time`, then gamma is set to 90 deg - kick_angle and the vehicle flies alpha = 0
    ballistic      start at `gamma0_deg` (and `V0`) with alpha = 0 (no thrust if no propellant)
    constant_alpha alpha fixed after the kick (boost-glide style lift)
Integration: classical fourth-order Runge-Kutta, fixed step, with the step shortened to land exactly on burnout and on
the pitch kick (the right-hand side is discontinuous there, which would otherwise spoil 4th-order convergence).
Ground impact is found by interpolating the step that crosses h = 0.
"""
import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import EngError
from . import atmosphere as atm
from ._util import num

G0 = 9.80665
RE = 6371000.0


@dataclass
class Vehicle:
    mass_initial_kg: float
    propellant_kg: float = 0.0
    thrust_vac_N: float = 0.0
    isp_vac_s: float = 250.0
    exit_area_m2: float = 0.0                 # pressure-thrust correction T = T_vac - pa Ae (0: constant thrust)
    ref_area_m2: float = 0.0                  # drag reference area S
    cd0: float = 0.4                          # or a Mach table: cd0_mach = [(M, CD0), ...]
    cd0_mach: Optional[List[Tuple[float, float]]] = None
    k_induced: float = 0.0                    # drag polar CD = CD0 + k CL^2
    cl: float = 0.0                           # lift coefficient (used with constant_alpha programmes)

    def validate(self):
        num("mass_initial_kg", self.mass_initial_kg, positive=True)
        num("propellant_kg", self.propellant_kg, nonneg=True)
        if self.propellant_kg >= self.mass_initial_kg:
            raise EngError("propellant must be less than the initial mass")
        num("thrust_vac_N", self.thrust_vac_N, nonneg=True)
        num("isp_vac_s", self.isp_vac_s, positive=True)
        for k in ("exit_area_m2", "ref_area_m2", "cd0", "k_induced"):
            num(k, getattr(self, k), nonneg=True)
        if self.propellant_kg > 0 and self.thrust_vac_N == 0:
            raise EngError("propellant without thrust: set thrust_vac_N")

    def cd0_at(self, M: float) -> float:
        if not self.cd0_mach:
            return self.cd0
        pts = sorted(self.cd0_mach)
        if M <= pts[0][0]:
            return pts[0][1]
        for (m0, c0), (m1, c1) in zip(pts, pts[1:]):
            if M <= m1:
                return c0 + (c1 - c0) * (M - m0) / (m1 - m0)
        return pts[-1][1]

    @property
    def mdot(self) -> float:
        return self.thrust_vac_N / (self.isp_vac_s * G0) if self.thrust_vac_N > 0 else 0.0

    @property
    def burn_time(self) -> float:
        return self.propellant_kg / self.mdot if self.mdot > 0 else 0.0


@dataclass
class Programme:
    kind: str = "gravity_turn"
    kick_time_s: float = 5.0
    kick_angle_deg: float = 5.0
    gamma0_deg: float = 90.0
    V0_m_s: float = 0.0
    alpha_deg: float = 0.0


def _air(h: float) -> Tuple[float, float, float]:
    if h > 86000.0:
        return 0.0, 0.0, 1e9                   # vacuum (pressure, density, speed of sound)
    s = atm.state(max(0.0, h))
    return s["pressure_Pa"], s["density_kg_m3"], s["speed_of_sound_m_s"]


def _rhs(t, y, veh: Vehicle, prog: Programme, flat: bool, burning: bool, kicked: bool, aero: bool):
    x, h, V, gam, m = y
    r = RE + h
    g = G0 if flat else G0 * (RE / r) ** 2
    pa, rho, a = _air(h) if aero else (0.0, 0.0, 1e9)
    q = 0.5 * rho * V * V
    T = 0.0
    if burning:
        T = max(0.0, veh.thrust_vac_N - pa * veh.exit_area_m2)
    alpha = math.radians(prog.alpha_deg) if (prog.kind == "constant_alpha" and kicked) else 0.0
    cl = veh.cl if (prog.kind == "constant_alpha" and kicked) else 0.0
    M = V / a if a > 0 else 0.0
    cd = veh.cd0_at(M) + veh.k_induced * cl * cl
    D, L = q * veh.ref_area_m2 * cd, q * veh.ref_area_m2 * cl
    dV = (T * math.cos(alpha) - D) / m - g * math.sin(gam)
    vertical_hold = prog.kind in ("gravity_turn", "constant_alpha") and not kicked
    if vertical_hold or V < 1e-6:
        dg = 0.0
    else:
        curv = 0.0 if flat else V / r
        dg = (T * math.sin(alpha) + L) / (m * V) - (g / V - curv) * math.cos(gam)
    dx = V * math.cos(gam) * (1.0 if flat else RE / r)
    dm = -veh.mdot if burning else 0.0
    return np.array([dx, V * math.sin(gam), dV, dg, dm]), {"q": q, "thrust": T, "drag": D, "lift": L, "mach": M, "g": g, "accel": dV}


def simulate(vehicle: Vehicle, programme: Programme = Programme(), dt: float = 0.05, t_max: float = 2000.0, flat: bool = False,
             aero: bool = True, h0: float = 0.0, stop_at_apogee: bool = False) -> Dict[str, object]:
    vehicle.validate()
    dt = num("dt", dt, positive=True, hi=10.0)
    t_max = num("t_max", t_max, positive=True)
    if programme.kind not in ("gravity_turn", "ballistic", "constant_alpha"):
        raise EngError("programme kind must be gravity_turn, ballistic or constant_alpha")
    gam0 = math.radians(90.0 if programme.kind != "ballistic" else num("gamma0_deg", programme.gamma0_deg, lo=-90, hi=90))
    y = np.array([0.0, num("h0", h0, nonneg=True), num("V0_m_s", programme.V0_m_s, nonneg=True), gam0, vehicle.mass_initial_kg])
    t = 0.0
    t_burn = vehicle.burn_time
    kicked = programme.kind == "ballistic"
    rows = []
    events = {"burnout_s": t_burn if t_burn > 0 else None}
    if vehicle.thrust_vac_N > 0 and programme.kind != "ballistic":
        T0 = vehicle.thrust_vac_N - _air(h0)[0] * vehicle.exit_area_m2
        if T0 <= vehicle.mass_initial_kg * G0:
            raise EngError(f"lift-off thrust {T0:.0f} N does not exceed the weight {vehicle.mass_initial_kg * G0:.0f} N: the vehicle cannot rise")

    def record(t, y, burning):
        _, extra = _rhs(t, y, vehicle, programme, flat, burning, kicked, aero)
        rows.append([t, *y, extra["q"], extra["mach"], extra["accel"], extra["thrust"], extra["drag"]])

    record(t, y, t < t_burn)
    impact = None
    while t < t_max - 1e-12:
        burning = t < t_burn - 1e-12
        h_step = dt
        if burning and t + h_step > t_burn:
            h_step = t_burn - t                                   # land exactly on burnout
        if not kicked and t + h_step > programme.kick_time_s:
            h_step = programme.kick_time_s - t                    # and on the pitch kick
        h_step = max(h_step, 1e-12)
        f = lambda tt, yy: _rhs(tt, yy, vehicle, programme, flat, burning, kicked, aero)[0]
        k1 = f(t, y)
        k2 = f(t + h_step / 2, y + h_step / 2 * k1)
        k3 = f(t + h_step / 2, y + h_step / 2 * k2)
        k4 = f(t + h_step, y + h_step * k3)
        y_new = y + h_step / 6 * (k1 + 2 * k2 + 2 * k3 + k4)
        if not np.all(np.isfinite(y_new)):
            raise EngError(f"integration became unstable at t = {t:.2f} s: reduce dt")
        if y_new[4] < vehicle.mass_initial_kg - vehicle.propellant_kg - 1e-9:
            raise EngError("mass fell below the dry mass: integration error, reduce dt")
        if y_new[1] < 0 and t > 0.5:
            s = y[1] / (y[1] - y_new[1])                          # linear interpolation of the crossing
            impact = {"time_s": t + s * h_step, "downrange_m": y[0] + s * (y_new[0] - y[0]), "speed_m_s": y[2] + s * (y_new[2] - y[2])}
            t += s * h_step
            y = y + s * (y_new - y)
            y[1] = 0.0
            record(t, y, burning)
            break
        t += h_step
        y = y_new
        if not kicked and abs(t - programme.kick_time_s) < 1e-9:
            kicked = True
            y[3] = math.radians(90.0 - num("kick_angle_deg", programme.kick_angle_deg, lo=0, hi=89))
        record(t, y, t < t_burn - 1e-12)
        if stop_at_apogee and y[2] * math.sin(y[3]) < 0 and t > t_burn:
            break
    arr = np.array(rows)
    cols = ["t", "x", "h", "V", "gamma", "m", "q", "mach", "accel", "thrust", "drag"]
    data = {c: arr[:, i] for i, c in enumerate(cols)}
    k = int(np.argmax(data["h"]))
    ap_t, ap_h, ap_x = float(data["t"][k]), float(data["h"][k]), float(data["x"][k])
    vz = data["V"] * np.sin(data["gamma"])
    # apogee between samples: cubic Hermite on h(t) using dh/dt = V sin(gamma) at both ends of the step where vz
    # changes sign (4th-order consistent with RK4; reading the maximum sample would only be 2nd order)
    for j in (k - 1, k):
        if 0 <= j < len(vz) - 1 and vz[j] > 0 >= vz[j + 1]:
            t0, t1 = data["t"][j], data["t"][j + 1]
            hh = t1 - t0
            h0_, h1_, d0, d1 = data["h"][j], data["h"][j + 1], vz[j] * hh, vz[j + 1] * hh
            lo_, hi_ = 0.0, 1.0
            dH = lambda s: (6 * s * s - 6 * s) * h0_ + (3 * s * s - 4 * s + 1) * d0 + (-6 * s * s + 6 * s) * h1_ + (3 * s * s - 2 * s) * d1
            for _ in range(80):
                mid = (lo_ + hi_) / 2
                lo_, hi_ = (mid, hi_) if dH(mid) > 0 else (lo_, mid)
            sa = (lo_ + hi_) / 2
            ap_h = float((2 * sa ** 3 - 3 * sa ** 2 + 1) * h0_ + (sa ** 3 - 2 * sa ** 2 + sa) * d0 + (-2 * sa ** 3 + 3 * sa ** 2) * h1_ + (sa ** 3 - sa ** 2) * d1)
            ap_t = float(t0 + sa * hh)
            ap_x = float(data["x"][j] + sa * (data["x"][j + 1] - data["x"][j]))
            break
    summary = {"apogee_m": ap_h, "apogee_time_s": ap_t, "apogee_downrange_m": ap_x,
               "max_speed_m_s": float(np.max(data["V"])), "max_mach": float(np.max(data["mach"])),
               "max_q_Pa": float(np.max(data["q"])), "max_q_time_s": float(data["t"][int(np.argmax(data["q"]))]),
               "max_accel_m_s2": float(np.max(data["accel"])), "burnout_s": events["burnout_s"],
               "burnout_altitude_m": float(np.interp(t_burn, data["t"], data["h"])) if t_burn else None,
               "burnout_speed_m_s": float(np.interp(t_burn, data["t"], data["V"])) if t_burn else None,
               "impact": impact, "steps": len(rows) - 1, "dt_s": dt}
    return {"data": data, "summary": summary,
            "assumptions": ["point mass (3-DOF planar), no attitude dynamics", "non-rotating spherical Earth" if not flat else "flat Earth, constant g",
                            "U.S. Standard Atmosphere 1976 to 86 km, vacuum above" if aero else "no atmosphere",
                            "prescribed pitch programme", "thrust = T_vac - pa Ae, constant mass flow", "fixed-step RK4"]}


def convergence(vehicle: Vehicle, programme: Programme, dts: Sequence[float] = (0.4, 0.2, 0.1, 0.05), quantity: str = "apogee_m",
                **kw) -> Dict[str, object]:
    """Timestep refinement: the quantity for each dt, successive differences and the observed order of accuracy."""
    vals = [simulate(vehicle, programme, dt=d, **kw)["summary"][quantity] for d in dts]
    diffs = [abs(a - b) for a, b in zip(vals, vals[1:])]
    orders = [math.log2(d1 / d2) if d2 > 0 and d1 > 0 else None for d1, d2 in zip(diffs, diffs[1:])]
    richardson = vals[-1] + (vals[-1] - vals[-2]) / 15.0
    return {"dt": list(dts), quantity: vals, "differences": diffs, "observed_order": orders, "richardson_estimate": richardson,
            "note": "RK4 is 4th order: halving dt should shrink the difference ~16x (order ~4) where the solution is smooth"}
