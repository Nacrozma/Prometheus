"""U.S. Standard Atmosphere 1976, 0 to 86 km geometric altitude (the seven lower layers).

    geopotential altitude  H = r0 h / (r0 + h),  r0 = 6 356 766 m
    temperature            T = Tb + Lb (H - Hb)           (linear in geopotential altitude per layer)
    pressure               p = pb (Tb / T)^(g0 M0 / (R* Lb))       for Lb != 0
                           p = pb exp(-g0 M0 (H - Hb) / (R* Tb))   for Lb  = 0
    density                rho = p M0 / (R* T)
    speed of sound         a = sqrt(gamma R T),  gamma = 1.4
    dynamic viscosity      mu = beta T^1.5 / (T + S),  beta = 1.458e-6, S = 110.4 K (Sutherland, as in the standard)

Constants exactly as in the 1976 standard: g0 = 9.80665, R* = 8.31432 J/(mol K), M0 = 0.0289644 kg/mol. Above 86 km
the molecular weight is no longer constant and this model does not apply. The temperature returned is the
molecular-scale temperature; between 80 and 86 km the standard's kinetic temperature is lower by up to 0.04 %
(at 86 km: 186.87 K kinetic vs 186.946 K molecular-scale). Pressure and density are unaffected. Layer base pressures are computed from
the layer equations (they reproduce the published 22 632.06, 5 474.889, 868.0187, 110.9063, 66.93887, 3.956420 Pa).
"""
import math
from typing import Dict

from . import EngError
from ._util import num, result

G0 = 9.80665
R_STAR = 8.31432
M0 = 0.0289644
R_AIR = R_STAR / M0                 # 287.0531 J/(kg K)
GAMMA = 1.4
R0 = 6356766.0
H_TOP_GEOPOT = 84852.0              # = 86 km geometric

LAYERS = [(0.0, 288.15, -0.0065), (11000.0, 216.65, 0.0), (20000.0, 216.65, 0.001), (32000.0, 228.65, 0.0028),
          (47000.0, 270.65, 0.0), (51000.0, 270.65, -0.0028), (71000.0, 214.65, -0.002)]


def _base_pressures():
    p = [101325.0]
    for i in range(1, len(LAYERS)):
        Hb, Tb, L = LAYERS[i - 1]
        H = LAYERS[i][0]
        if L == 0.0:
            p.append(p[-1] * math.exp(-G0 * M0 * (H - Hb) / (R_STAR * Tb)))
        else:
            p.append(p[-1] * (Tb / (Tb + L * (H - Hb))) ** (G0 * M0 / (R_STAR * L)))
    return p


P_BASE = _base_pressures()


def geopotential(h: float) -> float:
    return R0 * h / (R0 + h)


def state(altitude_m: float) -> Dict[str, float]:
    """Raw numbers (used by the trajectory model); raises EngError outside 0..86 km."""
    h = num("altitude_m", altitude_m)
    if not -1e-9 <= h <= 86000.0 + 1e-6:
        raise EngError("the 1976 standard atmosphere here covers 0 to 86,000 m geometric altitude")
    H = geopotential(max(0.0, h))
    i = max(k for k, layer in enumerate(LAYERS) if layer[0] <= H + 1e-9)
    Hb, Tb, L = LAYERS[i]
    T = Tb + L * (H - Hb)
    if L == 0.0:
        p = P_BASE[i] * math.exp(-G0 * M0 * (H - Hb) / (R_STAR * Tb))
    else:
        p = P_BASE[i] * (Tb / T) ** (G0 * M0 / (R_STAR * L))
    rho = p * M0 / (R_STAR * T)
    return {"altitude_m": h, "geopotential_altitude_m": H, "temperature_K": T, "pressure_Pa": p, "density_kg_m3": rho,
            "speed_of_sound_m_s": math.sqrt(GAMMA * R_AIR * T), "dynamic_viscosity_Pa_s": 1.458e-6 * T ** 1.5 / (T + 110.4),
            "gravity_m_s2": G0 * (R0 / (R0 + h)) ** 2, "layer": i}


def standard_atmosphere_1976(altitude_m: float) -> dict:
    s = state(altitude_m)
    return result(s, "U.S. Standard Atmosphere 1976: T linear in geopotential altitude per layer; hydrostatic pressure; ideal gas; Sutherland viscosity",
                  ["0-86 km geometric", "dry air, constant molecular weight (valid below 86 km)", "mid-latitude annual mean (a standard, not a forecast)"])
