"""Tests for arm_sim.py: forward/inverse kinematics, limits, torque, motion planning."""
import math
import os
import random
import sys
import unittest
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import arm_sim as a  # noqa: E402

ARM = a.DEFAULT_ARM


class ForwardKinematics(unittest.TestCase):
    def test_arm_stretched_out_horizontally(self):
        pts = a.forward([0, 0, 0, 0])
        self.assertAlmostEqual(pts["tip"][0], ARM.L1 + ARM.L2 + ARM.L3)
        self.assertAlmostEqual(pts["tip"][2], ARM.L0)
        self.assertEqual(pts["shoulder"], (0.0, 0.0, ARM.L0))

    def test_straight_up(self):
        tip = a.forward([0, 90, 0, 0])["tip"]
        self.assertAlmostEqual(tip[0], 0.0, places=12)
        self.assertAlmostEqual(tip[2], ARM.L0 + ARM.max_reach)

    def test_a_right_angle_elbow(self):
        pts = a.forward([0, 90, -90, 0])           # upper arm up, forearm and tool horizontal
        self.assertAlmostEqual(pts["elbow"][2], ARM.L0 + ARM.L1)
        self.assertAlmostEqual(pts["tip"][0], ARM.L2 + ARM.L3)
        self.assertAlmostEqual(pts["tip"][2], ARM.L0 + ARM.L1)

    def test_yaw_rotates_the_whole_arm(self):
        tip = a.forward([90, 0, 0, 0])["tip"]
        self.assertAlmostEqual(tip[0], 0.0, places=12)
        self.assertAlmostEqual(tip[1], ARM.max_reach)
        t30 = a.forward([30, 0, 0, 0])["tip"]
        self.assertAlmostEqual(math.hypot(t30[0], t30[1]), ARM.max_reach)

    def test_wrong_number_of_joints(self):
        with self.assertRaises(ValueError):
            a.forward([0, 0, 0])


class InverseKinematics(unittest.TestCase):
    def test_round_trip_over_many_random_poses(self):
        rng = random.Random(1234)
        solved = worst = 0
        for _ in range(1500):
            q = [rng.uniform(j.min_deg, j.max_deg) for j in ARM.joints]
            if a.collisions(q):
                continue
            tip = a.forward(q)["tip"]
            pitch = q[1] + q[2] + q[3]
            res = a.inverse(*tip, pitch_deg=pitch)
            self.assertTrue(res.reachable, (q, tip, res.reason))     # a pose we reached by FK must be solvable
            err = math.dist(a.forward(res.joints_deg)["tip"], tip)
            worst = max(worst, err)
            self.assertFalse(a.within_limits(res.joints_deg))
            solved += 1
        self.assertGreater(solved, 800)
        self.assertLess(worst, 1e-6)

    def test_free_pitch_returns_a_valid_pose(self):
        rng = random.Random(7)
        n = 0
        for _ in range(300):
            q = [rng.uniform(j.min_deg, j.max_deg) for j in ARM.joints]
            if a.collisions(q):
                continue
            tip = a.forward(q)["tip"]
            res = a.inverse(*tip)
            if res.reachable:
                n += 1
                self.assertLess(res.position_error_m, 1e-6)
                self.assertFalse(a.within_limits(res.joints_deg))
                self.assertFalse(a.collisions(res.joints_deg))
        self.assertGreater(n, 100)

    def test_known_target(self):
        res = a.inverse(0.15, 0.05, 0.10, pitch_deg=-45)
        self.assertTrue(res.reachable)
        self.assertAlmostEqual(res.joints_deg[0], math.degrees(math.atan2(0.05, 0.15)), places=4)
        self.assertEqual(res.elbow, "up")

    def test_out_of_reach_and_too_close(self):
        far = a.inverse(0.5, 0, 0.1)
        self.assertFalse(far.reachable)
        self.assertIn("reach", far.reason)
        close = a.inverse(0.01, 0.0, ARM.L0 + 0.02, pitch_deg=90)
        self.assertFalse(close.reachable)

    def test_below_the_table_is_refused(self):
        res = a.inverse(0.15, 0.0, -0.05)
        self.assertFalse(res.reachable)

    def test_targets_behind_the_base(self):
        far = a.inverse(-0.15, 0.0, 0.1, pitch_deg=-30)
        self.assertFalse(far.reachable)                              # too far back for this arm
        pose = [0, 150, -60, 0]                                       # shoulder past vertical: the tip ends up behind the base
        tip = a.forward(pose)["tip"]
        self.assertLess(tip[0], 0)
        near = a.inverse(*tip, pitch_deg=sum(pose[1:]))
        self.assertTrue(near.reachable, near.reason)
        self.assertGreater(near.joints_deg[1], 90)
        self.assertLess(math.dist(a.forward(near.joints_deg)["tip"], tip), 1e-6)
        sideways = a.inverse(0.0, 0.15, 0.1, pitch_deg=-30)          # directly to the side is within +-90 deg of yaw
        self.assertTrue(sideways.reachable)
        self.assertAlmostEqual(sideways.joints_deg[0], 90.0, places=4)

    def test_garbage_inputs_never_raise(self):
        for args in ((float("nan"), 0, 0.1), (0.1, float("inf"), 0.1), ("a", 0, 0), (True, 0, 0.1), (0, 0, 0)):
            self.assertFalse(a.inverse(*args).reachable)
        self.assertFalse(a.inverse(0.1, 0, 0.1, pitch_deg=float("nan")).reachable)

    def test_stretched_arm_reports_a_singularity(self):
        res = a.inverse(0.3395, 0.0, ARM.L0, pitch_deg=0)           # wrist point at 0.2395 m of a 0.24 m two-link reach
        self.assertTrue(res.reachable)
        self.assertLess(res.singularity_margin, 0.15)
        relaxed = a.inverse(0.25, 0.0, ARM.L0 + 0.05, pitch_deg=0)
        self.assertGreater(relaxed.singularity_margin, 0.5)

    def test_every_solution_has_the_requested_pitch(self):
        res = a.inverse(0.18, 0.04, 0.12, pitch_deg=-30)
        self.assertTrue(res.reachable)
        self.assertAlmostEqual(sum(res.joints_deg[1:]), -30.0, places=4)


class Servos(unittest.TestCase):
    def test_mapping_fits_hobby_servo_travel(self):
        for j in ARM.joints:
            lo, hi = j.servo_range()
            self.assertGreaterEqual(lo, 0)
            self.assertLessEqual(hi, 180)
        self.assertEqual(a.to_servo_angles([0, 90, -60, 0]), (90.0, 90.0, 90.0, 90.0))

    def test_roundtrip_and_limits(self):
        q = (12.0, 100.0, -80.0, 25.0)
        self.assertEqual(a.from_servo_angles(a.to_servo_angles(q)), q)
        with self.assertRaises(ValueError):
            a.to_servo_angles([0, 200, 0, 0])

    def test_a_spec_that_needs_more_than_180_degrees_is_rejected(self):
        bad = a.Joint("elbow", -150, 90, 150)
        with self.assertRaises(ValueError):
            a.ArmSpec(joints=(ARM.joints[0], ARM.joints[1], bad, ARM.joints[3]))
        with self.assertRaises(ValueError):
            a.ArmSpec(L1=-1)

    def test_pulse_widths(self):
        self.assertEqual(a.pulse_us(0), 500)
        self.assertEqual(a.pulse_us(90), 1500)
        self.assertEqual(a.pulse_us(180), 2500)
        with self.assertRaises(ValueError):
            a.pulse_us(181)


class Torque(unittest.TestCase):
    def test_horizontal_arm_matches_hand_calculation(self):
        m = a.Masses()
        t = a.static_torques([0, 0, 0, 0], payload_kg=0.1)
        L1, L2, L3 = ARM.L1, ARM.L2, ARM.L3
        shoulder = a.G * (m.link1 * L1 / 2 + m.elbow_servo * L1 + m.link2 * (L1 + L2 / 2) + m.wrist_servo * (L1 + L2)
                          + m.tool * (L1 + L2 + L3 / 2) + 0.1 * (L1 + L2 + L3))
        elbow = a.G * (m.link2 * L2 / 2 + m.wrist_servo * L2 + m.tool * (L2 + L3 / 2) + 0.1 * (L2 + L3))
        wrist = a.G * (m.tool * L3 / 2 + 0.1 * L3)
        self.assertAlmostEqual(t["shoulder"], shoulder, places=9)
        self.assertAlmostEqual(t["elbow"], elbow, places=9)
        self.assertAlmostEqual(t["wrist"], wrist, places=9)

    def test_straight_up_needs_no_holding_torque(self):
        t = a.static_torques([0, 90, 0, 0], payload_kg=0.2)
        for v in t.values():
            self.assertAlmostEqual(v, 0.0, places=12)

    def test_torque_grows_with_payload_and_shoulder_carries_most(self):
        q = [0, 20, -20, 0]
        light, heavy = a.static_torques(q, 0.0), a.static_torques(q, 0.3)
        for k in light:
            self.assertGreater(heavy[k], light[k])
        self.assertGreater(heavy["shoulder"], heavy["elbow"])
        self.assertGreater(heavy["elbow"], heavy["wrist"])
        with self.assertRaises(ValueError):
            a.static_torques(q, -1)

    def test_servo_selection_and_max_payload(self):
        q = [0, 30, -30, 0]
        weak = {"shoulder": "SG90", "elbow": "SG90", "wrist": "SG90"}
        strong = {"shoulder": "MG996R", "elbow": "MG996R", "wrist": "MG90S"}
        self.assertLess(a.max_payload(q, weak), a.max_payload(q, strong))
        self.assertEqual(a.max_payload([0, 0, 0, 0], {"shoulder": "SG90"}), 0.0)      # SG90 can't hold this arm out horizontally
        check = a.servo_check(a.static_torques(q, 0.0), strong)
        self.assertGreater(check["shoulder"]["margin"], 1.0)
        p = a.max_payload(q, strong)
        at_limit = a.servo_check(a.static_torques(q, p), strong)
        self.assertAlmostEqual(min(v["margin"] for v in at_limit.values()), 1.0, places=3)
        with self.assertRaises(ValueError):
            a.servo_check({"shoulder": 1.0}, {"shoulder": "NOPE"})


class Motion(unittest.TestCase):
    def test_a_move_starts_and_ends_exactly_and_respects_the_speed_limit(self):
        q0, q1 = (0, 60, -60, 0), (45, 100, -100, 20)
        path = a.plan_move(q0, q1, max_speed_dps=60, dt=0.02)
        self.assertEqual(path[0][1], tuple(float(v) for v in q0))
        for got, want in zip(path[-1][1], q1):
            self.assertAlmostEqual(got, want, places=9)
        for (t0, p0), (t1, p1) in zip(path, path[1:]):
            for u, v in zip(p0, p1):
                self.assertLessEqual(abs(v - u) / (t1 - t0), 60 + 1e-6)
        first_step = max(abs(v - u) for u, v in zip(path[0][1], path[1][1]))
        mid = len(path) // 2
        mid_step = max(abs(v - u) for u, v in zip(path[mid][1], path[mid + 1][1]))
        self.assertLess(first_step, mid_step)                    # eases in

    def test_zero_length_move(self):
        self.assertEqual(len(a.plan_move((0, 60, -60, 0), (0, 60, -60, 0))), 2)

    def test_moves_through_the_table_are_refused(self):
        start, end = (73, 54, -99, 19), (84, 34, -145, -69)       # both poses are legal; the path between them clips the table
        self.assertFalse(a.collisions(start) or a.collisions(end))
        with self.assertRaises(ValueError) as cm:
            a.plan_move(start, end)
        self.assertIn("collide", str(cm.exception))
        with self.assertRaises(ValueError):
            a.plan_move((0, 90, 0, 0), (0, 0, -150, 0))           # the end pose itself is below the table

    def test_endpoints_outside_limits_are_refused(self):
        with self.assertRaises(ValueError):
            a.plan_move((0, 60, -60, 0), (0, 200, -60, 0))
        with self.assertRaises(ValueError):
            a.plan_move((0, 60, -60, 0), (0, 60, -60, 0), max_speed_dps=0)


class Workspace(unittest.TestCase):
    def test_reachable_region_is_sensible(self):
        ws = a.workspace(step=0.02)
        self.assertGreater(len(ws["points"]), 50)
        self.assertLessEqual(ws["max_radius_m"], ARM.max_reach + 1e-9)
        self.assertLessEqual(ws["max_height_m"], ARM.L0 + ARM.max_reach + 1e-9)
        for r, z in ws["points"][:200]:
            self.assertTrue(a.inverse(r, 0.0, z).reachable)

    def test_svg_is_well_formed(self):
        svg = a.render_svg([20, 70, -60, 10], target=(0.15, 0.05, 0.1), points=[(0.1, 0.1), (0.12, 0.12)])
        root = ET.fromstring(svg)
        self.assertTrue(root.tag.endswith("svg"))
        self.assertNotIn("nan", svg.lower())


if __name__ == "__main__":
    unittest.main()
