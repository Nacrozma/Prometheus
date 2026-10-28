"""Known-answer tests for engineering.py.

Expected values come from textbook formulas worked by hand or published reference values
(ISA tables, standard orbital figures), not from running the code under test.
"""
import math
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import engineering as eng  # noqa: E402


def ok(name, **kw):
    r = eng.calculate(name, **kw)
    assert r["status"] == "success", r
    return r["results"]


class Units(unittest.TestCase):
    def test_conversions(self):
        self.assertAlmostEqual(ok("convert_units", value=1, from_unit="in", to_unit="mm")["value"], 25.4)
        self.assertAlmostEqual(ok("convert_units", value=1, from_unit="psi", to_unit="kPa")["value"], 6.894757, places=5)
        self.assertAlmostEqual(ok("convert_units", value=100, from_unit="km/h", to_unit="mph")["value"], 62.1371, places=3)
        self.assertAlmostEqual(ok("convert_units", value=9.4, from_unit="kg cm", to_unit="Nm")["value"], 0.92183, places=4)
        self.assertAlmostEqual(ok("convert_units", value=100, from_unit="C", to_unit="F")["value"], 212.0)
        self.assertAlmostEqual(ok("convert_units", value=-40, from_unit="F", to_unit="C")["value"], -40.0)
        self.assertAlmostEqual(ok("convert_units", value=180, from_unit="deg", to_unit="rad")["value"], math.pi)

    def test_mismatched_quantities_and_nonsense_are_errors(self):
        for kw in ({"value": 1, "from_unit": "m", "to_unit": "kg"}, {"value": 1, "from_unit": "m", "to_unit": "parsec"},
                   {"value": -300, "from_unit": "C", "to_unit": "K"}, {"value": float("nan"), "from_unit": "m", "to_unit": "mm"}):
            self.assertEqual(eng.calculate("convert_units", **kw)["status"], "error", kw)


class Sections(unittest.TestCase):
    def test_rectangle_and_circle(self):
        r = ok("section_properties", shape="rectangle", b=0.05, h=0.10)
        self.assertAlmostEqual(r["I_m4"], 4.1667e-6, places=9)                 # bh^3/12
        self.assertAlmostEqual(r["section_modulus_m3"], 8.3333e-5, places=8)
        c = ok("section_properties", shape="circle", d=0.02)
        self.assertAlmostEqual(c["I_m4"], 7.854e-9, places=12)                 # pi d^4/64
        self.assertAlmostEqual(c["J_m4"], 2 * c["I_m4"])

    def test_hollow_reduces_to_solid_and_validates(self):
        solid = ok("section_properties", shape="circle", d=0.03)["I_m4"]
        self.assertAlmostEqual(ok("section_properties", shape="hollow_circle", d_outer=0.03, d_inner=0)["I_m4"], solid)
        self.assertEqual(eng.calculate("section_properties", shape="hollow_circle", d_outer=0.02, d_inner=0.03)["status"], "error")


class Beams(unittest.TestCase):
    E, I, L = 200e9, 4.1667e-6, 2.0          # steel, 50x100 mm section

    def test_simply_supported_midspan_point_load(self):
        r = ok("beam", support="simply_supported", load="point", length=self.L, magnitude=10000, E=self.E, I=self.I)
        self.assertAlmostEqual(r["max_moment_Nm"], 5000.0)                     # PL/4
        self.assertAlmostEqual(r["reaction_left_N"], 5000.0)
        self.assertAlmostEqual(r["max_deflection_m"], 10000 * 8 / (48 * self.E * self.I), places=9)   # PL^3/48EI = 2.0 mm
        self.assertAlmostEqual(r["max_deflection_m"] * 1000, 2.0, places=2)

    def test_off_centre_load(self):
        r = ok("beam", support="simply_supported", load="point", length=4.0, magnitude=12000, E=self.E, I=self.I, position=1.0)
        self.assertAlmostEqual(r["reaction_left_N"], 9000.0)                    # P b / L
        self.assertAlmostEqual(r["reaction_right_N"], 3000.0)
        self.assertAlmostEqual(r["max_moment_Nm"], 9000.0)                      # P a b / L
        self.assertGreaterEqual(r["max_deflection_m"], r["deflection_under_load_m"])
        centre = ok("beam", support="simply_supported", load="point", length=4.0, magnitude=12000, E=self.E, I=self.I)
        self.assertGreater(centre["max_deflection_m"], r["max_deflection_m"])   # off-centre loads deflect less

    def test_midspan_formula_is_the_special_case_of_the_general_one(self):
        r = ok("beam", support="simply_supported", load="point", length=3.0, magnitude=500, E=70e9, I=1e-6)
        self.assertAlmostEqual(r["max_deflection_m"], r["deflection_under_load_m"], places=12)

    def test_udl(self):
        r = ok("beam", support="simply_supported", load="udl", length=self.L, magnitude=5000, E=self.E, I=self.I)
        self.assertAlmostEqual(r["max_moment_Nm"], 2500.0)                      # wL^2/8
        self.assertAlmostEqual(r["max_deflection_m"], 5 * 5000 * 16 / (384 * self.E * self.I), places=9)

    def test_cantilevers(self):
        p = ok("beam", support="cantilever", load="point", length=1.5, magnitude=200, E=70e9, I=2e-8)
        self.assertAlmostEqual(p["max_moment_Nm"], 300.0)
        self.assertAlmostEqual(p["max_deflection_m"], 200 * 1.5 ** 3 / (3 * 70e9 * 2e-8), places=9)
        u = ok("beam", support="cantilever", load="udl", length=1.5, magnitude=100, E=70e9, I=2e-8)
        self.assertAlmostEqual(u["max_moment_Nm"], 100 * 1.5 ** 2 / 2)
        self.assertAlmostEqual(u["max_deflection_m"], 100 * 1.5 ** 4 / (8 * 70e9 * 2e-8), places=9)
        mid = ok("beam", support="cantilever", load="point", length=2.0, magnitude=100, E=70e9, I=1e-7, position=1.0)
        self.assertAlmostEqual(mid["max_deflection_m"], 100 * 1 * (6 - 1) / (6 * 70e9 * 1e-7), places=9)   # Pa^2(3L-a)/6EI

    def test_flexible_beam_is_flagged(self):
        r = eng.calculate("beam", support="cantilever", load="point", length=1.0, magnitude=1000, E=70e9, I=1e-9)
        self.assertTrue(r["warnings"])

    def test_bad_input(self):
        self.assertEqual(eng.calculate("beam", support="simply_supported", load="point", length=1, magnitude=1, E=1e9, I=1e-6, position=1.5)["status"], "error")
        self.assertEqual(eng.calculate("beam", support="floating", load="point", length=1, magnitude=1, E=1e9, I=1e-6)["status"], "error")
        self.assertEqual(eng.calculate("beam", support="cantilever", load="udl", length=-1, magnitude=1, E=1e9, I=1e-6)["status"], "error")


class Strength(unittest.TestCase):
    def test_bending_stress_and_safety_factor(self):
        self.assertAlmostEqual(ok("bending_stress", moment=5000, I=4.1667e-6, c=0.05)["sigma_Pa"] / 1e6, 60.0, places=1)
        self.assertAlmostEqual(ok("safety_factor", strength=250e6, stress=100e6)["factor_of_safety"], 2.5)
        self.assertTrue(eng.calculate("safety_factor", strength=100, stress=200)["warnings"])

    def test_torsion(self):
        r = ok("torsion_shear", torque=100, d=0.02)                             # 16 T /(pi d^3) = 63.66 MPa
        self.assertAlmostEqual(r["tau_max_Pa"] / 1e6, 63.66, places=2)

    def test_euler_buckling(self):
        pcr = ok("euler_buckling", E=200e9, I=8.333e-9, length=1.0)["critical_load_N"]
        self.assertAlmostEqual(pcr, math.pi ** 2 * 200e9 * 8.333e-9, delta=1)
        fixed_free = ok("euler_buckling", E=200e9, I=8.333e-9, length=1.0, end_condition="fixed_free")["critical_load_N"]
        self.assertAlmostEqual(fixed_free, pcr / 4, delta=1)                    # K = 2 -> a quarter

    def test_plane_stress_textbook_example(self):
        r = ok("plane_stress", sigma_x=80e6, sigma_y=-40e6, tau_xy=30e6)       # centre 20, R = sqrt(60^2+30^2)=67.08
        self.assertAlmostEqual(r["sigma_1_Pa"] / 1e6, 87.08, places=2)
        self.assertAlmostEqual(r["sigma_2_Pa"] / 1e6, -47.08, places=2)
        self.assertAlmostEqual(r["tau_max_Pa"] / 1e6, 67.08, places=2)
        pure_shear = ok("plane_stress", sigma_x=0, sigma_y=0, tau_xy=50e6)
        self.assertAlmostEqual(pure_shear["von_mises_Pa"] / 1e6, 50 * math.sqrt(3), places=3)
        uniaxial = ok("plane_stress", sigma_x=100e6, sigma_y=0, tau_xy=0)
        self.assertAlmostEqual(uniaxial["von_mises_Pa"], 100e6)

    def test_thermal_expansion(self):
        self.assertAlmostEqual(ok("thermal_expansion", length=10, alpha=12e-6, delta_T=50)["delta_L_m"], 0.006)    # steel rail


class Trusses(unittest.TestCase):
    def test_triangle_truss(self):
        r = ok("truss", nodes={"A": [0, 0], "B": [4, 0], "C": [2, 3]}, members=[["A", "B"], ["A", "C"], ["B", "C"]],
               supports={"A": "pin", "B": "roller"}, loads={"C": [0, -10000]})
        self.assertAlmostEqual(r["reactions_N"]["A.Ry"], 5000.0, places=6)
        self.assertAlmostEqual(r["reactions_N"]["B.Ry"], 5000.0, places=6)
        self.assertAlmostEqual(r["reactions_N"]["A.Rx"], 0.0, places=6)
        # joint A: Fac*3/sqrt(13) = -5000 -> compression 6009.25; Fab = 6009.25*2/sqrt(13) = 3333.33 tension
        self.assertAlmostEqual(r["member_forces_N"]["A-C"], -6009.252, places=2)
        self.assertAlmostEqual(r["member_forces_N"]["B-C"], -6009.252, places=2)
        self.assertAlmostEqual(r["member_forces_N"]["A-B"], 3333.333, places=2)
        self.assertEqual(r["member_state"]["A-B"], "tension")
        self.assertEqual(r["member_state"]["A-C"], "compression")

    def test_horizontal_load_and_zero_force_member(self):
        # two-bar frame: pin at A, roller at B... a load along the bar axis
        r = ok("truss", nodes={"A": [0, 0], "B": [3, 0], "C": [3, 4]}, members=[["A", "B"], ["B", "C"], ["A", "C"]],
               supports={"A": "pin", "B": "roller"}, loads={"C": [1000, 0]})
        self.assertAlmostEqual(r["reactions_N"]["A.Rx"], -1000.0, places=6)
        self.assertAlmostEqual(r["reactions_N"]["A.Ry"] + r["reactions_N"]["B.Ry"], 0.0, places=6)
        # 3-4-5 triangle. Joint C: AC's horizontal component (3/5) must balance 1000 N -> AC = 1666.67 N tension;
        # its vertical component (4/5 x 1666.67 = 1333.33) is balanced by BC in compression; joint A then needs no AB force.
        self.assertAlmostEqual(r["member_forces_N"]["A-C"], 1666.667, places=2)
        self.assertAlmostEqual(r["member_forces_N"]["B-C"], -1333.333, places=2)
        self.assertEqual(r["member_state"]["A-B"], "zero-force")
        self.assertAlmostEqual(r["reactions_N"]["B.Ry"], 1333.333, places=2)

    def test_global_equilibrium_holds(self):
        loads = {"C": [300.0, -800.0], "D": [0.0, -200.0]}
        r = ok("truss", nodes={"A": [0, 0], "B": [6, 0], "C": [2, 2], "D": [4, 2]},
               members=[["A", "C"], ["C", "D"], ["D", "B"], ["A", "D"], ["C", "B"]], supports={"A": "pin", "B": "roller"}, loads=loads)
        rx = sum(v for k, v in r["reactions_N"].items() if k.endswith("Rx"))
        ry = sum(v for k, v in r["reactions_N"].items() if k.endswith("Ry"))
        self.assertAlmostEqual(rx + sum(l[0] for l in loads.values()), 0.0, places=6)
        self.assertAlmostEqual(ry + sum(l[1] for l in loads.values()), 0.0, places=6)
        moment_about_A = 6 * r["reactions_N"]["B.Ry"] + sum(x * l[1] - y * l[0] for (x, y), l in ((( 2, 2), loads["C"]), ((4, 2), loads["D"])))
        self.assertAlmostEqual(moment_about_A, 0.0, places=5)

    def test_indeterminate_and_unstable_structures_are_refused(self):
        extra = eng.calculate("truss", nodes={"A": [0, 0], "B": [4, 0], "C": [2, 3]}, members=[["A", "B"], ["A", "C"], ["B", "C"]],
                              supports={"A": "pin", "B": "pin"}, loads={"C": [0, -1]})
        self.assertEqual(extra["status"], "error")
        self.assertIn("determinate", extra["message"])
        mech = eng.calculate("truss", nodes={"A": [0, 0], "B": [4, 0], "C": [2, 3]}, members=[["A", "B"], ["A", "C"], ["B", "C"]],
                             supports={"A": "roller", "B": "roller", "C": "roller"}, loads={"C": [0, -1]})
        self.assertEqual(mech["status"], "error")                                  # three parallel reactions cannot stop sideways motion
        self.assertIn("unstable", mech["message"])
        stable = eng.calculate("truss", nodes={"A": [0, 0], "B": [4, 0], "C": [2, 3]}, members=[["A", "B"], ["A", "C"], ["B", "C"]],
                               supports={"A": "roller", "B": "roller", "C": "roller_x"}, loads={"C": [0, -1]})
        self.assertEqual(stable["status"], "success")                               # vertical + vertical + horizontal does restrain it
        self.assertEqual(eng.calculate("truss", nodes={"A": [0, 0], "B": [0, 0]}, members=[["A", "B"]], supports={"A": "pin", "B": "roller"}, loads={})["status"], "error")


class Atmosphere(unittest.TestCase):
    def test_isa_reference_values(self):
        s = ok("isa_atmosphere", altitude_m=0)
        self.assertAlmostEqual(s["temperature_K"], 288.15)
        self.assertAlmostEqual(s["pressure_Pa"], 101325.0, places=1)
        self.assertAlmostEqual(s["density_kg_m3"], 1.225, places=3)
        self.assertAlmostEqual(s["speed_of_sound_m_s"], 340.29, places=1)
        self.assertAlmostEqual(s["dynamic_viscosity_Pa_s"], 1.789e-5, delta=2e-8)
        t = ok("isa_atmosphere", altitude_m=11000)                              # tropopause
        self.assertAlmostEqual(t["temperature_K"], 216.65)
        self.assertAlmostEqual(t["pressure_Pa"], 22632, delta=15)
        self.assertAlmostEqual(t["density_kg_m3"], 0.3639, places=3)
        h = ok("isa_atmosphere", altitude_m=5000)
        self.assertAlmostEqual(h["pressure_Pa"], 54020, delta=100)
        self.assertAlmostEqual(h["density_kg_m3"], 0.7364, places=3)
        top = ok("isa_atmosphere", altitude_m=20000)
        self.assertAlmostEqual(top["pressure_Pa"], 5475, delta=15)

    def test_out_of_range_is_refused(self):
        self.assertEqual(eng.calculate("isa_atmosphere", altitude_m=30000)["status"], "error")
        self.assertEqual(eng.calculate("isa_atmosphere", altitude_m=-5)["status"], "error")

    def test_continuity_at_the_tropopause(self):
        a, b = ok("isa_atmosphere", altitude_m=10999.9), ok("isa_atmosphere", altitude_m=11000.1)
        self.assertAlmostEqual(a["pressure_Pa"] / b["pressure_Pa"], 1.0, places=4)

    def test_flight(self):
        self.assertAlmostEqual(ok("lift", density=1.225, speed=50, area=16.2, cl=1.0)["lift_N"], 24806.25, places=2)
        # a Cessna-172-like aircraft: W = 10.7 kN, S = 16.2 m^2, CLmax 1.6 -> about 23.4 m/s at sea level
        self.assertAlmostEqual(ok("stall_speed", weight_N=10700, density=1.225, area=16.2, cl_max=1.6)["stall_speed_m_s"], 25.9, delta=0.2)
        self.assertAlmostEqual(ok("reynolds_number", density=1.225, speed=50, length=1.5, viscosity=1.789e-5)["reynolds"], 5.135e6, delta=2e4)


class Orbits(unittest.TestCase):
    def test_iss_like_orbit(self):
        r = ok("circular_orbit", altitude_m=400e3)
        self.assertAlmostEqual(r["speed_m_s"], 7668.6, delta=5)                 # ~7.67 km/s
        self.assertAlmostEqual(r["period_s"] / 60, 92.4, delta=0.3)             # ~92 min
        self.assertAlmostEqual(r["escape_speed_m_s"] / r["speed_m_s"], math.sqrt(2))

    def test_geostationary_orbit(self):
        r = ok("circular_orbit", altitude_m=35786e3)
        self.assertAlmostEqual(r["period_s"] / 3600, 23.934, delta=0.02)        # one sidereal day
        self.assertAlmostEqual(r["speed_m_s"], 3074.7, delta=3)

    def test_earth_surface_escape_speed_and_moon(self):
        # 11.186 km/s is quoted for Earth's mean radius (6371 km); this uses the 6378 km equatorial radius -> 11.180
        self.assertAlmostEqual(ok("circular_orbit", altitude_m=0)["escape_speed_m_s"], 11180, delta=5)
        self.assertAlmostEqual(ok("circular_orbit", altitude_m=0, body="moon")["escape_speed_m_s"], 2380, delta=10)

    def test_hohmann_leo_to_geo(self):
        r = ok("hohmann", altitude_1_m=300e3, altitude_2_m=35786e3)             # the standard textbook case
        self.assertAlmostEqual(r["delta_v1_m_s"], 2426, delta=15)
        self.assertAlmostEqual(r["delta_v2_m_s"], 1467, delta=15)
        self.assertAlmostEqual(r["total_delta_v_m_s"], 3893, delta=25)
        self.assertAlmostEqual(r["transfer_time_s"] / 3600, 5.27, delta=0.05)

    def test_hohmann_is_symmetric_in_total_delta_v(self):
        up = ok("hohmann", altitude_1_m=500e3, altitude_2_m=20000e3)["total_delta_v_m_s"]
        down = ok("hohmann", altitude_1_m=20000e3, altitude_2_m=500e3)["total_delta_v_m_s"]
        self.assertAlmostEqual(up, down, places=6)

    def test_vis_viva_reduces_to_circular_speed(self):
        r = 7000e3
        self.assertAlmostEqual(ok("vis_viva", radius_m=r, semi_major_axis_m=r)["speed_m_s"],
                               ok("circular_orbit", altitude_m=r - 6378137.0)["speed_m_s"], places=6)
        self.assertEqual(eng.calculate("vis_viva", radius_m=2e7, semi_major_axis_m=5e6)["status"], "error")

    def test_rocket_equation(self):
        r = ok("rocket_equation", isp_s=300, mass_initial_kg=5000, mass_final_kg=1000)
        self.assertAlmostEqual(r["delta_v_m_s"], 300 * 9.80665 * math.log(5), places=6)       # ~4735 m/s
        self.assertAlmostEqual(r["delta_v_m_s"], 4735, delta=1)
        self.assertAlmostEqual(r["propellant_fraction"], 0.8)
        back = ok("rocket_equation", isp_s=300, delta_v_m_s=r["delta_v_m_s"])
        self.assertAlmostEqual(back["mass_ratio"], 5.0, places=6)
        self.assertEqual(eng.calculate("rocket_equation", isp_s=300, mass_initial_kg=100, mass_final_kg=200)["status"], "error")


class Interface(unittest.TestCase):
    def test_calculate_never_raises(self):
        self.assertEqual(eng.calculate("nope")["status"], "error")
        self.assertEqual(eng.calculate("beam")["status"], "error")                         # missing params
        self.assertEqual(eng.calculate("lift", density="x", speed=1, area=1, cl=1)["status"], "error")
        self.assertEqual(eng.calculate("lift", density=True, speed=1, area=1, cl=1)["status"], "error")
        self.assertEqual(eng.calculate("isa_atmosphere", altitude_m=float("inf"))["status"], "error")
        self.assertEqual(eng.calculate("circular_orbit", altitude_m=1e300)["status"] in ("error", "success"), True)

    def test_every_result_documents_itself(self):
        r = eng.calculate("hohmann", altitude_1_m=300e3, altitude_2_m=35786e3)
        for key in ("formula", "assumptions", "inputs", "warnings"):
            self.assertIn(key, r)

    def test_catalog_lists_everything(self):
        text = eng.catalog()
        for name in eng.CALCULATIONS:
            self.assertIn(name, text)


if __name__ == "__main__":
    unittest.main()
