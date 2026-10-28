"""Tests for arm_gesture.py with synthetic hands, and the whole chain gesture -> IK -> bridge -> firmware model."""
import math
import os
import random
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import arm_bridge as br  # noqa: E402
import arm_gesture as g  # noqa: E402
import arm_sim  # noqa: E402


def settle(ctrl, hand, n=12):
    cmd = None
    for _ in range(n):
        cmd = ctrl.step(hand)
    return cmd


class Features(unittest.TestCase):
    def test_features_recover_what_the_synthetic_hand_was_built_with(self):
        f, why = g.hand_features(g.synthetic_hand(0.4, 0.6, 0.12, pinch=0.5))
        self.assertEqual(why, "")
        self.assertAlmostEqual(f.center_x, 0.4, places=9)
        self.assertAlmostEqual(f.center_y, 0.6, places=9)
        self.assertAlmostEqual(f.palm_size, 0.12, places=9)
        self.assertAlmostEqual(f.pinch, 0.5, places=9)

    def test_bad_input_is_rejected_not_crashed_on(self):
        good = g.synthetic_hand(0.5, 0.5, 0.12)
        cases = [None, [], good[:20], "hand", [(0.5, 0.5)] * 21, [(float("nan"), 0.5, 0)] * 21, [(5.0, 0.5, 0)] * 21,
                 [("a", "b", "c")] * 21, g.synthetic_hand(0.5, 0.5, 0.001)]
        for c in cases:
            f, why = g.hand_features(c)
            self.assertIsNone(f, c)
            self.assertTrue(why)

    def test_mapping_directions(self):
        cal = g.Calibration()
        mid = g.features_to_target(g.HandFeatures(0.5, 0.5, 0.13, 1.0), cal)[0]
        right = g.features_to_target(g.HandFeatures(0.7, 0.5, 0.13, 1.0), cal)[0]
        high = g.features_to_target(g.HandFeatures(0.5, 0.3, 0.13, 1.0), cal)[0]
        near = g.features_to_target(g.HandFeatures(0.5, 0.5, 0.18, 1.0), cal)[0]
        self.assertLess(right[1], mid[1])             # selfie view: my right = the arm's right (negative y)
        self.assertGreater(high[2], mid[2])
        self.assertGreater(near[0], mid[0])
        flipped = g.features_to_target(g.HandFeatures(0.7, 0.5, 0.13, 1.0), g.Calibration(mirror=False))[0]
        self.assertGreater(flipped[1], mid[1])

    def test_mapping_is_bounded_for_extreme_hands(self):
        cal = g.Calibration()
        for fx in (g.HandFeatures(-0.1, -0.1, 0.5, 5.0), g.HandFeatures(1.1, 1.1, 0.02, 0.0)):
            (x, y, z), op = g.features_to_target(fx, cal)
            self.assertTrue(cal.reach_min <= x <= cal.reach_max)
            self.assertTrue(abs(y) <= cal.y_span / 2 + 1e-12)
            self.assertTrue(cal.z_min <= z <= cal.z_max)
            self.assertTrue(0 <= op <= 1)

    def test_pinch_controls_the_gripper(self):
        cal = g.Calibration()
        self.assertEqual(g.features_to_target(g.HandFeatures(0.5, 0.5, 0.13, 0.1), cal)[1], 0.0)
        self.assertEqual(g.features_to_target(g.HandFeatures(0.5, 0.5, 0.13, 1.5), cal)[1], 1.0)
        self.assertAlmostEqual(g.features_to_target(g.HandFeatures(0.5, 0.5, 0.13, 0.625), cal)[1], 0.5)


class Controller(unittest.TestCase):
    def test_does_not_move_until_the_hand_has_been_still(self):
        c = g.GestureController(arm_after=6)
        sent = [c.step(g.synthetic_hand(0.5, 0.5, 0.13)).send for _ in range(8)]
        self.assertEqual(sent, [False] * 5 + [True] * 3)

    def test_a_moving_hand_never_arms_the_arm(self):
        c = g.GestureController(arm_after=6)
        for i in range(30):
            cmd = c.step(g.synthetic_hand(0.2 + 0.6 * (i % 2), 0.5, 0.13))        # waving back and forth
            self.assertFalse(cmd.send)

    def test_tracking_follows_the_hand_with_smoothing(self):
        c = g.GestureController(alpha=0.3)
        settle(c, g.synthetic_hand(0.5, 0.5, 0.13))
        first = c.step(g.synthetic_hand(0.58, 0.5, 0.13))
        later = settle(c, g.synthetic_hand(0.58, 0.5, 0.13), 40)
        settled_y = g.features_to_target(g.HandFeatures(0.58, 0.5, 0.13, 1.0), g.Calibration())[0][1]
        self.assertGreater(first.target_m[1], settled_y)         # still on its way (y is negative for the right)
        self.assertAlmostEqual(later.target_m[1], settled_y, delta=0.005)

    def test_deadband_suppresses_jitter(self):
        c = g.GestureController(deadband_m=0.01)
        base = settle(c, g.synthetic_hand(0.5, 0.5, 0.13)).target_m
        rng = random.Random(3)
        for _ in range(50):
            cmd = c.step(g.synthetic_hand(0.5 + rng.uniform(-0.002, 0.002), 0.5 + rng.uniform(-0.002, 0.002), 0.13))
            self.assertEqual(cmd.target_m, base)

    def test_one_frame_glitch_is_ignored_but_a_real_move_is_followed(self):
        c = g.GestureController()
        before = settle(c, g.synthetic_hand(0.5, 0.5, 0.13))
        glitch = c.step(g.synthetic_hand(0.9, 0.2, 0.13))
        self.assertEqual(glitch.target_m, before.target_m)
        self.assertIn("jump", glitch.reason)
        after = c.step(g.synthetic_hand(0.5, 0.5, 0.13))
        self.assertEqual(after.state, "tracking")
        final = settle(c, g.synthetic_hand(0.8, 0.3, 0.13), 40)  # the hand genuinely moved
        self.assertNotEqual(final.target_m, before.target_m)

    def test_losing_the_hand_holds_then_stops_and_rearms(self):
        c = g.GestureController(hold_lost_frames=5, arm_after=4)
        last = settle(c, g.synthetic_hand(0.5, 0.5, 0.13))
        for _ in range(5):
            cmd = c.step(None)
            self.assertEqual(cmd.state, "holding")
            self.assertEqual(cmd.servo_deg, last.servo_deg)
        gone = c.step(None)
        self.assertEqual((gone.state, gone.send), ("idle", False))
        again = [c.step(g.synthetic_hand(0.5, 0.5, 0.13)) for _ in range(5)]
        self.assertFalse(again[0].send)                           # must be still again before it follows
        self.assertTrue(again[-1].send)

    def test_a_brief_dropout_resumes_without_rearming(self):
        c = g.GestureController(hold_lost_frames=10)
        settle(c, g.synthetic_hand(0.5, 0.5, 0.13))
        c.step(None)
        c.step(None)
        self.assertEqual(c.step(g.synthetic_hand(0.5, 0.5, 0.13)).state, "tracking")

    def test_out_of_workspace_targets_are_pulled_back_not_refused(self):
        cal = g.Calibration(reach_max=0.9, reach_min=0.5, z_max=0.9)
        c = g.GestureController(calib=cal)
        cmd = settle(c, g.synthetic_hand(0.5, 0.2, 0.2))
        self.assertTrue(cmd.send)
        self.assertTrue(cmd.clamped)
        self.assertLess(math.dist(arm_sim.forward(cmd.joints_deg)["tip"], cmd.target_m), 1e-4)

    def test_garbage_frames_never_command_the_arm(self):
        c = g.GestureController()
        settle(c, g.synthetic_hand(0.5, 0.5, 0.13))
        for bad in ([(float("nan"), 0, 0)] * 21, [(0, 0, 0)] * 21, "x", [1, 2, 3]):
            cmd = c.step(bad)
            self.assertEqual(cmd.state, "holding")
        self.assertGreater(c.rejected_frames, 0)

    def test_every_command_is_within_servo_limits_over_a_random_session(self):
        rng = random.Random(21)
        c = g.GestureController(arm_after=3)
        for _ in range(2000):
            hand = g.synthetic_hand(rng.uniform(-0.1, 1.1), rng.uniform(-0.1, 1.1), rng.uniform(0.03, 0.4), rng.uniform(0, 2))
            if rng.random() < 0.1:
                hand = None
            cmd = c.step(hand)
            if cmd.send:
                lo_hi = br.LIMITS_DEG
                for v, (lo, hi) in zip(cmd.servo_deg, lo_hi):
                    self.assertTrue(lo <= v <= hi, (cmd.servo_deg, cmd.reason))
                self.assertFalse(arm_sim.collisions(cmd.joints_deg))
                self.assertFalse(arm_sim.within_limits(cmd.joints_deg))

    def test_bad_parameters(self):
        with self.assertRaises(ValueError):
            g.GestureController(alpha=0)


class WholeChain(unittest.TestCase):
    """Synthetic hand -> controller -> IK -> bridge -> firmware model, on a virtual clock."""

    def test_the_simulated_arm_follows_the_hand_and_stays_safe(self):
        t = br.SimTransport()
        host = br.ArmBridge(t)
        ctrl = g.GestureController(arm_after=4)
        max_step = 0.0
        prev = list(t.firmware.current)
        for i in range(240):                                       # 8 s at 30 fps
            phase = i / 240
            hand = g.synthetic_hand(0.35 + 0.3 * phase, 0.45, 0.12 + 0.04 * math.sin(6 * phase), pinch=1.0 if phase < 0.7 else 0.2)
            cmd = ctrl.step(hand)
            host.heartbeat()
            if cmd.send:
                host.send_angles(cmd.servo_deg)
            t.advance(1 / 30)
            max_step = max(max_step, max(abs(a - b) for a, b in zip(prev, t.firmware.current)))
            prev = list(t.firmware.current)
        self.assertEqual(t.firmware.state, br.STATE_OK)
        self.assertLessEqual(max_step, br.MAX_SLEW_DPS / 30 + 1e-6)
        self.assertEqual(t.firmware.clamped_commands, 0)           # the host never asked for something illegal
        self.assertLess(t.firmware.current[4], 60)                 # the pinch closed the gripper toward the end
        tip = arm_sim.forward(arm_sim.from_servo_angles(t.firmware.current[:4]))["tip"]
        self.assertGreater(tip[0], 0.05)

    def test_if_the_pipeline_dies_the_arm_stops(self):
        t = br.SimTransport()
        host = br.ArmBridge(t)
        ctrl = g.GestureController(arm_after=3)
        for _ in range(30):
            cmd = ctrl.step(g.synthetic_hand(0.3, 0.5, 0.15))
            host.heartbeat()
            if cmd.send:
                host.send_angles(cmd.servo_deg)
            t.advance(1 / 30)
        t.advance(2.0)                                             # the host program crashed: no more frames
        self.assertEqual(t.firmware.state, br.STATE_LINK_LOST)
        frozen = list(t.firmware.current)
        self.assertEqual(list(t.firmware.target), frozen)          # the unfinished move was abandoned, not just paused
        t.advance(3.0)
        self.assertEqual(list(t.firmware.current), frozen)


if __name__ == "__main__":
    unittest.main()
