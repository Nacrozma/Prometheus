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

    def test_engineering_lab_runs_records_reproduces_and_reports(self):
        import tempfile

        def body(t, p):
            with tempfile.TemporaryDirectory() as d:
                old = p.ENG_DIR
                p.ENG_DIR = d                                     # never write into the real data folder from a test
                try:
                    cat = t.dispatch("engineering_lab", action="catalog")
                    t.assertIn("truss_stiffness", cat["models"])
                    r = t.dispatch("engineering_lab", action="run", model="normal_shock", params={"M1": 2.0})
                    t.assertEqual(r["status"], "success")
                    t.assertAlmostEqual(r["results"]["p2_over_p1"], 4.5)
                    tr = t.dispatch("engineering_lab", action="run", model="trajectory",
                                    params={"mass_initial_kg": 50, "propellant_kg": 25, "thrust_vac_N": 4000, "isp_vac_s": 220})
                    t.assertNotIn("series", tr)                       # the model gets a summary, not every point
                    t.assertIn("profile", tr["plots_available"])
                    rec = t.dispatch("engineering_lab", action="run", model="nozzle", record=True, title="ideal nozzle",
                                     params={"pc": 7e6, "Tc": 3300, "gamma": 1.2, "molar_mass": 0.022, "throat_area": 1e-3, "expansion_ratio": 20})
                    t.assertEqual(rec["validation_status"], "simulation tested")
                    again = t.dispatch("engineering_lab", action="rerun", experiment_id=rec["experiment_id"])
                    t.assertTrue(again["reproduced"])
                    rep = t.dispatch("engineering_lab", action="report", experiment_id=rec["experiment_id"], formats=["md"])
                    t.assertTrue(os.path.exists(rep["files"]["md"]))
                    st = t.dispatch("engineering_lab", action="validation_status")
                    t.assertEqual(st["hardware_tested"], [])
                    t.assertFalse(st["arm_parameters"]["fully_measured"])
                    hil = t.dispatch("engineering_lab", action="hil_simulation")
                    t.assertTrue(hil["passed"] and hil["simulation_only"])
                    sheet = t.dispatch("engineering_lab", action="arm_benchmark_sheet", params={"n_points": 2, "repeats": 2})
                    t.assertTrue(os.path.exists(sheet["sheet"]))
                    t.assertEqual(t.dispatch("engineering_lab", action="run", model="nope")["status"], "error")
                    t.assertEqual(t.dispatch("engineering_lab", action="get", experiment_id="../x")["status"], "error")
                    t.assertEqual(t.dispatch("engineering_lab", action="fly")["status"], "error")
                    t.assertNotIn("engineering_lab", p.DANGEROUS_TOOLS)
                finally:
                    p.ENG_DIR = old
        self.run_case(body)


if __name__ == "__main__":
    unittest.main()
