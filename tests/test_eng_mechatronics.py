"""Arm mechatronics: calibration provenance and the bench hardware-in-the-loop checks.

All tests run against arm_bridge.FirmwareSim (a software model). Mocked/simulated transports are NOT
evidence that the real board behaves the same: that needs `python -m eng.hil --port ... --servo-power-disconnected`.
"""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import arm_bridge as br  # noqa: E402
import arm_sim  # noqa: E402
from eng import EngError, calibration as cal, hil  # noqa: E402


class Calibration(unittest.TestCase):
    def test_defaults_are_provisional_and_match_arm_sim(self):
        c = cal.Calibration()
        self.assertEqual(c.summary()["measured"], [])
        self.assertFalse(c.summary()["fully_measured"])
        self.assertEqual(c.arm_spec().L1, arm_sim.DEFAULT_ARM.L1)
        self.assertEqual(c.masses(), arm_sim.Masses())

    def test_a_measurement_needs_full_provenance(self):
        c = cal.Calibration()
        with self.assertRaises(EngError):
            c.set_measured("L1", 0.118, "m", "calliper", "", 0.0002, "2026-11-21", "bench")      # no equipment
        with self.assertRaises(EngError):
            c.set_measured("L1", 0.118, "mm", "calliper", "Mitutoyo 500", 0.0002, "2026-11-21", "bench")   # wrong unit
        with self.assertRaises(EngError):
            c.set_measured("L1", 0.118, "m", "calliper", "Mitutoyo 500", 0.0002, "21/11/2026", "bench")    # not ISO
        with self.assertRaises(EngError):
            c.set_measured("com_link1", 1.4, "fraction of L1", "knife edge", "rule", 0.01, "2026-11-21", "bench")

    def test_round_trip_keeps_only_measured_values_and_reports_the_rest(self):
        c = cal.Calibration()
        c.set_measured("L1", 0.1182, "m", "calliper, 3 readings", "digital calliper 0.01 mm", 0.00006, "2026-11-21", "test fixture")
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "cal.json")
            c.save(path)
            data = json.load(open(path))
            self.assertEqual([p["name"] for p in data["parameters"]], ["L1"])
            back = cal.Calibration.load(path)
        self.assertAlmostEqual(back.arm_spec().L1, 0.1182)
        self.assertIn("L2", back.summary()["provisional"])
        self.assertNotIn("L1", back.summary()["provisional"])

    def test_bad_files_are_errors_not_silent_defaults(self):
        with self.assertRaises(EngError):
            cal.Calibration.from_dict({"parameters": [{"name": "L9", "value": 1, "unit": "m"}]})
        with self.assertRaises(EngError):
            cal.Calibration.from_dict({"parameters": "nope"})

    def test_template_lists_every_parameter_with_a_method(self):
        t = cal.template()
        self.assertEqual(len(t["rows"]), len(cal.PARAMETERS))
        self.assertTrue(all(r["suggested_method"] for r in t["rows"]))


class Bench(unittest.TestCase):
    def test_all_checks_pass_on_the_firmware_model(self):
        rep = hil.run_bench(br.SimTransport())
        self.assertTrue(rep.passed, [c for c in rep.checks if not c.passed])
        self.assertEqual(rep.target, "simulation model")
        self.assertGreaterEqual(len(rep.checks), 9)

    def test_a_real_port_is_refused_unless_servo_power_is_disconnected(self):
        class FakePort:                                    # stands in for SerialTransport; never touched
            def write(self, data):
                raise AssertionError("must not write")

            def read(self):
                return b""

        with self.assertRaises(PermissionError):
            hil.run_bench(FakePort())

    def test_the_bench_catches_a_firmware_without_a_watchdog(self):
        rep = hil.run_bench(br.SimTransport(br.FirmwareSim(watchdog_s=60.0)))
        failed = [c.name for c in rep.checks if not c.passed]
        self.assertIn("watchdog stops motion after link loss", failed)

    def test_the_bench_catches_a_firmware_that_boots_armed(self):
        fw = br.FirmwareSim()
        fw.state = br.STATE_OK                             # the old behaviour: moves on the first frame
        rep = hil.run_bench(br.SimTransport(fw))
        failed = [c.name for c in rep.checks if not c.passed]
        self.assertIn("boots disarmed", failed)
        self.assertIn("motion refused while disarmed", failed)

    def test_the_bench_catches_a_too_fast_slew(self):
        rep = hil.run_bench(br.SimTransport(br.FirmwareSim(slew_dps=400.0)))
        self.assertIn("slew limited", [c.name for c in rep.checks if not c.passed])

    def test_the_bench_leaves_the_arm_stopped(self):
        t = br.SimTransport()
        hil.run_bench(t)
        self.assertEqual(t.firmware.state, br.STATE_ESTOP)


if __name__ == "__main__":
    unittest.main()
