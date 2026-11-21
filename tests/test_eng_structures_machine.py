"""Direct-stiffness structures, machine design and design optimisation, against analytic references."""
import math
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import engineering  # noqa: E402
from eng import EngError, machine as M, optimize as O, structures as S  # noqa: E402

E, A, I = 200e9, 1e-3, 8e-6


class Trusses(unittest.TestCase):
    def test_determinate_truss_matches_the_method_of_joints(self):
        nodes = {"A": [0, 0], "B": [2, 0], "C": [4, 0], "D": [1, 1.5], "E": [3, 1.5]}
        members = [["A", "B"], ["B", "C"], ["A", "D"], ["D", "B"], ["B", "E"], ["E", "C"], ["D", "E"]]
        supports = {"A": "pin", "C": "roller"}
        loads = {"D": [0, -10e3], "E": [2e3, -5e3]}
        ref = engineering.truss(nodes, members, supports, loads)["results"]
        got = S.truss_stiffness(nodes, members, supports, loads)["results"]
        for k, v in ref["member_forces_N"].items():
            self.assertAlmostEqual(got["member_forces_N"][k], v, delta=1e-6 * 10e3)
        self.assertEqual(got["degree_of_indeterminacy"], 0)

    def test_three_bar_indeterminate_truss_closed_form(self):
        # symmetric three-bar truss, centre bar vertical (length L), sides at angle t:
        # F_centre = P / (1 + 2 cos^3 t), F_side = P cos^2 t / (1 + 2 cos^3 t)   (equal EA)
        for deg in (20, 30, 45, 60):
            t = math.radians(deg)
            nodes = {"D": [0, 0], "A": [-math.tan(t), 1], "B": [0, 1], "C": [math.tan(t), 1]}
            r = S.truss_stiffness(nodes, [["A", "D"], ["B", "D"], ["C", "D"]], {"A": "pin", "B": "pin", "C": "pin"}, {"D": [0, -1000]})["results"]
            c = math.cos(t)
            self.assertAlmostEqual(r["member_forces_N"]["B-D"], 1000 / (1 + 2 * c ** 3), places=8)
            self.assertAlmostEqual(r["member_forces_N"]["A-D"], 1000 * c * c / (1 + 2 * c ** 3), places=8)
            self.assertEqual(r["degree_of_indeterminacy"], 1)
            self.assertAlmostEqual(r["displacements_m"]["D"][1], -r["member_forces_N"]["B-D"] * 1 / (200e9 * 1e-4), places=15)

    def test_equilibrium_and_symmetry(self):
        nodes = {"A": [0, 0], "B": [1, 1], "C": [2, 0], "D": [1, 0]}
        r = S.truss_stiffness(nodes, [["A", "B"], ["B", "C"], ["A", "D"], ["D", "C"], ["B", "D"]], {"A": "pin", "C": "pin"}, {"D": [0, -500]})["results"]
        eq = r["equilibrium_residual"]
        self.assertLess(max(abs(eq["sum_Fx_N"]), abs(eq["sum_Fy_N"]), abs(eq["sum_M_Nm"])), 1e-8)
        self.assertAlmostEqual(r["member_forces_N"]["A-B"], r["member_forces_N"]["B-C"], places=9)
        self.assertAlmostEqual(r["reactions_N"]["A.y"], 250.0, places=9)

    def test_support_settlement_of_an_indeterminate_truss_creates_force(self):
        nodes = {"A": [0, 0], "B": [0, 1], "C": [1, 0.5]}
        free = S.truss_stiffness(nodes, [["A", "C"], ["B", "C"]], {"A": "pin", "B": "pin", "C": "roller"}, {})["results"]
        moved = S.truss_stiffness(nodes, [["A", "C"], ["B", "C"]], {"A": "pin", "B": "pin", "C": "roller"}, {}, settlements={"C": [0, -0.001]})["results"]
        self.assertAlmostEqual(max(abs(v) for v in free["member_forces_N"].values()), 0.0, places=9)
        self.assertGreater(max(abs(v) for v in moved["member_forces_N"].values()), 1.0)

    def test_mechanisms_and_bad_input_are_errors(self):
        with self.assertRaises(EngError) as ctx:
            S.truss_stiffness({"A": [0, 0], "B": [1, 0], "C": [1, 1], "D": [0, 1]},
                              [["A", "B"], ["B", "C"], ["C", "D"], ["D", "A"]], {"A": "pin", "B": "roller"}, {"C": [10, 0]})
        self.assertIn("mechanism", str(ctx.exception))
        for bad in ({"A": [0, 0], "B": [0, 0]}, {"A": [0, 0]}):
            with self.assertRaises(EngError):
                S.truss_stiffness(bad, [["A", "B"]], {"A": "pin"}, {})
        with self.assertRaises(EngError):
            S.truss_stiffness({"A": [0, 0], "B": [1, 0]}, [["A", "B"]], {"A": "fixed"}, {})


class Frames(unittest.TestCase):
    def test_cantilever_tip_load(self):
        L, P = 2.0, 1000.0
        r = S.frame({"A": [0, 0], "B": [L, 0]}, [["A", "B"]], {"A": "fixed"}, {"B": [0, -P, 0]}, E=E, A=A, I=I)["results"]
        self.assertAlmostEqual(r["displacements"]["B"]["uy_m"], -P * L ** 3 / (3 * E * I), places=15)
        self.assertAlmostEqual(r["displacements"]["B"]["rot_rad"], -P * L ** 2 / (2 * E * I), places=15)
        self.assertAlmostEqual(r["reactions"]["A.r"], P * L, places=8)

    def test_beams_against_the_closed_forms(self):
        L, w = 3.0, -2000.0
        ss = S.frame({"A": [0, 0], "B": [L, 0]}, [{"nodes": ["A", "B"], "w": w}], {"A": "pin", "B": "roller"}, {}, E=E, A=A, I=I)["results"]
        self.assertAlmostEqual(ss["members"]["A-B"]["max_moment_Nm"], -w * L * L / 8, delta=1e-6)
        # simply supported midspan deflection with 2 elements (node at midspan): 5 w L^4 / 384 EI
        two = S.frame({"A": [0, 0], "M": [L / 2, 0], "B": [L, 0]}, [{"nodes": ["A", "M"], "w": w}, {"nodes": ["M", "B"], "w": w}],
                      {"A": "pin", "B": "roller"}, {}, E=E, A=A, I=I)["results"]
        self.assertAlmostEqual(two["displacements"]["M"]["uy_m"], 5 * w * L ** 4 / (384 * E * I), places=13)
        ff = S.frame({"A": [0, 0], "B": [L, 0]}, [{"nodes": ["A", "B"], "w": w}], {"A": "fixed", "B": "fixed"}, {}, E=E, A=A, I=I)["results"]
        self.assertAlmostEqual(abs(ff["reactions"]["A.r"]), abs(w) * L * L / 12, places=6)
        pc = S.frame({"A": [0, 0], "B": [L, 0]}, [{"nodes": ["A", "B"], "w": w}], {"A": "fixed", "B": "roller"}, {}, E=E, A=A, I=I)["results"]
        self.assertAlmostEqual(pc["reactions"]["B.y"], -3 * w * L / 8, places=6)     # propped cantilever, indeterminate
        self.assertEqual(pc["degree_of_indeterminacy"], 1)

    def test_point_load_continuous_beam_matches_engineering_beam(self):
        L, P = 4.0, 3000.0
        r = S.frame({"A": [0, 0], "C": [1.0, 0], "B": [L, 0]}, [["A", "C"], ["C", "B"]], {"A": "pin", "B": "roller"}, {"C": [0, -P]}, E=E, A=A, I=I)["results"]
        ref = engineering.beam("simply_supported", "point", L, P, E, I, position=1.0)["results"]
        self.assertAlmostEqual(-r["displacements"]["C"]["uy_m"], ref["deflection_under_load_m"], places=13)
        self.assertAlmostEqual(r["reactions"]["A.y"], ref["reaction_left_N"], places=8)

    def test_portal_frame_equilibrium_and_symmetry(self):
        h, b = 3.0, 4.0
        nodes = {"A": [0, 0], "B": [0, h], "C": [b, h], "D": [b, 0]}
        mem = [{"nodes": ["A", "B"]}, {"nodes": ["B", "C"], "w": -5000.0}, {"nodes": ["C", "D"]}]
        r = S.frame(nodes, mem, {"A": "fixed", "D": "fixed"}, {}, E=E, A=A, I=I)["results"]
        eq = r["equilibrium_residual"]
        self.assertLess(max(abs(eq["sum_Fx_N"]), abs(eq["sum_Fy_N"]), abs(eq["sum_M_Nm"])), 1e-6)
        self.assertAlmostEqual(r["reactions"]["A.y"], r["reactions"]["D.y"], places=6)
        self.assertAlmostEqual(r["reactions"]["A.y"], 5000 * b / 2, places=6)
        self.assertAlmostEqual(r["reactions"]["A.x"], -r["reactions"]["D.x"], places=6)
        self.assertEqual(r["degree_of_indeterminacy"], 3)

    def test_stress_is_reported_with_a_fibre_distance(self):
        r = S.frame({"A": [0, 0], "B": [1, 0]}, [{"nodes": ["A", "B"], "c": 0.05}], {"A": "fixed"}, {"B": [0, -100]}, E=E, A=A, I=I)["results"]
        self.assertAlmostEqual(r["members"]["A-B"]["max_normal_stress_Pa"], 100 * 1 * 0.05 / I, places=3)

    def test_unsupported_frame_is_a_mechanism(self):
        with self.assertRaises(EngError):
            S.frame({"A": [0, 0], "B": [1, 0]}, [["A", "B"]], {"A": "pin"}, {"B": [0, -1]})


class MachineDesign(unittest.TestCase):
    def test_marin_factors(self):
        r = M.marin(520e6, "machined", 0.032)["results"]
        self.assertAlmostEqual(r["ka"], 4.51 * 520 ** -0.265, places=12)
        self.assertAlmostEqual(r["ka"], 0.860, places=3)
        self.assertAlmostEqual(r["kb"], 1.24 * 32 ** -0.107, places=12)
        self.assertAlmostEqual(r["Se_prime_Pa"], 260e6)
        self.assertAlmostEqual(M.marin(1600e6)["results"]["Se_prime_Pa"], 700e6)
        self.assertEqual(M.marin(500e6, loading="torsion")["results"]["kc"], 0.59)
        self.assertEqual(M.marin(500e6, reliability=99)["results"]["ke"], 0.814)
        with self.assertRaises(EngError):
            M.marin(500e6, d=0.3)

    def test_stress_concentration_quantities_are_distinct(self):
        self.assertAlmostEqual(M.kt_elliptical_hole(1, 1)["results"]["Kt"], 3.0)
        r = M.fatigue_kf(2.2, 0.002, 600e6)["results"]
        self.assertTrue(0 < r["q"] < 1)
        self.assertTrue(1 < r["Kf"] < r["Kt"])
        self.assertAlmostEqual(r["Kf"], 1 + r["q"] * 1.2, places=12)
        self.assertGreater(M.notch_sensitivity(0.005, 600e6), M.notch_sensitivity(0.0005, 600e6))     # sharp notch: less sensitive
        with self.assertRaises(EngError):
            M.notch_sensitivity(0.001, 200e6)

    def test_goodman_soderberg_gerber(self):
        r = M.fatigue(100e6, 50e6, 200e6, 600e6, 400e6)["results"]
        self.assertAlmostEqual(r["n_goodman"], 1 / (0.5 + 50 / 600))
        self.assertAlmostEqual(r["n_soderberg"], 1 / (0.5 + 50 / 400))
        self.assertLess(r["n_soderberg"], r["n_goodman"])
        self.assertGreater(r["n_gerber"], r["n_goodman"])
        n = r["n_gerber"]
        self.assertAlmostEqual(n * 100 / 200 + (n * 50 / 600) ** 2, 1.0, places=12)
        self.assertAlmostEqual(M.fatigue(100e6, 0, 200e6, 600e6, 400e6)["results"]["n_goodman"], 2.0)

    def test_finite_life(self):
        r = M.finite_life(300e6, 245e6, 490e6)["results"]
        self.assertAlmostEqual(r["f"], 0.896, places=3)                     # Shigley fig. 6-18: f ~ 0.9 at 70 kpsi
        S1000 = r["a_Pa"] * 1000 ** r["b"]
        self.assertAlmostEqual(S1000, r["f"] * 490e6, delta=1)
        self.assertAlmostEqual(r["a_Pa"] * 1e6 ** r["b"], 245e6, delta=1)
        self.assertTrue(1e3 < r["cycles"] < 1e6)
        self.assertEqual(M.finite_life(200e6, 245e6, 490e6)["results"]["cycles"], math.inf)

    def test_shaft_sizing_round_trips(self):
        s = M.shaft(Ma=70, Mm=0, Ta=0, Tm=45, Sut=700e6, Sy=560e6, n=1.5, Kf=1.58, Kfs=1.39)["results"]
        c = M.shaft(Ma=70, Mm=0, Ta=0, Tm=45, Sut=700e6, Sy=560e6, Kf=1.58, Kfs=1.39, d=s["diameter_m"])["results"]
        self.assertAlmostEqual(c["n_fatigue_DE_Goodman"], 1.5, places=6)
        bigger = M.shaft(Ma=70, Mm=0, Ta=0, Tm=45, Sut=700e6, Sy=560e6, Kf=1.58, Kfs=1.39, d=s["diameter_m"] * 1.2)["results"]
        self.assertGreater(bigger["n_fatigue_DE_Goodman"], 1.5)

    def test_bolted_joint(self):
        self.assertAlmostEqual(M.tensile_stress_area(0.010, 0.0015) * 1e6, 57.99, places=2)   # ISO 898-1: 58.0 mm^2
        self.assertAlmostEqual(M.tensile_stress_area(0.012, 0.00175) * 1e6, 84.27, places=2)  # ISO: 84.3 mm^2
        r = M.bolted_joint(0.012, 0.00175, 0.03, 5000, "8.8")["results"]
        self.assertAlmostEqual(r["preload_N"], 0.75 * r["tensile_stress_area_m2"] * 580e6, places=6)
        self.assertTrue(0 < r["joint_constant_C"] < 0.5)
        self.assertAlmostEqual(r["bolt_load_N"], r["joint_constant_C"] * 5000 + r["preload_N"], places=6)
        self.assertGreater(r["n_separation"], 1)
        weak = M.bolted_joint(0.006, 0.001, 0.03, 20000, "8.8")
        self.assertTrue(any("separates" in w or "overloaded" in w for w in weak["warnings"]))


class Optimisation(unittest.TestCase):
    def test_cantilever_sweep_pareto_front_is_non_dominated(self):
        r = O.cantilever_section(0.5, 200, "aluminium_6061_t6", "rectangle", min_safety_factor=3, max_deflection=0.002)
        front = r["pareto_front"]
        for a in front:
            for b in r["candidates"]:
                self.assertFalse(b["mass_kg"] < a["mass_kg"] and b["safety_factor"] > a["safety_factor"])
        self.assertTrue(r["best"]["feasible"])
        self.assertEqual(r["best"]["mass_kg"], min(c["mass_kg"] for c in r["feasible"]))
        for c in r["candidates"]:
            if not c["feasible"]:
                self.assertTrue(c["violations"])

    def test_truss_sizing_mass_and_safety_scale_with_area(self):
        nodes = {"A": [0, 0], "B": [1, 1], "C": [2, 0]}
        r = O.truss_sizing(nodes, [["A", "B"], ["B", "C"], ["A", "C"]], {"A": "pin", "C": "roller"}, {"B": [0, -5000]},
                           areas=[2e-5, 5e-5, 1e-4, 2e-4])
        masses = [c["mass_kg"] for c in r["candidates"]]
        self.assertEqual(masses, sorted(masses))
        self.assertEqual([c["n_yield"] for c in r["candidates"]], sorted(c["n_yield"] for c in r["candidates"]))
        self.assertTrue(any("buckling" in v for c in r["candidates"] for v in c["violations"]))


if __name__ == "__main__":
    unittest.main()
