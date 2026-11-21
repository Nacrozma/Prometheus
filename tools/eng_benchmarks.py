#!/usr/bin/env python3
"""Reproducible engineering benchmark plots and numbers for docs/VALIDATION.md.

    python tools/eng_benchmarks.py [outdir]          (default docs/validation)

Every plot comes from the eng models with fixed inputs listed in benchmarks.json. No physical measurement exists
yet: there is deliberately NO "simulated vs measured" plot until real measurements are entered (eng.arm_benchmark).
"""
import json
import math
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import arm_sim  # noqa: E402
from eng import MODEL_VERSION, arm_dynamics as D, atmosphere as A, compressible as C, control as K, gesture_lab as GL  # noqa: E402
from eng import optimize as O, propulsion as P, structures as S, trajectory as T  # noqa: E402
from eng.plots import line_plot  # noqa: E402

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs", "validation"))
os.makedirs(OUT, exist_ok=True)
numbers = {"model_version": MODEL_VERSION, "note": "all values are model outputs (software); none is a physical measurement"}


def save(name, svg):
    with open(os.path.join(OUT, name + ".svg"), "w", encoding="utf-8") as f:
        f.write(svg)
    print("wrote", name)


# 1. arm: dynamic vs static shoulder torque along a fast move
m = D.ArmModel().with_payload(0.05)
tr = D.plan((0, 30, -30, 0), (0, 100, -60, 0), "cubic", duration=0.5, dt=0.002)
ev = D.evaluate(m, tr, {j: "MG996R" for j in D.JOINTS})
static = [arm_sim.static_torques(np.degrees(q), 0.05)["shoulder"] for q in tr.q]
save("arm_torque_vs_time", line_plot([{"x": list(tr.t), "y": list(np.abs(ev["tau"][:, 1])), "label": "dynamic |tau| (RNEA)"},
                                      {"x": list(tr.t), "y": static, "label": "static holding torque", "style": "dashed"},
                                      {"x": list(tr.t), "y": [0.5 * D.SERVO_MODELS["MG996R"].stall_torque_Nm] * len(tr.t), "label": "MG996R assumed continuous (50% stall)", "style": "dashed"}],
                                     "Shoulder torque, 0.5 s cubic move, 50 g payload (provisional arm parameters)", "time [s]", "torque [N m]"))
numbers["arm_fast_move"] = {"peak_dynamic_Nm": ev["joints"]["shoulder"]["peak_torque_Nm"], "peak_static_Nm": max(static), "feasible": ev["feasible"], "flags": ev["flags"]}

# 2. design sweep
opt = O.cantilever_section(0.5, 200, "aluminium_6061_t6", "rectangle", min_safety_factor=3, max_deflection=0.002)
c = opt["candidates"]
feas = [x for x in c if x["feasible"]]
inf = [x for x in c if not x["feasible"]]
fr = opt["pareto_front"]
save("design_mass_vs_safety_factor", line_plot([{"x": [x["mass_kg"] for x in inf], "y": [x["safety_factor"] for x in inf], "label": "violates a constraint", "style": "points", "color": "#9aa4b8"},
                                                {"x": [x["mass_kg"] for x in feas], "y": [x["safety_factor"] for x in feas], "label": "feasible", "style": "points"},
                                                {"x": [x["mass_kg"] for x in fr], "y": [x["safety_factor"] for x in fr], "label": "Pareto front"}],
                                               "Cantilever 0.5 m, 200 N tip load, 6061-T6 rectangles", "mass [kg]", "safety factor against yield [-]"))
save("design_mass_vs_deflection", line_plot([{"x": [x["mass_kg"] for x in c], "y": [x["tip_deflection_m"] * 1000 for x in c], "label": "candidates", "style": "points"},
                                             {"x": [0, max(x["mass_kg"] for x in c)], "y": [2, 2], "label": "limit 2 mm", "style": "dashed"}],
                                            "Cantilever design sweep: deflection", "mass [kg]", "tip deflection [mm]", log_y=True))
numbers["design_best"] = opt["best"]

# 3. structure: frame elements vs analytic cantilever deflection curve
L, Pp, E, I = 2.0, 1000.0, 200e9, 8e-6
n = 8
nodes = {f"N{i}": [L * i / n, 0] for i in range(n + 1)}
sol = S.frame(nodes, [[f"N{i}", f"N{i + 1}"] for i in range(n)], {"N0": "fixed"}, {f"N{n}": [0, -Pp, 0]}, E=E, A=1e-3, I=I)["results"]
xs = np.linspace(0, L, 100)
w = -Pp * xs ** 2 * (3 * L - xs) / (6 * E * I)
fx = [L * i / n for i in range(n + 1)]
fy = [sol["displacements"][f"N{i}"]["uy_m"] for i in range(n + 1)]
save("structure_cantilever_deflection", line_plot([{"x": list(xs), "y": list(w * 1000), "label": "analytic P x^2 (3L - x) / 6EI"},
                                                   {"x": fx, "y": [v * 1000 for v in fy], "label": "direct stiffness, 8 frame elements", "style": "points"}],
                                                  "Cantilever deflection: stiffness method vs closed form", "x [m]", "deflection [mm]"))
numbers["frame_max_nodal_error_m"] = max(abs(fy[i] - (-Pp * fx[i] ** 2 * (3 * L - fx[i]) / (6 * E * I))) for i in range(n + 1))

# 4. RK4 convergence
veh = T.Vehicle(50.0, propellant_kg=25, thrust_vac_N=4000, isp_vac_s=220)
prog = T.Programme("gravity_turn", kick_time_s=3, kick_angle_deg=4)
dts = (0.4, 0.2, 0.1, 0.05, 0.025)
cv = T.convergence(veh, prog, dts, flat=True, aero=False)
veh_air = T.Vehicle(50.0, propellant_kg=25, thrust_vac_N=4000, isp_vac_s=220, ref_area_m2=0.0177, cd0=0.45)
cva = T.convergence(veh_air, prog, dts)
ref = [cv["differences"][0] * (d / dts[1]) ** 4 for d in dts[1:]]
save("rk4_convergence", line_plot([{"x": list(dts[1:]), "y": cv["differences"], "label": "vacuum, flat Earth", "style": "points"},
                                   {"x": list(dts[1:]), "y": cva["differences"], "label": "with 1976 atmosphere + drag", "style": "points"},
                                   {"x": list(dts[1:]), "y": ref, "label": "slope 4 reference", "style": "dashed"}],
                                  "RK4 timestep refinement: change in apogee", "time step dt [s]", "|apogee(dt) - apogee(2dt)| [m]", log_x=True, log_y=True))
numbers["rk4_convergence"] = {"vacuum": cv, "atmosphere": cva}

# 5. trajectory
sim = T.simulate(veh_air, prog, dt=0.05)
d = sim["data"]
save("trajectory_profile", line_plot([{"x": list(d["x"] / 1000), "y": list(d["h"] / 1000), "label": "trajectory"}],
                                     "Sounding rocket (50 kg, 4 kN, gravity turn), 1976 atmosphere", "downrange [km]", "altitude [km]"))
save("trajectory_time", line_plot([{"x": list(d["t"]), "y": list(d["h"] / 1000), "label": "altitude [km]"},
                                   {"x": list(d["t"]), "y": list(d["V"] / 100), "label": "speed [100 m/s]"},
                                   {"x": list(d["t"]), "y": list(d["q"] / 1e5), "label": "dynamic pressure [bar]"}],
                                  "Trajectory against time", "time [s]", "value (see legend units)"))
numbers["trajectory"] = sim["summary"]

# 6. atmosphere
hs = np.linspace(0, 86000, 300)
st = [A.state(h) for h in hs]
save("atmosphere_temperature", line_plot([{"x": [s["temperature_K"] for s in st], "y": list(hs / 1000), "label": "T (1976 standard)"}],
                                         "U.S. Standard Atmosphere 1976", "temperature [K]", "altitude [km]"))

# 7. shocks
Ms = np.linspace(1.01, 5, 150)
nsh = [C.normal_shock(x)["results"] for x in Ms]
save("normal_shock_vs_mach", line_plot([{"x": list(Ms), "y": [r["p2_over_p1"] for r in nsh], "label": "p2/p1"},
                                        {"x": list(Ms), "y": [r["T2_over_T1"] for r in nsh], "label": "T2/T1"},
                                        {"x": list(Ms), "y": [r["rho2_over_rho1"] for r in nsh], "label": "rho2/rho1"},
                                        {"x": list(Ms), "y": [10 * r["p02_over_p01"] for r in nsh], "label": "10 x p02/p01"}],
                                       "Normal shock ratios, gamma = 1.4", "upstream Mach M1 [-]", "ratio [-]"))
thetas = np.linspace(0.5, C.max_deflection(3.0)["theta_max_deg"] - 0.05, 60)
save("oblique_theta_beta", line_plot([{"x": list(thetas), "y": [C.oblique_shock(3.0, t)["results"]["beta_deg"] for t in thetas], "label": "weak, M1 = 3"},
                                      {"x": list(thetas), "y": [C.oblique_shock(3.0, t, strong=True)["results"]["beta_deg"] for t in thetas], "label": "strong, M1 = 3"}],
                                     "Oblique shock angle against deflection", "deflection theta [deg]", "shock angle beta [deg]"))

# 8. nozzle
base = dict(pc=7e6, Tc=3300.0, gamma=1.2, molar_mass=0.022, throat_area=1e-3)
eps = np.geomspace(2, 150, 80)
rs = [P.nozzle(**base, expansion_ratio=float(e))["results"] for e in eps]
save("nozzle_isp_vs_expansion", line_plot([{"x": list(eps), "y": [r["isp_vacuum_s"] for r in rs], "label": "vacuum"},
                                           {"x": list(eps), "y": [r["isp_sea_level_s"] for r in rs], "label": "sea level (ideal; separation not modelled)"}],
                                          "Ideal nozzle: Isp against expansion ratio (pc 7 MPa, Tc 3300 K, gamma 1.2, M 22 g/mol)", "expansion ratio Ae/At [-]", "specific impulse [s]", log_x=True))
numbers["nozzle_eps20"] = P.nozzle(**base, expansion_ratio=20.0)["results"]

# 9. control
plant = K.Plant("attitude", 0.05, u_max=0.5, rate_limit=10.0)
pid = K.simulate(plant, K.Controller("pid", Kp=0.8, Ki=0.4, Kd=0.15, Tf=0.01, Ts=0.01), K.Scenario(0.2, 8, noise_std=0.001, delay_samples=1, disturbance=0.02, disturbance_time=5.0))
g = K.place(0.05, 6.0, 0.8)
sfb = K.simulate(plant, K.Controller("state", Kp=g["Kp"], Kd=g["Kd"], Ki=0.0, Ts=0.01), K.Scenario(0.2, 8, noise_std=0.001, rate_noise_std=0.005, delay_samples=1, disturbance=0.02, disturbance_time=5.0))
save("control_response", line_plot([{"x": list(pid["t"]), "y": list(pid["y"]), "label": "PID"},
                                    {"x": list(sfb["t"]), "y": list(sfb["y"]), "label": "state feedback (wn 6, zeta 0.8)"},
                                    {"x": list(pid["t"]), "y": list(pid["reference"]), "label": "reference", "style": "dashed"}],
                                   "Attitude step 0.2 rad, noise, 1-sample delay, 0.02 N m disturbance at 5 s", "time [s]", "angle [rad]"))
numbers["control"] = {"pid": pid["metrics"], "state_feedback": sfb["metrics"]}

# 10. gesture filter trade-off (synthetic perturbation)
rows = GL.tuning_sweep(alphas=(0.1, 0.15, 0.25, 0.35, 0.5, 0.7, 0.9), deadbands=(0.0,))
save("gesture_jitter_vs_lag", line_plot([{"x": [r["lag_frames"] for r in rows], "y": [r["jitter_mm"] for r in rows], "label": "EMA alpha 0.1 ... 0.9", "style": "points"}],
                                        "Gesture filter: noise leak vs lag (SYNTHETIC landmarks, noise 0.005)", "lag to 90% of a step [frames at 30 fps]", "command jitter [mm]"))
numbers["gesture_suite"] = GL.standard_suite()
numbers["gesture_deadband"] = GL.tuning_sweep(alphas=(0.35,), deadbands=(0.0, 0.002, 0.004, 0.008))

with open(os.path.join(OUT, "benchmarks.json"), "w", encoding="utf-8") as f:
    json.dump(numbers, f, indent=2, default=lambda o: o if isinstance(o, (int, float, str)) else str(o))
print("wrote benchmarks.json")
