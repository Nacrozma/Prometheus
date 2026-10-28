"""engineering_calc and arm_plan as Prometheus tools."""
import io
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("PROMETHEUS_FAST_BOOT", "1")


class Tools(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_memory_integration import Redirected
        cls.Base = Redirected

    def run_case(self, body):
        Base = self.Base

        class Case(Base):
            def runTest(inner):
                import prometheus as p
                body(inner, p)
        res = unittest.TextTestRunner(stream=io.StringIO()).run(Case())
        self.assertTrue(res.wasSuccessful(), [str(e[1]) for e in res.errors + res.failures])

    def test_engineering_calc_through_the_dispatcher(self):
        def body(t, p):
            r = t.dispatch("engineering_calc", calc="hohmann", params={"altitude_1_m": 300e3, "altitude_2_m": 35786e3})
            t.assertEqual(r["status"], "success")
            t.assertAlmostEqual(r["results"]["total_delta_v_m_s"], 3893, delta=25)
            t.assertIn("formula", r)
            listing = t.dispatch("engineering_calc")
            t.assertIn("hohmann", listing["available"])
            t.assertEqual(t.dispatch("engineering_calc", calc="nope")["status"], "error")
            t.assertEqual(t.dispatch("engineering_calc", calc="beam", params="not a dict")["status"], "error")
            t.assertEqual(t.dispatch("engineering_calc", calc="lift", params={"calc": "x"})["status"], "error")
            t.assertEqual(t.dispatch("engineering_calc", calc="isa_atmosphere", params={"altitude_m": "high"})["status"], "error")
        self.run_case(body)

    def test_arm_plan_reports_ik_torque_and_is_labelled_simulation(self):
        def body(t, p):
            r = t.dispatch("arm_plan", x=0.15, y=0.05, z=0.10)
            t.assertEqual(r["status"], "success")
            t.assertTrue(r["simulation_only"])
            t.assertEqual(set(r["joints_deg"]), {"yaw", "shoulder", "elbow", "wrist"})
            t.assertGreater(r["servo_margin"]["shoulder"], 0)
            far = t.dispatch("arm_plan", x=1.0, y=0.0, z=0.1)
            t.assertEqual(far["status"], "error")
            t.assertTrue(far["simulation_only"])
            weak = t.dispatch("arm_plan", x=0.2, y=0.0, z=0.1, payload_kg=0.5, servo_model="SG90")
            t.assertTrue(weak["warnings"])
            t.assertEqual(t.dispatch("arm_plan", x=0.15, y=0.0, z=0.1, servo_model="NOPE")["status"], "error")
            t.assertEqual(t.dispatch("arm_plan", x="a", y=0.0, z=0.1)["status"], "error")
            t.assertEqual(t.dispatch("arm_plan", y=0.0, z=0.1)["status"], "error")
        self.run_case(body)

    def test_neither_tool_needs_confirmation_and_both_are_recorded(self):
        def body(t, p):
            for name in ("engineering_calc", "arm_plan"):
                t.assertNotIn(name, p.DANGEROUS_TOOLS)
            t.dispatch("engineering_calc", calc="lift", params={"density": 1.2, "speed": 30, "area": 10, "cl": 1})
            t.assertEqual(p.tool_stats.summary()["engineering_calc"]["successes"], 1)
            t.assertEqual(p.audit_log.tail(1)[0]["tool"], "engineering_calc")
        self.run_case(body)


if __name__ == "__main__":
    unittest.main()
