"""Arm dynamics, benchmark analysis and gesture stress tests (all software; no hardware involved)."""
import math
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import arm_bridge as br  # noqa: E402
import arm_sim  # noqa: E402
from eng import EngError, arm_benchmark as bm, arm_dynamics as D, gesture_lab as gl  # noqa: E402

ALL_MG = {j: "MG996R" for j in D.JOINTS}


class Dynamics(unittest.TestCase):
    def test_static_case_equals_the_existing_holding_torque_model(self):
        m = D.ArmModel()
        for q in [(0, 60, -60, 0), (35, 45, -90, 20), (-50, 120, -100, -30), (10, 10, 0, 0)]:
            for payload in (0.0, 0.05):
                tau = m.with_payload(payload).rnea(np.radians(q), np.zeros(4), np.zeros(4))
                st = arm_sim.static_torques(q, payload)
                for j, name in enumerate(("shoulder", "elbow", "wrist"), start=1):
                    self.assertAlmostEqual(abs(tau[j]), st[name], places=9, msg=(q, payload, name))
                self.assertAlmostEqual(tau[0], 0.0, places=12)          # gravity has no yaw component

    def test_single_link_matches_the_analytic_pendulum(self):
        # only the upper arm has mass: tau = I_pivot q'' + m g lc cos q (+ no velocity term about a fixed axis)
        masses = arm_sim.Masses(link1=0.2, link2=0.0, elbow_servo=0.0, wrist_servo=0.0, tool=0.0)
        m = D.ArmModel(masses=masses)
        L, mass = arm_sim.DEFAULT_ARM.L1, 0.2
        I_pivot = mass * L * L / 3
        for q1, qd1, qdd1 in [(0.3, 0.0, 0.0), (0.8, 1.5, -2.0), (1.4, -0.7, 4.0)]:
            tau = m.rnea([0.0, q1, 0.0, 0.0], [0.0, qd1, 0.0, 0.0], [0.0, qdd1, 0.0, 0.0])
            self.assertAlmostEqual(tau[1], I_pivot * qdd1 + mass * D.G * (L / 2) * math.cos(q1), places=10)

    def test_mass_matrix_is_symmetric_positive_definite(self):
        m = D.ArmModel().with_payload(0.03)
        rng = np.random.default_rng(3)
        for _ in range(20):
            q = np.radians([rng.uniform(-80, 80), rng.uniform(10, 170), rng.uniform(-140, 20), rng.uniform(-80, 80)])
            M = m.mass_matrix(q)
            self.assertTrue(np.allclose(M, M.T, atol=1e-12))
            self.assertGreater(np.linalg.eigvalsh(M).min(), 0.0)

    def test_decomposition_reassembles_rnea(self):
        m = D.ArmModel().with_payload(0.02)
        q, qd, qdd = np.radians([20, 70, -50, 10]), np.array([0.4, -0.3, 0.8, 0.2]), np.array([1.0, -2.0, 0.5, 3.0])
        parts = m.decompose(q, qd, qdd)
        self.assertTrue(np.allclose(parts["tau"], m.rnea(q, qd, qdd), atol=1e-12))

    def test_power_balance_along_a_trajectory(self):
        # sum(tau q') = d(KE + PE)/dt for a frictionless model: an independent check of the whole RNEA
        m = D.ArmModel().with_payload(0.04)
        tr = D.plan((-30, 40, -70, -20), (40, 110, -40, 30), "quintic", duration=1.2, dt=0.0005)
        E = np.array([sum(m.energy(tr.q[k], tr.qd[k])) for k in range(len(tr.t))])
        dE = np.gradient(E, tr.t)
        P = np.array([m.rnea(tr.q[k], tr.qd[k], tr.qdd[k]) @ tr.qd[k] for k in range(len(tr.t))])
        inner = slice(5, -5)
        self.assertLess(np.max(np.abs(dE[inner] - P[inner])), 1e-4 * max(1e-6, np.max(np.abs(P))) + 1e-6)

    def test_friction_adds_dissipation(self):
        f = D.Friction(viscous_Nms=(0.01,) * 4, coulomb_Nm=(0.02,) * 4)
        m0, m1 = D.ArmModel(), D.ArmModel(friction=f)
        q, qd = np.radians([0, 60, -60, 0]), np.array([0.5, 0.5, -0.5, 0.0])
        d = m1.rnea(q, qd, np.zeros(4)) - m0.rnea(q, qd, np.zeros(4))
        self.assertTrue(np.all(d[:3] * qd[:3] > 0))                   # friction opposes motion: positive power

    def test_inputs_are_validated(self):
        with self.assertRaises(EngError):
            D.ArmModel().rnea([0, 1, 2], [0] * 4, [0] * 4)
        with self.assertRaises(EngError):
            D.ArmModel().rnea([0, float("nan"), 0, 0], [0] * 4, [0] * 4)
        with self.assertRaises(EngError):
            D.Inertial(com_link1=1.5)


class Trajectories(unittest.TestCase):
    def test_profiles_hit_the_endpoints_with_zero_velocity(self):
        for kind in ("trapezoid", "cubic", "quintic"):
            tr = D.plan((0, 60, -60, 0), (30, 90, -30, 20), kind)
            self.assertTrue(np.allclose(np.degrees(tr.q[0]), (0, 60, -60, 0)))
            self.assertTrue(np.allclose(np.degrees(tr.q[-1]), (30, 90, -30, 20)))
            self.assertTrue(np.allclose(tr.qd[0], 0, atol=1e-9) and np.allclose(tr.qd[-1], 0, atol=1e-9), kind)

    def test_default_duration_respects_the_speed_limit(self):
        for kind in ("trapezoid", "cubic", "quintic"):
            tr = D.plan((0, 60, -60, 0), (60, 60, -60, 0), kind, max_speed_dps=40.0, dt=0.001)
            self.assertLessEqual(np.degrees(np.max(np.abs(tr.qd))), 40.0 * 1.0001, kind)

    def test_velocity_is_the_derivative_of_position(self):
        tr = D.plan((0, 60, -60, 0), (45, 100, -20, 30), "trapezoid", dt=0.0005)
        num = np.gradient(tr.q[:, 1], tr.t)
        self.assertLess(np.max(np.abs(num[3:-3] - tr.qd[3:-3, 1])), 1e-3)

    def test_out_of_limit_poses_and_collisions_are_refused(self):
        with self.assertRaises(EngError):
            D.plan((0, 60, -60, 0), (120, 60, -60, 0))
        with self.assertRaises(EngError):
            D.plan((0, 60, -60, 0), (0, 0, -60, -90))                 # tip through the table


class Feasibility(unittest.TestCase):
    def test_slow_moves_are_feasible_and_fast_heavy_ones_are_flagged(self):
        m = D.ArmModel()
        slow = D.evaluate(m, D.plan((0, 60, -60, 0), (30, 90, -30, 0), "quintic", max_speed_dps=30), ALL_MG)
        self.assertTrue(slow["feasible"], slow["flags"])
        weak = {j: "SG90" for j in D.JOINTS}
        heavy = D.evaluate(m.with_payload(0.25), D.plan((0, 10, 0, 0), (0, 80, -40, 0), "cubic", duration=0.25), weak)
        self.assertFalse(heavy["feasible"])
        self.assertTrue(any("shoulder" in f for f in heavy["flags"]))

    def test_torque_speed_line(self):
        s = D.SERVO_MODELS["MG996R"]
        self.assertAlmostEqual(s.available(0.0), s.stall_torque_Nm)
        self.assertAlmostEqual(s.available(s.no_load_speed_rad_s), 0.0)
        self.assertAlmostEqual(s.available(s.no_load_speed_rad_s / 2), s.stall_torque_Nm / 2)

    def test_dynamic_peak_exceeds_static_for_a_fast_move(self):
        m = D.ArmModel().with_payload(0.05)
        tr = D.plan((0, 30, -30, 0), (0, 100, -60, 0), "cubic", duration=0.4)
        dyn = D.evaluate(m, tr, ALL_MG)["joints"]["shoulder"]["peak_torque_Nm"]
        static = max(arm_sim.static_torques(np.degrees(q), 0.05)["shoulder"] for q in tr.q)
        self.assertGreater(dyn, static)


class Benchmark(unittest.TestCase):
    def test_plan_is_safe_deterministic_and_interleaved(self):
        a, b = bm.make_plan(seed=4), bm.make_plan(seed=4)
        self.assertEqual([t.cmd for t in a], [t.cmd for t in b])
        for t in a:
            res = arm_sim.inverse(*t.cmd)
            self.assertTrue(res.reachable)
            self.assertLess(math.dist(t.pred, t.cmd), 1e-3)
            self.assertGreaterEqual(t.cmd[2], 0.04)
        first_rep = [t.waypoint for t in a if t.repeat == 0 and t.payload_kg == 0.0]
        self.assertEqual(sorted(first_rep), list(range(8)))

    def test_analysis_refuses_an_unmeasured_sheet(self):
        with self.assertRaises(EngError):
            bm.analyse(bm.read_csv(bm.to_csv(bm.make_plan(n_points=2, repeats=2))))

    def test_analysis_statistics_on_a_clearly_synthetic_dataset(self):
        # SYNTHETIC numbers built inside the test to check the arithmetic; not a measurement of any arm.
        trials = bm.make_plan(n_points=2, payloads=(0.0, 0.05), repeats=3, seed=2)
        rows = bm.read_csv(bm.to_csv(trials))
        for r in rows:
            sag = 0.002 + 0.04 * float(r["payload_kg"])                      # 2 mm offset + 40 mm/kg
            jitter = 0.0005 * (int(r["repeat"]) - 1)
            r["meas_x_m"] = str(float(r["pred_x_m"]) + jitter)
            r["meas_y_m"] = r["pred_y_m"]
            r["meas_z_m"] = str(float(r["pred_z_m"]) - sag)
            r["meas_uncertainty_m"] = "0.0005"
        s = bm.analyse(rows)
        self.assertEqual(s["trials_measured"], len(rows))
        self.assertAlmostEqual(s["sag_vs_payload"]["slope_m_per_kg"], 0.04, places=9)
        self.assertAlmostEqual(s["sag_vs_payload"]["intercept_m"], 0.002, places=9)
        # repeatability of x offsets -0.5, 0, +0.5 mm: l = 0.5,0,0.5 -> mean 1/3 mm, std 0.2887 mm
        self.assertAlmostEqual(s["per_waypoint"][0]["repeatability_RP_m"], (1 / 3 + 3 * 0.2886751) * 1e-3, places=7)

    def test_execute_needs_a_person_for_every_move_and_never_arms(self):
        t = br.SimTransport()
        host = br.ArmBridge(t)
        trials = bm.make_plan(n_points=3, repeats=1, payloads=(0.0,))
        asked = []
        done = bm.execute(host, trials, lambda tr: asked.append(tr.trial_id) or len(asked) < 3, lambda s: t.advance(s))
        self.assertEqual(len(done), 2)                                     # the third confirmation said no
        self.assertEqual(t.firmware.state, br.STATE_ESTOP)                 # stopped at the end
        self.assertEqual(t.firmware.current[0], float(br.REST_DEG[0]))     # never armed: nothing moved


class GestureLab(unittest.TestCase):
    def test_the_suite_never_moves_while_the_hand_is_lost(self):
        suite = gl.standard_suite()
        for name, r in suite.items():
            self.assertEqual(r["moved_while_lost"], 0, name)
        self.assertEqual(suite["hand_lost"]["frames_to_stop_after_loss"], 15)   # hold_lost_frames, then stop
        self.assertGreater(suite["glitch_5pct"]["rejected_frames"], 0)
        self.assertGreater(suite["noise_0.008"]["jitter_mm"], suite["noise_0.003"]["jitter_mm"])

    def test_smoothing_trades_jitter_for_lag(self):
        rows = {r["alpha"]: r for r in gl.tuning_sweep(alphas=(0.15, 0.7), deadbands=(0.0,))}
        self.assertLess(rows[0.15]["jitter_mm"], rows[0.7]["jitter_mm"])
        self.assertGreater(rows[0.15]["lag_frames"], rows[0.7]["lag_frames"])

    def test_recordings_round_trip(self):
        import tempfile
        frames = gl.scenario("clean", 20)
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "r.jsonl")
            gl.write_recording(p, frames, {"lighting": "synthetic"})
            header, back = gl.read_recording(p)
        self.assertEqual(header["conditions"]["lighting"], "synthetic")
        self.assertEqual(len(back), 20)


if __name__ == "__main__":
    unittest.main()
