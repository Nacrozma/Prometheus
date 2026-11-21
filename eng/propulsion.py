"""Ideal rocket nozzle performance (quasi-one-dimensional, isentropic, frozen composition).

    R = Ru / Mw,   c* = sqrt(g R Tc) / ( g sqrt( (2/(g+1))^((g+1)/(g-1)) ) )
    mdot = pc At / c*                                     (choked throat)
    exit Mach from the supersonic root of A/A* = eps;    pe/pc = (1 + (g-1)/2 Me^2)^(-g/(g-1))
    CF = sqrt( 2 g^2/(g-1) (2/(g+1))^((g+1)/(g-1)) (1 - (pe/pc)^((g-1)/g)) ) + eps (pe - pa)/pc
    F  = CF pc At,   Isp = F / (mdot g0) = CF c* / g0,   ve = sqrt( 2g/(g-1) R Tc (1 - (pe/pc)^((g-1)/g)) )

Ideal means: perfect gas with one constant gamma and molar mass (no shifting equilibrium), isentropic expansion,
one-dimensional uniform exit flow (no divergence loss), no boundary layer, complete combustion at the stated chamber
temperature. Real engines deliver less: optional efficiencies eta_cstar (combustion, typically 0.9-0.99) and eta_cf
(nozzle, typically 0.95-0.99) scale c* and CF and are reported separately. Nothing here is a measurement of an engine.
Flow separation: an over-expanded nozzle at sea level separates roughly when pe < 0.4 pa (Summerfield criterion);
the ideal formula is then wrong and a warning is given.
"""
import math
from typing import Dict, Optional

from . import EngError
from ._util import num, result
from .compressible import mach_from_area_ratio

RU = 8.314462618
G0 = 9.80665
P_SL = 101325.0


def nozzle(pc: float, Tc: float, gamma: float, molar_mass: float, throat_area: float, expansion_ratio: float,
           pa: float = P_SL, eta_cstar: float = 1.0, eta_cf: float = 1.0) -> dict:
    """pc [Pa], Tc [K], gamma, molar_mass [kg/mol], throat_area [m^2], expansion_ratio Ae/At, pa ambient [Pa]."""
    pc, Tc = num("pc", pc, positive=True), num("Tc", Tc, positive=True)
    g = num("gamma", gamma, lo=1.05, hi=1.67)
    Mw = num("molar_mass", molar_mass, lo=0.002, hi=0.2)
    At = num("throat_area", throat_area, positive=True)
    eps = num("expansion_ratio", expansion_ratio, lo=1.0, hi=500)
    pa = num("pa", pa, nonneg=True)
    ec, ef = num("eta_cstar", eta_cstar, lo=0.5, hi=1.0), num("eta_cf", eta_cf, lo=0.5, hi=1.0)
    R = RU / Mw
    gam_term = (2 / (g + 1)) ** ((g + 1) / (g - 1))
    cstar = math.sqrt(g * R * Tc) / (g * math.sqrt(gam_term))
    Me = mach_from_area_ratio(eps, True, g)
    pe = pc * (1 + (g - 1) / 2 * Me * Me) ** (-g / (g - 1))
    mom = math.sqrt(2 * g * g / (g - 1) * gam_term * (1 - (pe / pc) ** ((g - 1) / g)))

    def cf(p_amb):
        return mom + eps * (pe - p_amb) / pc

    mdot = pc * At / (cstar * ec)
    ve = math.sqrt(2 * g / (g - 1) * R * Tc * (1 - (pe / pc) ** ((g - 1) / g)))
    out = {"cstar_ideal_m_s": cstar, "cstar_m_s": cstar * ec, "exit_mach": Me, "exit_pressure_Pa": pe, "pc_over_pe": pc / pe,
           "exhaust_velocity_ideal_m_s": ve, "mass_flow_kg_s": mdot}
    for label, p_amb in (("ambient", pa), ("sea_level", P_SL), ("vacuum", 0.0)):
        c = cf(p_amb) * ef
        F = c * pc * At
        out[f"CF_{label}"] = c
        out[f"thrust_{label}_N"] = F
        out[f"isp_{label}_s"] = F / (mdot * G0)
    pe_opt = pa
    warnings = []
    if pa > 0 and pe < 0.4 * pa:
        warnings.append(f"over-expanded: exit pressure {pe:.0f} Pa is below 0.4 x ambient ({0.4 * pa:.0f} Pa); the flow likely separates "
                        "and the ideal thrust is not valid")
    elif pa > 0 and pe < pa:
        warnings.append("over-expanded at this ambient pressure (pe < pa): pressure thrust is negative")
    if pe > pa * 3 and pa > 0:
        warnings.append("strongly under-expanded at this ambient pressure: a larger expansion ratio would recover thrust")
    if Tc > 4000:
        warnings.append("chamber temperature above 4000 K: dissociation makes the frozen, constant-gamma model optimistic")
    out["optimum_expansion_for_ambient"] = pe_opt > 0 and abs(pe - pe_opt) / pe_opt < 0.02
    return result(out, "c* = sqrt(g R Tc)/(g sqrt((2/(g+1))^((g+1)/(g-1)))); mdot = pc At/c*; CF = momentum term + eps (pe - pa)/pc; "
                       "F = CF pc At; Isp = CF c*/g0",
                  ["ideal rocket: perfect gas, constant gamma and molar mass (frozen flow)", "isentropic, 1-D, uniform exit (no divergence loss)",
                   f"efficiencies applied: eta_c* = {ec}, eta_CF = {ef}" if (ec < 1 or ef < 1) else "no efficiency losses (ideal)"],
                  warnings)


def cf_vacuum_limit(gamma: float) -> float:
    """CF for infinite expansion into vacuum (the upper bound of the ideal thrust coefficient)."""
    g = num("gamma", gamma, lo=1.05, hi=1.67)
    return math.sqrt(2 * g * g / (g - 1) * (2 / (g + 1)) ** ((g + 1) / (g - 1)))


def sensitivity(base: Dict[str, float], output: str = "isp_vacuum_s", rel_step: float = 1e-4) -> Dict[str, float]:
    """Normalised sensitivities d ln(output) / d ln(input) by central differences, for each numeric input of nozzle()."""
    y0 = nozzle(**base)["results"][output]
    out = {}
    for k in ("pc", "Tc", "gamma", "molar_mass", "expansion_ratio", "pa"):
        if k not in base or base[k] == 0:
            continue
        hi, lo = dict(base), dict(base)
        hi[k] = base[k] * (1 + rel_step)
        lo[k] = base[k] * (1 - rel_step)
        try:
            out[k] = (nozzle(**hi)["results"][output] - nozzle(**lo)["results"][output]) / (2 * rel_step * y0)
        except EngError:
            continue
    return out
