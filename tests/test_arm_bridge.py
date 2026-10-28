"""Tests for arm_bridge.py: framing, the firmware model's safety rules, and parity with the Arduino sketch."""
import os
import random
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import arm_bridge as b  # noqa: E402

INO = os.path.join(ROOT, "arduino", "arm_controller", "arm_controller.ino")
REST = b.REST_DEG


def link():
    t = b.SimTransport()
    return t, b.ArmBridge(t)


class Framing(unittest.TestCase):
    def test_crc8_standard_check_value(self):
        self.assertEqual(b.crc8(b"123456789"), 0xF4)       # the published CRC-8 (poly 0x07) check value
        self.assertEqual(b.crc8(b""), 0)

    def test_roundtrip(self):
        angles = (12.3, 90.0, 179.9, 0.0, 55.5)
        frame = b.encode_frame(b.CMD_SET_ANGLES, b.encode_angles(angles))
        self.assertEqual(frame[0], b.SOF)
        got = b.FrameParser().feed(frame)
        self.assertEqual(got[0][0], b.CMD_SET_ANGLES)
        self.assertEqual(b.decode_angles(got[0][1]), angles)

    def test_byte_at_a_time_and_back_to_back_frames(self):
        stream = b.encode_frame(b.CMD_HEARTBEAT) + b.encode_frame(b.CMD_ESTOP) + b.encode_frame(b.CMD_GET_STATUS)
        p = b.FrameParser()
        got = []
        for byte in stream:
            got += p.feed(bytes([byte]))
        self.assertEqual([c for c, _ in got], [b.CMD_HEARTBEAT, b.CMD_ESTOP, b.CMD_GET_STATUS])

    def test_garbage_before_and_between_frames_is_skipped(self):
        good = b.encode_frame(b.CMD_HEARTBEAT)
        p = b.FrameParser()
        got = p.feed(b"\x00\x01\x02" + good + b"\xff\xfe" + good)
        self.assertEqual(len(got), 2)
        self.assertGreaterEqual(p.dropped_bytes, 5)

    def test_corrupt_checksum_is_rejected_and_the_next_frame_still_parses(self):
        bad = bytearray(b.encode_frame(b.CMD_SET_ANGLES, b.encode_angles((1, 2, 3, 4, 50))))
        bad[-1] ^= 0x55
        good = b.encode_frame(b.CMD_HEARTBEAT)
        p = b.FrameParser()
        got = p.feed(bytes(bad) + good)
        self.assertEqual([c for c, _ in got], [b.CMD_HEARTBEAT])
        self.assertEqual(p.bad_crc >= 1, True)

    def test_a_real_frame_inside_a_truncated_one_is_recovered(self):
        truncated = b.encode_frame(b.CMD_SET_ANGLES, b.encode_angles((1, 2, 3, 4, 50)))[:6]      # lost its tail
        good = b.encode_frame(b.CMD_ESTOP)
        got = b.FrameParser().feed(truncated + good + b.encode_frame(b.CMD_HEARTBEAT))
        self.assertIn(b.CMD_ESTOP, [c for c, _ in got])

    def test_oversized_length_byte_does_not_stall_the_parser(self):
        p = b.FrameParser()
        got = p.feed(bytes([b.SOF, 200]) + b.encode_frame(b.CMD_HEARTBEAT))
        self.assertEqual([c for c, _ in got], [b.CMD_HEARTBEAT])

    def test_fuzz_never_raises_and_recovers_valid_frames(self):
        rng = random.Random(99)
        good = b.encode_frame(b.CMD_HEARTBEAT)
        for _ in range(300):
            noise = bytes(x for x in (rng.randrange(256) for _ in range(rng.randrange(40))) if x != b.SOF)
            p = b.FrameParser()
            self.assertEqual([c for c, _ in p.feed(noise + good)], [b.CMD_HEARTBEAT])
            b.FrameParser().feed(bytes(rng.randrange(256) for _ in range(200)))      # pure noise: must not raise

    def test_encoding_validation(self):
        for bad in ((1, 2, 3), (1, 2, 3, 4, float("nan")), (1, 2, 3, 4, -1), (1, 2, 3, 4, 7000), (1, 2, 3, 4, True)):
            with self.assertRaises(ValueError):
                b.encode_angles(bad)
        with self.assertRaises(ValueError):
            b.encode_frame(1, bytes(17))


class FirmwareRules(unittest.TestCase):
    def test_boots_holding_rest_with_no_link(self):
        t, _ = link()
        t.advance(2.0)
        self.assertEqual(t.firmware.state, b.STATE_LINK_LOST)
        self.assertEqual(tuple(t.firmware.current), tuple(float(v) for v in REST))

    def test_first_valid_frame_establishes_the_link_and_motion_is_slew_limited(self):
        t, host = link()
        host.send_angles((120, 90, 90, 90, 40))
        self.assertEqual(t.firmware.state, b.STATE_OK)
        t.advance(0.2)
        self.assertAlmostEqual(t.firmware.current[0], 90 + b.MAX_SLEW_DPS * 0.2, places=3)       # 30 deg in 0.2 s at most 90 deg/s... capped by distance
        host.heartbeat()
        t.advance(0.4)
        host.heartbeat()
        t.advance(0.4)
        self.assertAlmostEqual(t.firmware.current[0], 120.0, places=6)

    def test_no_joint_ever_exceeds_the_slew_limit(self):
        t, host = link()
        host.send_angles((0, 180, 0, 180, 100))
        prev = list(t.firmware.current)
        for _ in range(100):
            t.advance(0.01)
            host.heartbeat()
            for a, c in zip(prev, t.firmware.current):
                self.assertLessEqual(abs(c - a), b.MAX_SLEW_DPS * 0.01 + 1e-9)
            prev = list(t.firmware.current)

    def test_firmware_clamps_even_if_the_host_does_not(self):
        t = b.SimTransport()
        t.write(b.encode_frame(b.CMD_SET_ANGLES, b.encode_angles((90, 90, 90, 90, 150))))          # gripper limit is 100
        self.assertEqual(t.firmware.target[4], 100.0)
        self.assertEqual(t.firmware.clamped_commands, 1)

    def test_host_refuses_out_of_limit_angles(self):
        _, host = link()
        with self.assertRaises(ValueError):
            host.send_angles((90, 90, 90, 90, 150))
        with self.assertRaises(ValueError):
            host.send_angles((90, 90, 90, 90, 5))

    def test_watchdog_holds_position_when_the_host_goes_quiet(self):
        t, host = link()
        host.send_angles((180, 90, 90, 90, 40))
        t.advance(0.3)
        mid = t.firmware.current[0]
        self.assertLess(mid, 180)
        t.advance(2.0)                                           # no more frames
        self.assertEqual(t.firmware.state, b.STATE_LINK_LOST)
        frozen = t.firmware.current[0]
        self.assertLess(frozen, 180)                              # it stopped where it was at the watchdog, not at the target
        self.assertLess(frozen, mid + b.MAX_SLEW_DPS * (b.WATCHDOG_S + 0.05))
        t.advance(2.0)
        self.assertEqual(t.firmware.current[0], frozen)

    def test_heartbeats_keep_the_link_alive(self):
        t, host = link()
        host.send_angles((100, 90, 90, 90, 40))
        for _ in range(100):
            t.advance(0.2)
            host.heartbeat()
        self.assertEqual(t.firmware.state, b.STATE_OK)

    def test_link_recovers_after_a_watchdog_stop(self):
        t, host = link()
        host.send_angles((100, 90, 90, 90, 40))
        t.advance(1.0)
        self.assertEqual(t.firmware.state, b.STATE_LINK_LOST)
        host.send_angles((110, 90, 90, 90, 40))
        self.assertEqual(t.firmware.state, b.STATE_OK)

    def test_estop_freezes_and_blocks_motion_until_cleared(self):
        t, host = link()
        host.send_angles((180, 90, 90, 90, 40))
        t.advance(0.2)
        host.estop()
        held = t.firmware.current[0]
        host.send_angles((0, 90, 90, 90, 40))                    # ignored
        t.advance(0.5)
        host.heartbeat()                                          # a heartbeat must NOT clear an e-stop
        t.advance(0.3)
        self.assertEqual(t.firmware.state, b.STATE_ESTOP)
        self.assertEqual(t.firmware.current[0], held)
        self.assertGreaterEqual(t.firmware.rejected_commands, 1)
        host.clear_estop()
        self.assertEqual(t.firmware.state, b.STATE_OK)
        self.assertEqual(t.firmware.target[0], held)             # clearing does not resume the old target
        host.send_angles((60, 90, 90, 90, 40))
        t.advance(1.0)
        host.heartbeat()
        self.assertLess(t.firmware.current[0], held)

    def test_estop_survives_the_watchdog(self):
        t, host = link()
        host.estop()
        t.advance(5.0)
        self.assertEqual(t.firmware.state, b.STATE_ESTOP)

    def test_corrupted_and_dropped_frames_do_not_move_the_arm(self):
        t, host = link()
        host.heartbeat()
        t.corrupt_next_writes = 1
        host.send_angles((170, 90, 90, 90, 40))
        t.advance(1.0)
        self.assertEqual(t.firmware.current[0], 90.0)
        t.drop_next_writes = 1
        host.send_angles((170, 90, 90, 90, 40))
        t.advance(0.1)
        self.assertEqual(t.firmware.current[0], 90.0)

    def test_status_reports_state_and_pose(self):
        t, host = link()
        host.send_angles((100, 90, 90, 90, 40))
        t.advance(0.05)
        st = host.request_status()
        self.assertEqual(st["state"], b.STATE_OK)
        self.assertAlmostEqual(st["angles_deg"][0], t.firmware.current[0], places=1)

    def test_wrong_length_set_angles_is_rejected(self):
        t = b.SimTransport()
        t.write(b.encode_frame(b.CMD_SET_ANGLES, b"\x01\x02\x03"))
        self.assertEqual(t.firmware.rejected_commands, 1)
        self.assertEqual(list(t.firmware.target), list(map(float, REST)))


class SketchParity(unittest.TestCase):
    """The Arduino sketch cannot be compiled here, but its protocol constants must at least match the model."""

    @classmethod
    def setUpClass(cls):
        cls.src = open(INO, encoding="utf-8").read()

    def const(self, name):
        m = re.search(rf"\b{name}\s*=\s*(0x[0-9A-Fa-f]+|[0-9.]+)", self.src)
        self.assertIsNotNone(m, name)
        return float(int(m.group(1), 16)) if m.group(1).startswith("0x") else float(m.group(1))

    def array(self, name):
        m = re.search(rf"\b{name}\s*\[[^\]]*\]\s*=\s*\{{([^}}]*)\}}", self.src)
        self.assertIsNotNone(m, name)
        return [float(x) for x in m.group(1).split(",")]

    def test_protocol_constants_match(self):
        for name in ("SOF", "MAX_PAYLOAD", "CMD_SET_ANGLES", "CMD_HEARTBEAT", "CMD_ESTOP", "CMD_CLEAR_ESTOP", "CMD_GET_STATUS",
                     "RSP_STATUS", "CRC_POLY", "NUM_JOINTS"):
            self.assertEqual(self.const(name), float(getattr(b, name)), name)
        self.assertEqual(self.const("WATCHDOG_MS") / 1000, b.WATCHDOG_S)
        self.assertEqual(self.const("MAX_SLEW_DPS"), b.MAX_SLEW_DPS)

    def test_states_match(self):
        for name, value in (("STATE_OK", b.STATE_OK), ("STATE_LINK_LOST", b.STATE_LINK_LOST), ("STATE_ESTOP", b.STATE_ESTOP)):
            self.assertIn(f"{name} = {value}", self.src)

    def test_limits_and_rest_pose_match(self):
        self.assertEqual(self.array("LIMIT_MIN"), [float(lo) for lo, _ in b.LIMITS_DEG])
        self.assertEqual(self.array("LIMIT_MAX"), [float(hi) for _, hi in b.LIMITS_DEG])
        self.assertEqual(self.array("REST_DEG"), [float(v) for v in b.REST_DEG])

    def test_sketch_states_its_status_honestly_and_has_balanced_braces(self):
        self.assertIn("NOT COMPILED OR RUN", self.src)
        self.assertEqual(self.src.count("{"), self.src.count("}"))
        self.assertEqual(self.src.count("("), self.src.count(")"))

    def test_sketch_keeps_the_safety_rules(self):
        for needle in ("WATCHDOG_MS", "LIMIT_MIN", "LIMIT_MAX", "MAX_SLEW_DPS", "STATE_ESTOP", "does not trust the host"):
            self.assertIn(needle, self.src)


if __name__ == "__main__":
    unittest.main()
