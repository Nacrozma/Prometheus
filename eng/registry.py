"""Runnable engineering models with plain parameters and JSON-safe results.

One entry per model: a function taking keyword parameters (numbers, strings, lists, dicts: what a tool call or a form
supplies), returning {"results": ..., "formula"/"assumptions": ..., "series": {name: {"x": [...], "y": [...], ...}}}.
`run(name, **params)` never raises: errors come back as {"status": "error", "message": ...}. Experiments, reports, the
desktop Engineering Lab and the Prometheus `engineering_lab` tool all go through this registry, so a result is always
produced by the same code path and can be re-run.
"""
import math
from typing import Any, Callable, Dict, Tuple

import numpy as np

from . import EngError, MODEL_VERSION
from . import arm_dynamics, atmosphere, compressible, control, machine, optimize, propulsion, structures, trajectory, uncertainty


def _clean(v: Any) -> Any:
    """numpy -> plain Python, non-finite floats -> strings, recursively (so results are valid JSON)."""
    if isinstance(v, dict):
        return {str(k): _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if isinstance(v, np.ndarray):
        return [_clean(x) for x in v.tolist()]
    if isinstance(v, (np.floating,)):
        v = float(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, complex):
        return {"re": v.real, "im": v.imag}
    if isinstance(v, float) and not math.isfinite(v):
        return "inf" if v > 0 else ("-inf" if v < 0 else "nan")
    return v


def _decimate(xs, ys, n: int = 400):
    if len(xs) <= n:
        return list(map(float, xs)), list(map(float, ys))
    idx = np.linspace(0, len(xs) - 1, n).astype(int)
    return [float(xs[i]) for i in idx], [float(ys[i]) for i in idx]


# ------------------------------------------------------------------------------ wrappers that need translation
def _trajectory(**p) -> dict:
    vkeys = ("mass_initial_kg", "propellant_kg", "thrust_vac_N", "isp_vac_s", "exit_area_m2", "ref_area_m2", "cd0", "cd0_mach", "k_induced", "cl")
    pkeys = ("kind", "kick_time_s", "kick_angle_deg", "gamma0_deg", "V0_m_s", "alpha_deg")
    veh = trajectory.Vehicle(**{k: p[k] for k in vkeys if k in p})
    prog = trajectory.Programme(**{("kind" if k == "kind" else k): p[k] for k in pkeys if k in p})
    sim = trajectory.simulate(veh, prog, dt=p.get("dt", 0.05), t_max=p.get("t_max", 2000.0), flat=bool(p.get("flat", False)),
                              aero=bool(p.get("aero", True)))
    d = sim["data"]
    series = {}
    for key, label, unit in (("h", "altitude", "m"), ("V", "speed", "m/s"), ("accel", "tangential acceleration", "m/s^2"), ("q", "dynamic pressure", "Pa"),
                             ("mach", "Mach number", "-")):
        x, y = _decimate(d["t"], d[key])
        series[key] = {"x": x, "y": y, "xlabel": "time [s]", "ylabel": f"{label} [{unit}]"}
    x, y = _decimate(d["t"], np.degrees(d["gamma"]))
    series["gamma"] = {"x": x, "y": y, "xlabel": "time [s]", "ylabel": "flight-path angle [deg]"}
    x, y = _decimate(d["x"] / 1000, d["h"] / 1000)
    series["profile"] = {"x": x, "y": y, "xlabel": "downrange [km]", "ylabel": "altitude [km]"}
    return {"results": sim["summary"], "assumptions": sim["assumptions"], "series": series,
            "formula": "planar 3-DOF point mass, RK4; dV/dt = (T cos a - D)/m - g sin g; dgamma/dt = (T sin a + L)/(mV) - (g/V - V/r) cos g"}


def _trajectory_convergence(**p) -> dict:
    dts = p.pop("dts", (0.4, 0.2, 0.1, 0.05))
    quantity = p.pop("quantity", "apogee_m")
    vkeys = ("mass_initial_kg", "propellant_kg", "thrust_vac_N", "isp_vac_s", "exit_area_m2", "ref_area_m2", "cd0", "k_induced", "cl")
    veh = trajectory.Vehicle(**{k: p[k] for k in vkeys if k in p})
    prog = trajectory.Programme(**{k: p[k] for k in ("kind", "kick_time_s", "kick_angle_deg", "gamma0_deg", "V0_m_s", "alpha_deg") if k in p})
    c = trajectory.convergence(veh, prog, dts, quantity, flat=bool(p.get("flat", False)), aero=bool(p.get("aero", True)))
    diffs = c["differences"]
    return {"results": c, "series": {"convergence": {"x": c["dt"][1:], "y": diffs, "xlabel": "time step dt [s]",
                                                     "ylabel": f"|{quantity}(dt) - {quantity}(2dt)| [m]", "log": True}},
            "assumptions": ["successive halving; observed order = log2 of the ratio of successive differences"]}


def _control(**p) -> dict:
    plant = control.Plant(**{k: p[k] for k in ("kind", "inertia", "u_max", "rate_limit") if k in p and not k.startswith("c_")})
    ck = {k[2:]: p[k] for k in p if k.startswith("c_")}
    ctrl = control.Controller(**ck)
    sc = control.Scenario(**{k: p[k] for k in ("reference", "duration", "noise_std", "rate_noise_std", "delay_samples", "disturbance",
                                                "disturbance_time", "seed") if k in p})
    r = control.simulate(plant, ctrl, sc)
    x, y = _decimate(r["t"], r["y"])
    _, u = _decimate(r["t"], r["u"])
    _, e = _decimate(r["t"], r["error"])
    unit = "rad" if plant.kind == "attitude" else "m"
    uunit = "N m" if plant.kind == "attitude" else "N"
    st = r["stability"]
    return {"results": {"metrics": r["metrics"], "discrete_stable": st["discrete_stable"], "spectral_radius": st["spectral_radius"],
                        "routh_hurwitz": st.get("routh_hurwitz_continuous")},
            "series": {"response": {"x": x, "y": y, "ref": [sc.reference] * len(x), "xlabel": "time [s]", "ylabel": f"output [{unit}]"},
                       "control": {"x": x, "y": u, "xlabel": "time [s]", "ylabel": f"actuator command [{uunit}]"},
                       "error": {"x": x, "y": e, "xlabel": "time [s]", "ylabel": f"error [{unit}]"}},
            "assumptions": r["assumptions"]}


def _arm_trajectory(**p) -> dict:
    model = arm_dynamics.ArmModel().with_payload(float(p.get("payload_kg", 0.0)))
    tr = arm_dynamics.plan(p["q_start_deg"], p["q_end_deg"], p.get("kind", "trapezoid"), p.get("duration"), p.get("max_speed_dps", 60.0),
                           p.get("accel_fraction", 0.25), p.get("dt", 0.01))
    servo = p.get("servos") or {j: p.get("servo", "MG996R") for j in arm_dynamics.JOINTS}
    ev = arm_dynamics.evaluate(model, tr, servo)
    series = {}
    for j, name in enumerate(arm_dynamics.JOINTS):
        x, y = _decimate(tr.t, ev["tau"][:, j])
        series[f"torque_{name}"] = {"x": x, "y": y, "xlabel": "time [s]", "ylabel": f"{name} torque [N m]"}
        x, y = _decimate(tr.t, tr.qd[:, j])
        series[f"speed_{name}"] = {"x": x, "y": y, "xlabel": "time [s]", "ylabel": f"{name} speed [rad/s]"}
    res = {k: v for k, v in ev.items() if k != "tau"}
    return {"results": res, "series": series, "assumptions": ev["assumptions"],
            "formula": "recursive Newton-Euler: tau = M(q) q'' + C(q,q') q' + G(q) + tau_f"}


def _cantilever_opt(**p) -> dict:
    r = optimize.cantilever_section(**p)
    c = r["candidates"]
    front = r["pareto_front"]
    return {"results": {k: v for k, v in r.items() if k != "candidates"}, "candidates": c,
            "series": {"mass_vs_sf": {"x": [x["mass_kg"] for x in c], "y": [x["safety_factor"] for x in c], "style": "points",
                                      "front_x": [x["mass_kg"] for x in front], "front_y": [x["safety_factor"] for x in front],
                                      "xlabel": "mass [kg]", "ylabel": "safety factor against yield [-]"},
                       "mass_vs_deflection": {"x": [x["mass_kg"] for x in c], "y": [x["tip_deflection_m"] * 1000 for x in c], "style": "points",
                                              "xlabel": "mass [kg]", "ylabel": "tip deflection [mm]"}},
            "assumptions": r["assumptions"]}


def _mach_sweep(**p) -> dict:
    g = float(p.get("gamma", 1.4))
    Ms = np.linspace(1.01, float(p.get("M_max", 5.0)), 120)
    ns = [compressible.normal_shock(m, g)["results"] for m in Ms]
    return {"results": {"gamma": g, "points": len(Ms)},
            "series": {"p_ratio": {"x": list(Ms), "y": [n["p2_over_p1"] for n in ns], "xlabel": "upstream Mach M1 [-]", "ylabel": "p2/p1 [-]"},
                       "M2": {"x": list(Ms), "y": [n["M2"] for n in ns], "xlabel": "upstream Mach M1 [-]", "ylabel": "downstream Mach M2 [-]"},
                       "p0_loss": {"x": list(Ms), "y": [n["p02_over_p01"] for n in ns], "xlabel": "upstream Mach M1 [-]", "ylabel": "p02/p01 [-]"}},
            "assumptions": compressible.ASSUME}


def _nozzle_sweep(**p) -> dict:
    base = {k: p[k] for k in ("pc", "Tc", "gamma", "molar_mass", "throat_area", "pa") if k in p}
    eps = np.geomspace(2, float(p.get("eps_max", 100)), 60)
    rs = [propulsion.nozzle(**base, expansion_ratio=float(e))["results"] for e in eps]
    return {"results": {"base": base},
            "series": {"isp_sl": {"x": list(eps), "y": [r["isp_sea_level_s"] for r in rs], "xlabel": "expansion ratio Ae/At [-]", "ylabel": "Isp [s]"},
                       "isp_vac": {"x": list(eps), "y": [r["isp_vacuum_s"] for r in rs], "xlabel": "expansion ratio Ae/At [-]", "ylabel": "Isp [s]"}},
            "assumptions": ["ideal rocket"]}


def _gum(**p) -> dict:
    """Uncertainty of a registered closed-form quantity: 'cantilever_tip_deflection' = P L^3 / (3 E I)."""
    expr = p.get("expression", "cantilever_tip_deflection")
    funcs = {"cantilever_tip_deflection": lambda P, L, E, I: P * L ** 3 / (3 * E * I),
             "bending_stress": lambda M, c, I: M * c / I,
             "dynamic_pressure": lambda rho, V: 0.5 * rho * V * V}
    if expr not in funcs:
        raise EngError(f"expression must be one of {', '.join(funcs)}")
    x, u = p["values"], p.get("uncertainties", {})
    lin = uncertainty.propagate_linear(funcs[expr], x, u)
    mc = uncertainty.monte_carlo(funcs[expr], x, u, n=int(p.get("samples", 20000)), seed=int(p.get("seed", 0)))
    return {"results": {"linear": lin, "monte_carlo": mc}, "assumptions": ["uncorrelated inputs", "normal input distributions (Monte Carlo)"]}


MODELS: Dict[str, Tuple[Callable[..., dict], str, str]] = {
    "truss_stiffness": (structures.truss_stiffness, "structures", "2-D truss by direct stiffness (indeterminate OK): nodes, members, supports, loads, E, A"),
    "frame": (structures.frame, "structures", "2-D rigid frame / continuous beam by direct stiffness: nodes, members (E, A, I, w, c), supports, loads [Fx,Fy,M]"),
    "kt_elliptical_hole": (machine.kt_elliptical_hole, "machine", "Kt of an elliptical hole (Inglis): a, b"),
    "fatigue_kf": (machine.fatigue_kf, "machine", "notch sensitivity q and fatigue factor Kf: Kt, r, Sut, loading"),
    "marin": (machine.marin, "machine", "corrected endurance limit Se: Sut, surface, d, loading, temperature_C, reliability"),
    "fatigue": (machine.fatigue, "machine", "Goodman/Soderberg/Gerber/yield factors and life: sigma_a, sigma_m, Se, Sut, Sy"),
    "finite_life": (machine.finite_life, "machine", "cycles to failure (Basquin): sigma_rev, Se, Sut"),
    "shaft": (machine.shaft, "machine", "DE-Goodman shaft sizing/check: Ma, Mm, Ta, Tm, Sut, Sy, n, Kf, Kfs, d?"),
    "bolted_joint": (machine.bolted_joint, "machine", "bolted tension joint: d, pitch, grip, load_per_bolt, property_class"),
    "cantilever_optimisation": (_cantilever_opt, "design", "mass vs safety factor sweep with Pareto front: length, load, material, shape, sizes"),
    "truss_sizing": (optimize.truss_sizing, "design", "truss member-area sweep: nodes, members, supports, loads, areas, material"),
    "standard_atmosphere_1976": (atmosphere.standard_atmosphere_1976, "aerospace", "U.S. Standard Atmosphere 1976, 0-86 km: altitude_m"),
    "isentropic": (compressible.isentropic, "aerospace", "isentropic ratios: M, gamma"),
    "normal_shock": (compressible.normal_shock, "aerospace", "normal shock: M1, gamma"),
    "oblique_shock": (compressible.oblique_shock, "aerospace", "oblique shock: M1, theta_deg, strong, gamma"),
    "expansion_fan": (compressible.expansion_fan, "aerospace", "Prandtl-Meyer expansion: M1, turn_deg, gamma"),
    "mach_sweep": (_mach_sweep, "aerospace", "normal-shock properties against Mach (plots): M_max, gamma"),
    "nozzle": (propulsion.nozzle, "aerospace", "ideal rocket nozzle: pc, Tc, gamma, molar_mass, throat_area, expansion_ratio, pa"),
    "nozzle_sweep": (_nozzle_sweep, "aerospace", "Isp against expansion ratio (plots): pc, Tc, gamma, molar_mass, throat_area"),
    "trajectory": (_trajectory, "aerospace", "3-DOF point-mass RK4 trajectory: mass_initial_kg, propellant_kg, thrust_vac_N, isp_vac_s, ref_area_m2, cd0, kind, kick_time_s, kick_angle_deg, dt"),
    "trajectory_convergence": (_trajectory_convergence, "aerospace", "RK4 timestep refinement study (same parameters + dts)"),
    "control": (_control, "control", "closed-loop sandbox: kind, inertia, u_max, rate_limit, c_kind, c_Kp, c_Ki, c_Kd, c_Tf, c_Ts, reference, duration, noise_std, delay_samples, disturbance"),
    "arm_trajectory": (_arm_trajectory, "arm", "arm dynamic torques along a move: q_start_deg, q_end_deg, kind, duration, max_speed_dps, payload_kg, servo"),
    "uncertainty": (_gum, "method", "GUM + Monte Carlo for an expression: expression, values, uncertainties"),
}


_TRUSS = dict(nodes={"A": [0, 0], "B": [2, 0], "C": [4, 0], "D": [1, 1.5], "E": [3, 1.5]},
              members=[["A", "B"], ["B", "C"], ["A", "D"], ["D", "B"], ["B", "E"], ["E", "C"], ["D", "E"], ["A", "E"]],
              supports={"A": "pin", "C": "pin"}, loads={"D": [0, -10000], "E": [2000, -5000]}, E=200e9, A=5e-4)
EXAMPLES: Dict[str, dict] = {        # a valid, meaningful starting input for every model (used by the desktop lab and tests)
    "truss_stiffness": _TRUSS,
    "frame": dict(nodes={"A": [0, 0], "B": [0, 3], "C": [4, 3], "D": [4, 0]},
                  members=[{"nodes": ["A", "B"]}, {"nodes": ["B", "C"], "w": -5000, "c": 0.1}, {"nodes": ["C", "D"]}],
                  supports={"A": "fixed", "D": "fixed"}, loads={"B": [2000, 0, 0]}, E=200e9, A=5e-3, I=8e-5),
    "kt_elliptical_hole": dict(a=0.004, b=0.002),
    "fatigue_kf": dict(Kt=2.1, r=0.002, Sut=690e6, loading="bending"),
    "marin": dict(Sut=690e6, surface="machined", d=0.025, loading="bending", reliability=99),
    "fatigue": dict(sigma_a=120e6, sigma_m=80e6, Se=210e6, Sut=690e6, Sy=490e6),
    "finite_life": dict(sigma_rev=300e6, Se=245e6, Sut=490e6),
    "shaft": dict(Ma=70, Mm=0, Ta=0, Tm=45, Sut=700e6, Sy=560e6, n=1.5, Kf=1.58, Kfs=1.39),
    "bolted_joint": dict(d=0.012, pitch=0.00175, grip=0.03, load_per_bolt=5000, property_class="8.8"),
    "cantilever_optimisation": dict(length=0.5, load=200, material="aluminium_6061_t6", shape="rectangle", min_safety_factor=3, max_deflection=0.002),
    "truss_sizing": dict(nodes={"A": [0, 0], "B": [1, 1], "C": [2, 0]}, members=[["A", "B"], ["B", "C"], ["A", "C"]],
                         supports={"A": "pin", "C": "roller"}, loads={"B": [0, -5000]}, areas=[2e-5, 5e-5, 1e-4, 2e-4, 4e-4], material="steel_s275"),
    "standard_atmosphere_1976": dict(altitude_m=30000),
    "isentropic": dict(M=2.0), "normal_shock": dict(M1=2.0), "oblique_shock": dict(M1=2.0, theta_deg=10.0), "expansion_fan": dict(M1=2.0, turn_deg=10.0),
    "mach_sweep": dict(M_max=5.0),
    "nozzle": dict(pc=7e6, Tc=3300, gamma=1.2, molar_mass=0.022, throat_area=1e-3, expansion_ratio=20),
    "nozzle_sweep": dict(pc=7e6, Tc=3300, gamma=1.2, molar_mass=0.022, throat_area=1e-3, eps_max=150),
    "trajectory": dict(mass_initial_kg=50, propellant_kg=25, thrust_vac_N=4000, isp_vac_s=220, exit_area_m2=0.0, ref_area_m2=0.0177, cd0=0.45,
                       kind="gravity_turn", kick_time_s=3, kick_angle_deg=4, dt=0.05),
    "trajectory_convergence": dict(mass_initial_kg=50, propellant_kg=25, thrust_vac_N=4000, isp_vac_s=220, kick_time_s=3, kick_angle_deg=4,
                                   dts=[0.4, 0.2, 0.1, 0.05], flat=True, aero=False),
    "control": dict(kind="attitude", inertia=0.05, u_max=0.5, rate_limit=10.0, c_kind="pid", c_Kp=0.8, c_Ki=0.4, c_Kd=0.15, c_Tf=0.01, c_Ts=0.01,
                    reference=0.2, duration=8, noise_std=0.001, delay_samples=1, disturbance=0.02, disturbance_time=5.0),
    "arm_trajectory": dict(q_start_deg=[0, 30, -30, 0], q_end_deg=[0, 100, -60, 0], kind="cubic", duration=0.5, payload_kg=0.05, servo="MG996R"),
    "uncertainty": dict(expression="cantilever_tip_deflection", values={"P": 100, "L": 0.5, "E": 69e9, "I": 2e-9},
                        uncertainties={"P": 2, "L": 0.001, "E": 2e9, "I": 1e-10}, samples=20000),
}


def catalog() -> str:
    return "\n".join(f"- {n} [{cat}]: {doc}" for n, (_, cat, doc) in sorted(MODELS.items()))


def run(name: str, **params) -> dict:
    entry = MODELS.get(str(name))
    if entry is None:
        return {"status": "error", "message": f"unknown model '{name}'. Available:\n{catalog()}"}
    try:
        out = entry[0](**params)
    except EngError as e:
        return {"status": "error", "model": name, "message": str(e)}
    except (TypeError, KeyError) as e:
        return {"status": "error", "model": name, "message": f"wrong or missing parameters ({e}). Usage: {entry[2]}"}
    except (ValueError, ZeroDivisionError, OverflowError, np.linalg.LinAlgError) as e:
        return {"status": "error", "model": name, "message": f"numerical problem: {e}"}
    out = _clean(out)
    out.update({"status": "success", "model": name, "category": entry[1], "model_version": MODEL_VERSION, "inputs": _clean(params)})
    out.setdefault("warnings", [])
    return out
