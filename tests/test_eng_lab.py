"""Uncertainty, experiment records, data logging, reports, plots and the model registry."""
import json
import math
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from eng import EngError, experiments as X, plots, registry as R, report as P, uncertainty as U  # noqa: E402

TRAJ = dict(mass_initial_kg=50, propellant_kg=25, thrust_vac_N=4000, isp_vac_s=220, ref_area_m2=0.0177, cd0=0.45, kick_time_s=3, kick_angle_deg=4)


class Uncertainty(unittest.TestCase):
    def test_measurement_summary(self):
        r = U.measurement_summary([10.01, 10.03, 9.99, 10.02, 10.00], resolution=0.01)
        self.assertAlmostEqual(r["mean"], 10.01, places=12)
        s = math.sqrt(sum((x - 10.01) ** 2 for x in [10.01, 10.03, 9.99, 10.02, 10.00]) / 4)
        self.assertAlmostEqual(r["u_typeA"], s / math.sqrt(5), places=12)
        self.assertAlmostEqual(r["u_typeB"], 0.01 / math.sqrt(12), places=12)
        self.assertAlmostEqual(r["u_combined"], math.hypot(r["u_typeA"], r["u_typeB"]), places=12)
        self.assertGreater(r["coverage_factor_k95"], 1.96)
        self.assertTrue(any("Type B" in w for w in U.measurement_summary([1.0, 1.1, 0.9])["warnings"]))

    def test_t_quantiles(self):
        self.assertAlmostEqual(U.t95(4), 2.776, places=3)
        self.assertAlmostEqual(U.t95(math.inf), 1.960)
        self.assertTrue(2.228 > U.t95(11) > 2.179)

    def test_linear_and_monte_carlo_agree_for_a_near_linear_model(self):
        f = lambda P, L, E, I: P * L ** 3 / (3 * E * I)
        x = {"P": 100.0, "L": 0.5, "E": 69e9, "I": 2e-9}
        u = {"P": 1.0, "L": 0.0005, "E": 0.5e9, "I": 0.01e-9}
        lin = U.propagate_linear(f, x, u)
        rel = math.sqrt((1 / 100) ** 2 + (3 * 0.0005 / 0.5) ** 2 + (0.5 / 69) ** 2 + (0.01 / 2) ** 2)
        self.assertAlmostEqual(lin["relative_u_y"], rel, places=6)                 # analytic for a power law
        self.assertAlmostEqual(lin["normalised_sensitivity"]["L"], 3.0, places=5)
        mc = U.monte_carlo(f, x, u, n=40000, seed=3)
        self.assertAlmostEqual(mc["std"] / lin["u_y"], 1.0, delta=0.03)
        self.assertAlmostEqual(sum(lin["contribution_pct"].values()), 100.0, places=9)

    def test_monte_carlo_reveals_nonlinearity(self):
        f = lambda x: x * x
        mc = U.monte_carlo(f, {"x": 0.0}, {"x": 1.0}, n=20000, seed=1)
        lin = U.propagate_linear(f, {"x": 0.0}, {"x": 1.0})
        self.assertEqual(lin["u_y"], 0.0)                                          # first order sees nothing at x = 0
        self.assertAlmostEqual(mc["mean"], 1.0, delta=0.05)                        # E[x^2] = 1

    def test_bad_inputs(self):
        with self.assertRaises(EngError):
            U.propagate_linear(lambda a: a, {"a": 1.0}, {"b": 0.1})
        with self.assertRaises(EngError):
            U.measurement_summary([])


class Experiments(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = X.ExperimentStore(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_run_record_and_reproduce(self):
        rec = self.store.run("trajectory", TRAJ, title="baseline", objective="apogee of the baseline vehicle")
        self.assertEqual(rec["kind"], "simulation")
        self.assertEqual(rec["validation_status"], "simulation tested")
        self.assertEqual(len(rec["input_hash"]), 64)
        self.assertIn("eng_model_version", rec["software"])
        again = self.store.rerun(rec["id"])
        self.assertTrue(again["reproduced"])
        self.assertTrue(again["input_hash_matches"])
        self.assertEqual(self.store.list()[0]["id"], rec["id"])

    def test_hardware_tested_needs_hardware_and_data(self):
        rec = self.store.run("nozzle", dict(pc=7e6, Tc=3300, gamma=1.2, molar_mass=0.022, throat_area=1e-3, expansion_ratio=20), title="ideal")
        with self.assertRaises(EngError):
            self.store.set_status(rec["id"], "hardware tested")
        hw = self.store.create("watchdog stop time", "hardware", validation_status="awaiting physical validation")
        with self.assertRaises(EngError):
            self.store.set_status(hw["id"], "hardware tested")                     # no data attached yet
        self.store.attach_table(hw["id"], "frames", [{"trial": 1, "stop_ms": 480.0}])
        self.assertEqual(self.store.set_status(hw["id"], "hardware tested", "video at 240 fps")["validation_status"], "hardware tested")

    def test_validation_and_ids(self):
        with self.assertRaises(EngError):
            self.store.create("x", "guess")
        with self.assertRaises(EngError):
            self.store.create("x", "simulation", validation_status="proven")
        with self.assertRaises(EngError):
            self.store.get("../etc/passwd")
        with self.assertRaises(EngError):
            self.store.attach_table(self.store.create("y", "analysis")["id"], "../bad", [{"a": 1}])

    def test_data_logger(self):
        t = [0.0]
        log = X.DataLogger({"port": "sim"}, {"L1": 0.12}, {"temperature_C": 21}, clock=lambda: t[0])
        log.log(cmd_deg=90.0, meas_deg=89.6)
        t[0] = 0.5
        log.log(cmd_deg=95.0, meas_deg=94.1)
        self.assertEqual([r["t_s"] for r in log.rows], [0.0, 0.5])
        header = log.to_csv().splitlines()[0].split(",")
        self.assertEqual(header, ["t_s", "wall_time", "cmd_deg", "meas_deg"])
        self.assertEqual(json.loads(log.to_json())["meta"]["calibration"]["L1"], 0.12)
        with self.assertRaises(EngError):
            log.log(x=float("nan"))


class Reports(unittest.TestCase):
    def test_reports_are_complete_and_honest(self):
        with tempfile.TemporaryDirectory() as d:
            st = X.ExperimentStore(d)
            rec = st.run("trajectory", TRAJ, title="baseline")
            md = P.markdown(rec)
            for needle in ("## Inputs", "## Assumptions", "## Results", "## Validation", "simulation tested", rec["input_hash"],
                           "No physical measurement supports this result", "not a certified engineering analysis"):
                self.assertIn(needle, md)
            files = P.write_all(rec, d, pdf=True)
            self.assertTrue(os.path.getsize(files["pdf"]) > 1000)
            with open(files["pdf"], "rb") as f:
                self.assertEqual(f.read(4), b"%PDF")
            self.assertIn("<svg", open(files["html"], encoding="utf-8").read())
            self.assertTrue(any(k.startswith("svg:") for k in files))

    def test_plots_are_deterministic_and_reject_empty_data(self):
        s = [{"x": [0, 1, 2], "y": [0, 1, 4], "label": "y = x^2"}]
        self.assertEqual(plots.line_plot(s, "t", "x [m]", "y [m]"), plots.line_plot(s, "t", "x [m]", "y [m]"))
        with self.assertRaises(EngError):
            plots.line_plot([{"x": [1], "y": [float("nan")]}])
        self.assertIn("<circle", plots.line_plot([{"x": [1, 10, 100], "y": [1, 2, 3], "style": "points"}], log_x=True))


class Registry(unittest.TestCase):
    def test_every_model_runs_with_a_reference_input_and_is_json(self):
        cases = {
            "truss_stiffness": dict(nodes={"A": [0, 0], "B": [1, 1], "C": [2, 0]}, members=[["A", "B"], ["B", "C"], ["A", "C"]],
                                    supports={"A": "pin", "C": "roller"}, loads={"B": [0, -1000]}),
            "frame": dict(nodes={"A": [0, 0], "B": [2, 0]}, members=[["A", "B"]], supports={"A": "fixed"}, loads={"B": [0, -1000, 0]}),
            "kt_elliptical_hole": dict(a=2, b=1), "fatigue_kf": dict(Kt=2, r=0.002, Sut=600e6), "marin": dict(Sut=600e6, d=0.02),
            "fatigue": dict(sigma_a=100e6, sigma_m=50e6, Se=200e6, Sut=600e6, Sy=400e6), "finite_life": dict(sigma_rev=300e6, Se=245e6, Sut=490e6),
            "shaft": dict(Ma=70, Mm=0, Ta=0, Tm=45, Sut=700e6, Sy=560e6), "bolted_joint": dict(d=0.01, pitch=0.0015, grip=0.02, load_per_bolt=3000),
            "cantilever_optimisation": dict(length=0.5, load=200),
            "truss_sizing": dict(nodes={"A": [0, 0], "B": [1, 1], "C": [2, 0]}, members=[["A", "B"], ["B", "C"], ["A", "C"]],
                                 supports={"A": "pin", "C": "roller"}, loads={"B": [0, -1000]}, areas=[1e-4, 2e-4]),
            "standard_atmosphere_1976": dict(altitude_m=30000), "isentropic": dict(M=2), "normal_shock": dict(M1=2),
            "oblique_shock": dict(M1=2, theta_deg=10), "expansion_fan": dict(M1=2, turn_deg=10), "mach_sweep": {},
            "nozzle": dict(pc=7e6, Tc=3300, gamma=1.2, molar_mass=0.022, throat_area=1e-3, expansion_ratio=20),
            "nozzle_sweep": dict(pc=7e6, Tc=3300, gamma=1.2, molar_mass=0.022, throat_area=1e-3), "trajectory": TRAJ,
            "trajectory_convergence": dict(TRAJ, dts=[0.2, 0.1, 0.05], flat=True, aero=False),
            "control": dict(kind="attitude", inertia=0.05, u_max=0.5, c_kind="pid", c_Kp=0.8, c_Ki=0.4, c_Kd=0.15, c_Ts=0.01, duration=4),
            "arm_trajectory": dict(q_start_deg=[0, 60, -60, 0], q_end_deg=[30, 90, -30, 0]),
            "uncertainty": dict(values={"rho": 1.225, "V": 50.0}, uncertainties={"rho": 0.01, "V": 0.5}, expression="dynamic_pressure", samples=2000),
        }
        self.assertEqual(set(cases), set(R.MODELS))
        for name, params in cases.items():
            r = R.run(name, **params)
            self.assertEqual(r["status"], "success", (name, r.get("message")))
            json.dumps(r, allow_nan=False)                                       # strictly valid JSON

    def test_errors_never_raise(self):
        self.assertEqual(R.run("nope")["status"], "error")
        self.assertEqual(R.run("normal_shock", M1=0.5)["status"], "error")
        self.assertIn("Usage", R.run("normal_shock", Mach=2)["message"])


if __name__ == "__main__":
    unittest.main()
