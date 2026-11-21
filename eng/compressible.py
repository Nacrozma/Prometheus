"""Compressible flow of a calorically perfect gas (constant gamma; default 1.4 for air).

Isentropic:   T0/T = 1 + (g-1)/2 M^2,  p0/p = (T0/T)^(g/(g-1)),  rho0/rho = (T0/T)^(1/(g-1))
              A/A* = (1/M) [ (2/(g+1)) (1 + (g-1)/2 M^2) ]^((g+1)/(2(g-1))),   Mach angle mu = asin(1/M)
Normal shock: M2^2 = (1 + (g-1)/2 M1^2) / (g M1^2 - (g-1)/2)
              p2/p1 = 1 + 2g/(g+1) (M1^2 - 1),  rho2/rho1 = (g+1) M1^2 / ((g-1) M1^2 + 2),  T2/T1 = (p2/p1)/(rho2/rho1)
              p02/p01 from the isentropic stagnation ratios across the shock
Oblique:      tan(theta) = 2 cot(beta) (M1^2 sin^2 beta - 1) / (M1^2 (g + cos 2beta) + 2); normal-shock relations on
              Mn1 = M1 sin(beta); M2 = Mn2 / sin(beta - theta). Weak and strong solutions; detached if theta > theta_max.
Prandtl-Meyer: nu(M) = sqrt((g+1)/(g-1)) atan(sqrt((g-1)/(g+1)(M^2-1))) - atan(sqrt(M^2-1)); an expansion through
              angle theta gives nu(M2) = nu(M1) + theta, isentropic (p0, T0 constant).

Assumptions everywhere: steady, adiabatic, inviscid, one-dimensional (or two-dimensional planar for oblique waves),
calorically perfect gas. High-temperature effects (vibrational excitation, dissociation) are not modelled: above
roughly Mach 5 in air, real-gas results differ.
"""
import math
from typing import Dict

from . import EngError
from ._util import num, result

ASSUME = ["steady, adiabatic, inviscid", "calorically perfect gas (constant gamma)", "no real-gas effects (reliable below ~Mach 5 for air)"]


def _g(gamma) -> float:
    return num("gamma", gamma, lo=1.0001, hi=1.7)


def _bisect(f, lo, hi, tol=1e-13, n=300):
    flo = f(lo)
    for _ in range(n):
        mid = 0.5 * (lo + hi)
        fm = f(mid)
        if (fm > 0) == (flo > 0):
            lo, flo = mid, fm
        else:
            hi = mid
        if hi - lo < tol:
            break
    return 0.5 * (lo + hi)


def area_ratio(M: float, gamma: float = 1.4) -> float:
    g = _g(gamma)
    return (1 / M) * ((2 / (g + 1)) * (1 + (g - 1) / 2 * M * M)) ** ((g + 1) / (2 * (g - 1)))


def isentropic(M: float, gamma: float = 1.4) -> dict:
    M, g = num("M", M, positive=True, hi=50), _g(gamma)
    t = 1 + (g - 1) / 2 * M * M
    res = {"M": M, "T0_over_T": t, "p0_over_p": t ** (g / (g - 1)), "rho0_over_rho": t ** (1 / (g - 1)),
           "A_over_Astar": area_ratio(M, g), "mach_angle_deg": math.degrees(math.asin(1 / M)) if M > 1 else None}
    return result(res, "T0/T = 1 + (g-1)/2 M^2; p0/p = (T0/T)^(g/(g-1)); A/A* = (1/M)[(2/(g+1))(1+(g-1)/2 M^2)]^((g+1)/(2(g-1)))", ASSUME)


def mach_from_area_ratio(A_over_Astar: float, supersonic: bool = True, gamma: float = 1.4) -> float:
    r, g = num("A_over_Astar", A_over_Astar, lo=1.0), _g(gamma)
    if abs(r - 1) < 1e-12:
        return 1.0
    f = lambda M: area_ratio(M, g) - r
    return _bisect(f, 1.0, 100.0) if supersonic else _bisect(f, 1e-9, 1.0)


def normal_shock(M1: float, gamma: float = 1.4) -> dict:
    M1, g = num("M1", M1, hi=50), _g(gamma)
    if M1 <= 1:
        raise EngError("a normal shock needs supersonic upstream flow (M1 > 1)")
    M2 = math.sqrt((1 + (g - 1) / 2 * M1 * M1) / (g * M1 * M1 - (g - 1) / 2))
    p21 = 1 + 2 * g / (g + 1) * (M1 * M1 - 1)
    r21 = (g + 1) * M1 * M1 / ((g - 1) * M1 * M1 + 2)
    T21 = p21 / r21
    p0r = p21 * ((1 + (g - 1) / 2 * M2 * M2) / (1 + (g - 1) / 2 * M1 * M1)) ** (g / (g - 1))
    return result({"M1": M1, "M2": M2, "p2_over_p1": p21, "rho2_over_rho1": r21, "T2_over_T1": T21, "p02_over_p01": p0r,
                   "entropy_rise_over_R": -math.log(p0r)},
                  "M2^2 = (1+(g-1)/2 M1^2)/(g M1^2-(g-1)/2); p2/p1 = 1+2g/(g+1)(M1^2-1); rho2/rho1 = (g+1)M1^2/((g-1)M1^2+2)", ASSUME)


def _theta(beta, M1, g):
    return math.atan(2 / math.tan(beta) * (M1 ** 2 * math.sin(beta) ** 2 - 1) / (M1 ** 2 * (g + math.cos(2 * beta)) + 2))


def max_deflection(M1: float, gamma: float = 1.4) -> Dict[str, float]:
    M1, g = num("M1", M1, hi=50), _g(gamma)
    if M1 <= 1:
        raise EngError("oblique shocks need M1 > 1")
    lo, hi = math.asin(1 / M1), math.pi / 2
    phi = (math.sqrt(5) - 1) / 2
    a, b = lo, hi
    for _ in range(200):                                  # golden-section maximisation of theta(beta)
        c, d = b - phi * (b - a), a + phi * (b - a)
        if _theta(c, M1, g) > _theta(d, M1, g):
            b = d
        else:
            a = c
    beta = 0.5 * (a + b)
    return {"theta_max_deg": math.degrees(_theta(beta, M1, g)), "beta_at_theta_max_deg": math.degrees(beta)}


def oblique_shock(M1: float, theta_deg: float, strong: bool = False, gamma: float = 1.4) -> dict:
    M1, g = num("M1", M1, hi=50), _g(gamma)
    th = math.radians(num("theta_deg", theta_deg, positive=True, hi=89))
    mx = max_deflection(M1, g)
    if math.degrees(th) > mx["theta_max_deg"]:
        raise EngError(f"deflection {math.degrees(th):.2f} deg exceeds the maximum {mx['theta_max_deg']:.2f} deg for M1 = {M1}: "
                       "the shock detaches (a bow shock forms; the attached-shock solution does not exist)")
    mu, bmax = math.asin(1 / M1), math.radians(mx["beta_at_theta_max_deg"])
    f = lambda b: _theta(b, M1, g) - th
    beta = _bisect(f, bmax, math.pi / 2 - 1e-12) if strong else _bisect(f, mu + 1e-12, bmax)
    ns = normal_shock(M1 * math.sin(beta), g)["results"]
    M2 = ns["M2"] / math.sin(beta - th)
    return result({"M1": M1, "theta_deg": math.degrees(th), "beta_deg": math.degrees(beta), "solution": "strong" if strong else "weak",
                   "M2": M2, "Mn1": M1 * math.sin(beta), "p2_over_p1": ns["p2_over_p1"], "rho2_over_rho1": ns["rho2_over_rho1"],
                   "T2_over_T1": ns["T2_over_T1"], "p02_over_p01": ns["p02_over_p01"], "theta_max_deg": mx["theta_max_deg"]},
                  "theta-beta-M relation; normal-shock relations on Mn1 = M1 sin(beta); M2 = Mn2/sin(beta-theta)", ASSUME + ["planar (2-D) wedge flow"])


def _pm(M: float, g: float) -> float:
    k = math.sqrt((g + 1) / (g - 1))
    return math.degrees(k * math.atan(math.sqrt((M * M - 1) / (k * k))) - math.atan(math.sqrt(M * M - 1)))


def prandtl_meyer(M: float, gamma: float = 1.4) -> float:
    """nu(M) in degrees."""
    return _pm(num("M", M, lo=1.0, hi=100), _g(gamma))


def mach_from_prandtl_meyer(nu_deg: float, gamma: float = 1.4) -> float:
    g = _g(gamma)
    nu = num("nu_deg", nu_deg, nonneg=True)
    nmax = math.degrees(math.pi / 2 * (math.sqrt((g + 1) / (g - 1)) - 1))
    if nu >= nmax:
        raise EngError(f"nu = {nu:.2f} deg exceeds the maximum turning angle {nmax:.2f} deg (expansion to vacuum)")
    return _bisect(lambda M: _pm(M, g) - nu, 1.0, 1e5)


def expansion_fan(M1: float, turn_deg: float, gamma: float = 1.4) -> dict:
    M1, g = num("M1", M1, hi=50), _g(gamma)
    if M1 <= 1:
        raise EngError("a Prandtl-Meyer expansion needs supersonic flow (M1 > 1)")
    turn = num("turn_deg", turn_deg, positive=True)
    nu1 = prandtl_meyer(M1, g)
    M2 = mach_from_prandtl_meyer(nu1 + turn, g)
    t1, t2 = 1 + (g - 1) / 2 * M1 * M1, 1 + (g - 1) / 2 * M2 * M2
    return result({"M1": M1, "M2": M2, "nu1_deg": nu1, "nu2_deg": nu1 + turn, "p2_over_p1": (t1 / t2) ** (g / (g - 1)),
                   "T2_over_T1": t1 / t2, "rho2_over_rho1": (t1 / t2) ** (1 / (g - 1)),
                   "mu1_deg": math.degrees(math.asin(1 / M1)), "mu2_deg": math.degrees(math.asin(1 / M2))},
                  "nu(M2) = nu(M1) + theta; isentropic ratios across the fan (p0, T0 constant)", ASSUME + ["planar (2-D)", "centred fan at a sharp corner"])
