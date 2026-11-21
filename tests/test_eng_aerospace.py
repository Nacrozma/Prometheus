"""Aerospace models against published reference values and analytic solutions.

References: U.S. Standard Atmosphere 1976 (NOAA/NASA/USAF) layer base values; NACA Report 1135 / Anderson,
"Modern Compressible Flow", for isentropic, normal-shock, oblique-shock and Prandtl-Meyer values at gamma = 1.4;
Sutton & Biblarz, "Rocket Propulsion Elements", for the ideal thrust coefficient; textbook projectile and
rocket-equation solutions for the trajectory integrator.
"""
import math
import os
import sys
import unittest

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from eng import EngError, atmosphere as A, compressible as C, control as K, propulsion as P, trajectory as T  # noqa: E402


class Atmosphere(unittest.TestCase):
    def test_layer_base_pressures_match_the_1976_standard(self):
        published = [101325.0, 22632.06, 5474.889, 868.0187, 110.9063, 66.93887, 3.956420]
        for got, ref in zip(A.P_BASE, published):
            self.assertAlmostEqual(got / ref, 1.0, places=5)

    def test_tabulated_points(self):
        # geometric altitude -> (T [K], p [Pa], rho [kg/m^3]) from the 1976 tables
        table = {0: (288.15, 101325.0, 1.2250), 11000: (216.774, 22699.9, 0.36480), 20000: (216.650, 5529.3, 0.088910),
                 32000: (228.490, 889.06, 0.013555), 50000: (270.650, 79.779, 1.0269e-3), 86000: (186.946, 0.37338, 6.958e-6)}
        for h, (t, p, rho) in table.items():
            s = A.state(h)
            self.assertAlmostEqual(s["temperature_K"], t, delta=0.01, msg=h)
            self.assertAlmostEqual(s["pressure_Pa"] / p, 1.0, delta=2e-4, msg=h)
            self.assertAlmostEqual(s["density_kg_m3"] / rho, 1.0, delta=1e-3, msg=h)

    def test_continuity_and_range(self):
        for Hb, *_ in A.LAYERS[1:]:
            h = A.R0 * Hb / (A.R0 - Hb)                         # geometric altitude of the layer boundary
            lo, hi = A.state(h - 1e-3), A.state(h + 1e-3)
            self.assertAlmostEqual(lo["pressure_Pa"] / hi["pressure_Pa"], 1.0, places=6)
        with self.assertRaises(EngError):
            A.state(90000)
        with self.assertRaises(EngError):
            A.state(-10)


class Compressible(unittest.TestCase):
    def test_isentropic_m2(self):
        r = C.isentropic(2.0)["results"]
        self.assertAlmostEqual(r["p0_over_p"], 7.8244, places=4)
        self.assertAlmostEqual(r["T0_over_T"], 1.8, places=12)
        self.assertAlmostEqual(r["A_over_Astar"], 1.6875, places=12)
        self.assertAlmostEqual(r["mach_angle_deg"], 30.0, places=10)
        self.assertAlmostEqual(C.mach_from_area_ratio(1.6875), 2.0, places=9)
        self.assertAlmostEqual(C.mach_from_area_ratio(1.6875, supersonic=False), 0.3722, places=4)

    def test_normal_shock(self):
        r = C.normal_shock(2.0)["results"]
        self.assertAlmostEqual(r["M2"], 0.5774, places=4)
        self.assertAlmostEqual(r["p2_over_p1"], 4.5, places=12)
        self.assertAlmostEqual(r["rho2_over_rho1"], 2.6667, places=4)
        self.assertAlmostEqual(r["T2_over_T1"], 1.6875, places=12)
        self.assertAlmostEqual(r["p02_over_p01"], 0.7209, places=4)
        weak = C.normal_shock(1.0001)["results"]
        self.assertAlmostEqual(weak["M2"], 1.0, places=3)
        with self.assertRaises(EngError):
            C.normal_shock(0.9)

    def test_oblique_shock(self):
        r = C.oblique_shock(2.0, 10.0)["results"]
        self.assertAlmostEqual(r["beta_deg"], 39.31, places=2)
        self.assertAlmostEqual(r["M2"], 1.6405, places=3)
        self.assertAlmostEqual(r["p2_over_p1"], 1.7066, places=3)
        self.assertAlmostEqual(C.max_deflection(2.0)["theta_max_deg"], 22.97, places=2)
        strong = C.oblique_shock(2.0, 10.0, strong=True)["results"]
        self.assertGreater(strong["beta_deg"], r["beta_deg"])
        self.assertLess(strong["M2"], 1.0)
        with self.assertRaises(EngError) as ctx:
            C.oblique_shock(2.0, 25.0)
        self.assertIn("detaches", str(ctx.exception))

    def test_prandtl_meyer(self):
        self.assertAlmostEqual(C.prandtl_meyer(2.0), 26.3798, places=4)
        self.assertAlmostEqual(C.mach_from_prandtl_meyer(26.3798), 2.0, places=4)
        r = C.expansion_fan(2.0, 10.0)["results"]
        self.assertAlmostEqual(r["M2"], 2.3849, places=3)
        t1 = 1 + 0.2 * 4
        t2 = 1 + 0.2 * r["M2"] ** 2
        self.assertAlmostEqual(r["p2_over_p1"], (t1 / t2) ** 3.5, places=12)
        with self.assertRaises(EngError):
            C.mach_from_prandtl_meyer(131.0)                      # beyond nu_max = 130.45 deg


class Propulsion(unittest.TestCase):
    BASE = dict(pc=7e6, Tc=3300.0, gamma=1.2, molar_mass=0.022, throat_area=1e-3, expansion_ratio=20.0, pa=101325.0)

    def test_vacuum_cf_limit(self):
        self.assertAlmostEqual(P.cf_vacuum_limit(1.2), 2.2466, places=4)    # Sutton: CF -> 2.246 for gamma 1.2
        self.assertAlmostEqual(P.cf_vacuum_limit(1.4), 1.8116, places=4)
        r = P.nozzle(**{**self.BASE, "expansion_ratio": 400.0})["results"]
        self.assertLess(r["CF_vacuum"], P.cf_vacuum_limit(1.2))

    def test_internal_consistency(self):
        r = P.nozzle(**self.BASE)["results"]
        g, R, Tc = 1.2, P.RU / 0.022, 3300.0
        cstar = math.sqrt(g * R * Tc) / (g * math.sqrt((2 / 2.2) ** (2.2 / 0.2)))
        self.assertAlmostEqual(r["cstar_ideal_m_s"], cstar, places=9)
        self.assertAlmostEqual(r["mass_flow_kg_s"], 7e6 * 1e-3 / cstar, places=9)
        # thrust = momentum flux + pressure thrust (independent route)
        Ae = 20.0 * 1e-3
        F_alt = r["mass_flow_kg_s"] * r["exhaust_velocity_ideal_m_s"] + (r["exit_pressure_Pa"] - 101325.0) * Ae
        self.assertAlmostEqual(r["thrust_sea_level_N"] / F_alt, 1.0, places=9)
        self.assertAlmostEqual(r["isp_vacuum_s"], r["CF_vacuum"] * r["cstar_m_s"] / P.G0, places=9)
        self.assertGreater(r["isp_vacuum_s"], r["isp_sea_level_s"])

    def test_efficiencies_and_warnings(self):
        ideal = P.nozzle(**self.BASE)["results"]
        real = P.nozzle(**{**self.BASE, "eta_cstar": 0.95, "eta_cf": 0.97})["results"]
        self.assertAlmostEqual(real["isp_vacuum_s"] / ideal["isp_vacuum_s"], 0.95 * 0.97, places=9)
        over = P.nozzle(**{**self.BASE, "pc": 1e6, "expansion_ratio": 60.0})
        self.assertTrue(any("separates" in w for w in over["warnings"]))
        s = P.sensitivity(self.BASE)
        self.assertGreater(s["Tc"], 0.4)                        # Isp ~ sqrt(Tc): d ln Isp / d ln Tc ~ 0.5
        self.assertLess(s["molar_mass"], -0.4)
        with self.assertRaises(EngError):
            P.nozzle(**{**self.BASE, "expansion_ratio": 0.5})


class Trajectory(unittest.TestCase):
    def test_vacuum_projectile_matches_the_parabola(self):
        r = T.simulate(T.Vehicle(10.0), T.Programme("ballistic", gamma0_deg=45, V0_m_s=100), dt=0.01, flat=True, aero=False)["summary"]
        self.assertAlmostEqual(r["apogee_m"], 100 ** 2 * 0.5 / (2 * T.G0), places=5)
        self.assertAlmostEqual(r["impact"]["downrange_m"], 100 ** 2 / T.G0, delta=1e-4)
        self.assertAlmostEqual(r["impact"]["time_s"], 200 * math.sin(math.radians(45)) / T.G0, places=5)

    def test_vertical_burn_matches_the_rocket_equation_with_gravity_loss(self):
        v = T.Vehicle(100.0, propellant_kg=60, thrust_vac_N=3000, isp_vac_s=200)
        s = T.simulate(v, T.Programme("gravity_turn", kick_time_s=1e9), dt=0.05, flat=True, aero=False, t_max=v.burn_time)
        d = s["data"]
        t, ve, mdot = d["t"][-1], 200 * T.G0, v.mdot
        m = 100 - mdot * t
        self.assertAlmostEqual(t, v.burn_time, places=9)
        self.assertAlmostEqual(d["V"][-1], ve * math.log(100 / m) - T.G0 * t, places=6)
        self.assertAlmostEqual(d["h"][-1], ve * (m / mdot * math.log(m / 100) + t) - T.G0 * t * t / 2, places=5)

    def test_energy_is_conserved_in_a_vacuum_coast_with_spherical_gravity(self):
        s = T.simulate(T.Vehicle(10.0), T.Programme("ballistic", gamma0_deg=60, V0_m_s=3000), dt=0.1, aero=False)
        d = s["data"]
        mu = T.G0 * T.RE ** 2
        E = d["V"] ** 2 / 2 - mu / (T.RE + d["h"])
        self.assertLess(np.max(np.abs(E - E[0])) / abs(E[0]), 1e-9)

    def test_rk4_converges_at_fourth_order(self):
        v = T.Vehicle(50.0, propellant_kg=25, thrust_vac_N=4000, isp_vac_s=220)
        conv = T.convergence(v, T.Programme("gravity_turn", kick_time_s=3, kick_angle_deg=4), dts=(0.2, 0.1, 0.05), flat=True, aero=False)
        self.assertGreater(conv["observed_order"][0], 3.5)
        self.assertLess(conv["observed_order"][0], 4.5)

    def test_drag_lowers_the_apogee_and_max_q_is_reported(self):
        base = dict(mass_initial_kg=50.0, propellant_kg=25, thrust_vac_N=4000, isp_vac_s=220, ref_area_m2=0.0177)
        prog = T.Programme("gravity_turn", kick_time_s=3, kick_angle_deg=4)
        vac = T.simulate(T.Vehicle(**base), prog, dt=0.05, aero=False)["summary"]
        air = T.simulate(T.Vehicle(**base, cd0=0.45), prog, dt=0.05)["summary"]
        self.assertLess(air["apogee_m"], vac["apogee_m"])
        self.assertGreater(air["max_q_Pa"], 0)
        self.assertIsNotNone(air["impact"])

    def test_invalid_vehicles_are_refused(self):
        with self.assertRaises(EngError):
            T.simulate(T.Vehicle(10.0, propellant_kg=12), T.Programme())
        with self.assertRaises(EngError):
            T.simulate(T.Vehicle(100.0, propellant_kg=10, thrust_vac_N=500), T.Programme())    # thrust below weight


class Control(unittest.TestCase):
    def test_state_feedback_matches_second_order_theory(self):
        g = K.place(0.05, 6.0, 0.7)
        r = K.simulate(K.Plant("attitude", 0.05, u_max=50), K.Controller("state", Kp=g["Kp"], Kd=g["Kd"], Ts=0.001), K.Scenario(0.2, 4))
        self.assertAlmostEqual(r["metrics"]["overshoot_pct"], 100 * math.exp(-0.7 * math.pi / math.sqrt(1 - 0.49)), delta=0.05)
        self.assertAlmostEqual(r["metrics"]["steady_state_error"], 0.0, places=6)
        self.assertTrue(r["stability"]["discrete_stable"])

    def test_discrete_poles_match_the_continuous_design(self):
        g = K.place(0.05, 6.0, 0.7)
        st = K.stability(K.Plant("attitude", 0.05), K.Controller("state", Kp=g["Kp"], Kd=g["Kd"], Ts=0.001))
        z = max(st["eigenvalues"], key=lambda v: abs(v))
        s = complex(-0.7 * 6, 6 * math.sqrt(1 - 0.49))
        # the sampled loop holds u for Ts, so its poles differ from exp(s Ts) by O(wn Ts): 1e-5 here
        self.assertLess(abs(abs(z) - abs(np.exp(s * 0.001))), 2e-5)

    def test_routh_and_discrete_stability_agree_on_a_bad_pid(self):
        bad = K.Controller("pid", Kp=0.8, Ki=5.0, Kd=0.01, Ts=0.01)
        st = K.stability(K.Plant("attitude", 0.05), bad)
        self.assertFalse(st["routh_hurwitz_continuous"]["stable"])
        self.assertFalse(st["discrete_stable"])
        with self.assertRaises(EngError):
            K.simulate(K.Plant("attitude", 0.05, u_max=1e6), bad, K.Scenario(0.2, 30))

    def test_delay_degrades_and_eventually_destabilises(self):
        p = K.Plant("attitude", 0.05, u_max=10)
        c = K.Controller("pid", Kp=0.8, Ki=0.2, Kd=0.15, Tf=0.01, Ts=0.01)
        rho = [K.stability(p, c, d)["spectral_radius"] for d in (0, 20, 40)]
        self.assertLess(rho[0], rho[1])                           # (at very small delays the slow pole barely moves)
        self.assertLess(rho[1], rho[2])
        self.assertFalse(K.stability(p, c, 40)["discrete_stable"])

    def test_saturation_rate_limit_noise_and_disturbance(self):
        p = K.Plant("attitude", 0.05, u_max=0.1, rate_limit=2.0)
        c = K.Controller("pid", Kp=0.8, Ki=0.4, Kd=0.15, Tf=0.01, Ts=0.01)
        r = K.simulate(p, c, K.Scenario(0.2, 8, noise_std=0.001, disturbance=0.02, disturbance_time=5.0))
        self.assertLessEqual(r["metrics"]["peak_control"], 0.1 + 1e-12)
        self.assertLessEqual(np.max(np.abs(np.diff(r["u"]))), 2.0 * 0.01 + 1e-12)
        self.assertGreater(r["metrics"]["disturbance_peak_deviation"], 0)
        a = K.simulate(p, c, K.Scenario(0.2, 3, noise_std=0.001, seed=7))["y"]
        b = K.simulate(p, c, K.Scenario(0.2, 3, noise_std=0.001, seed=7))["y"]
        self.assertTrue(np.array_equal(a, b))                     # reproducible

    def test_altitude_hold_respects_thrust_limits(self):
        r = K.simulate(K.Plant("altitude", 1.5, 30), K.Controller("pid", Kp=12, Ki=3, Kd=6, Ts=0.02), K.Scenario(1.0, 15))
        self.assertGreaterEqual(np.min(r["u"]), -1e-9)
        self.assertLessEqual(np.max(r["u"]), 30 + 1e-9)
        self.assertLess(abs(r["metrics"]["steady_state_error"]), 0.05)


if __name__ == "__main__":
    unittest.main()
