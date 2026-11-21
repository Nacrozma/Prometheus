"""Machine design: stress concentration, fatigue, shafts, bolted joints.

Methods and coefficients follow Shigley's Mechanical Engineering Design (Budynas & Nisbett, 9th/10th ed.), the
standard undergraduate reference; ISO 898-1 property classes for bolts. These are educational design methods:
they estimate, they do not certify. All stresses in Pa, lengths in m unless a name says otherwise.

Stress concentration
    Kt   theoretical (elastic) stress concentration factor from geometry (charts, or the closed forms here)
    q    notch sensitivity, Neuber: q = 1 / (1 + sqrt(a)/sqrt(r)), sqrt(a) from Shigley eq. 6-35 (steel, Sut in kpsi)
    Kf   fatigue stress concentration factor, Kf = 1 + q (Kt - 1)   (Kf <= Kt; Kf = Kt for a fully notch-sensitive part)

Endurance limit (steel)
    Se' = 0.5 Sut (Sut <= 1400 MPa), 700 MPa above;  Se = ka kb kc kd ke kf Se'   (Marin factors)
    ka = a Sut^b (surface), kb size (rotating round bars), kc load (bending 1, axial 0.85, torsion 0.59),
    kd temperature (Shigley eq. 6-27), ke reliability (Shigley table 6-5)

Fluctuating stress criteria (sigma_a alternating, sigma_m mean, both already multiplied by Kf):
    Goodman    sigma_a/Se + sigma_m/Sut = 1/n
    Soderberg  sigma_a/Se + sigma_m/Sy  = 1/n        (conservative)
    Gerber     n sigma_a/Se + (n sigma_m/Sut)^2 = 1
    Langer (first-cycle yield) n_y = Sy / (sigma_a + sigma_m)
Finite life (Basquin, Shigley eq. 6-13 to 6-16): S_f = a N^b, valid 10^3 <= N <= 10^6.

Shaft (DE-Goodman, Shigley eq. 7-7 and 7-8) for bending M and torsion T split into alternating and mean parts.

Bolted joints (Shigley ch. 8): tensile stress area At = pi/4 (d - 0.9382 p)^2 (ISO metric), preload Fi = 0.75 At Sp
(reusable) or 0.9 At Sp (permanent), bolt and member stiffness (member by Wileman's exponential fit for steel),
joint constant C = kb/(kb + km), yield, load and separation factors, Goodman fatigue with the fully corrected
endurance strength of rolled threads.
"""
import math
from typing import Any, Dict, Optional

from . import EngError
from ._util import num, result

MPA = 1e6
KPSI = 6.894757e6

SURFACE = {"ground": (1.58, -0.085), "machined": (4.51, -0.265), "cold_drawn": (4.51, -0.265),
           "hot_rolled": (57.7, -0.718), "as_forged": (272.0, -0.995)}       # ka = a Sut[MPa]^b
LOAD = {"bending": 1.0, "axial": 0.85, "torsion": 0.59}
RELIABILITY = {50: 1.000, 90: 0.897, 95: 0.868, 99: 0.814, 99.9: 0.753, 99.99: 0.702, 99.999: 0.659, 99.9999: 0.620}

# ISO 898-1 (via Shigley table 8-11): class -> (proof Sp, Sut, Sy) in MPa; 8.8 differs below/above M16
BOLT_CLASSES = {"4.6": (225, 400, 240), "4.8": (310, 420, 340), "5.8": (380, 520, 420), "8.8_small": (580, 800, 640),
                "8.8": (600, 830, 660), "9.8": (650, 900, 720), "10.9": (830, 1040, 940), "12.9": (970, 1220, 1100)}
# fully corrected endurance strength of rolled threads (Shigley table 8-17), MPa
BOLT_SE = {"8.8_small": 129, "8.8": 129, "9.8": 140, "10.9": 162, "12.9": 190}


# ------------------------------------------------------------------------------ stress concentration
def kt_elliptical_hole(a: float, b: float) -> Dict[str, Any]:
    """Inglis: elliptical hole in an infinite plate under remote tension perpendicular to the a axis: Kt = 1 + 2a/b
    (a circle gives 3). Exact for linear elasticity; finite plates need chart corrections."""
    a, b = num("a", a, positive=True), num("b", b, positive=True)
    return result({"Kt": 1 + 2 * a / b}, "Kt = 1 + 2a/b (Inglis)", ["infinite plate", "uniaxial remote tension perpendicular to a", "linear elastic"])


def notch_sensitivity(r: float, Sut: float, loading: str = "bending") -> float:
    """Neuber notch sensitivity for steel, Shigley eq. 6-35 (valid ~340-1700 MPa). r notch radius [m]."""
    r_in = num("notch radius r", r, positive=True) / 0.0254
    s = num("Sut", Sut, positive=True) / KPSI
    if not 50 <= s <= 250:
        raise EngError(f"the notch-sensitivity fit covers Sut = 345..1720 MPa (got {Sut / MPA:.0f} MPa)")
    if loading in ("bending", "axial"):
        sqrt_a = 0.246 - 3.08e-3 * s + 1.51e-5 * s * s - 2.67e-8 * s ** 3
    elif loading == "torsion":
        sqrt_a = 0.190 - 2.51e-3 * s + 1.35e-5 * s * s - 2.67e-8 * s ** 3
    else:
        raise EngError("loading must be bending, axial or torsion")
    return 1.0 / (1.0 + sqrt_a / math.sqrt(r_in))


def fatigue_kf(Kt: float, r: float, Sut: float, loading: str = "bending") -> Dict[str, Any]:
    kt = num("Kt", Kt, lo=1.0)
    q = notch_sensitivity(r, Sut, loading)
    kf = 1 + q * (kt - 1)
    return result({"q": q, "Kf": kf, "Kt": kt}, "q = 1/(1 + sqrt(a)/sqrt(r)) (Neuber, Shigley 6-35); Kf = 1 + q(Kt - 1)",
                  ["steel", "Kt from a chart or closed form for the actual geometry", "Kf applies to alternating stress (and mean for ductile parts by convention)"])


# ------------------------------------------------------------------------------ endurance limit
def marin(Sut: float, surface: str = "machined", d: Optional[float] = None, loading: str = "bending",
          temperature_C: Optional[float] = None, reliability: float = 50, kf_misc: float = 1.0) -> Dict[str, Any]:
    sut = num("Sut", Sut, positive=True)
    if surface not in SURFACE:
        raise EngError(f"surface must be one of {', '.join(SURFACE)}")
    a, b = SURFACE[surface]
    ka = a * (sut / MPA) ** b
    if d is None or loading == "axial":
        kb = 1.0
    else:
        dm = num("d", d, positive=True) * 1000
        if 2.79 <= dm <= 51:
            kb = 1.24 * dm ** -0.107
        elif 51 < dm <= 254:
            kb = 1.51 * dm ** -0.157
        elif dm < 2.79:
            kb = 1.0
        else:
            raise EngError("the size factor covers diameters up to 254 mm")
    if loading not in LOAD:
        raise EngError(f"loading must be one of {', '.join(LOAD)}")
    kc = LOAD[loading]
    if temperature_C is None:
        kd = 1.0
    else:
        tf = num("temperature_C", temperature_C) * 9 / 5 + 32
        if not 70 <= tf <= 1000:
            raise EngError("the temperature factor covers 21..538 C")
        kd = 0.975 + 0.432e-3 * tf - 0.115e-5 * tf ** 2 + 0.104e-8 * tf ** 3 - 0.595e-12 * tf ** 4
    if reliability not in RELIABILITY:
        raise EngError(f"reliability must be one of {sorted(RELIABILITY)} %")
    ke = RELIABILITY[reliability]
    se_prime = 0.5 * sut if sut <= 1400 * MPA else 700 * MPA
    se = ka * kb * kc * kd * ke * num("kf_misc", kf_misc, positive=True) * se_prime
    warnings = ["ka > 1: check the surface category" ] if ka > 1 else []
    return result({"Se_prime_Pa": se_prime, "ka": ka, "kb": kb, "kc": kc, "kd": kd, "ke": ke, "Se_Pa": se},
                  "Se = ka kb kc kd ke kf Se', Se' = 0.5 Sut (<= 1400 MPa) else 700 MPa; ka = a Sut^b; kb = 1.24 d^-0.107 "
                  "(2.79-51 mm), 1.51 d^-0.157 (51-254 mm)",
                  ["steel", "rotating-beam test basis", "infinite life defined at 10^6 cycles"], warnings)


# ------------------------------------------------------------------------------ fluctuating stress
def fatigue(sigma_a: float, sigma_m: float, Se: float, Sut: float, Sy: float) -> Dict[str, Any]:
    """Safety factors for a fluctuating normal stress (alternating sigma_a, mean sigma_m >= 0, already including Kf)."""
    sa, sm = num("sigma_a", sigma_a, nonneg=True), num("sigma_m", sigma_m)
    se, sut, sy = num("Se", Se, positive=True), num("Sut", Sut, positive=True), num("Sy", Sy, positive=True)
    if sy > sut:
        raise EngError("Sy cannot exceed Sut")
    if sa == 0 and sm == 0:
        raise EngError("no stress: nothing to check")
    if sm < 0:
        # compressive mean: Shigley treats fatigue as governed by the alternating stress alone
        n_goodman = n_soderberg = n_gerber = se / sa if sa > 0 else math.inf
        note = "compressive mean stress: fatigue factor = Se / sigma_a (mean stress taken as not harmful)"
    else:
        n_goodman = 1.0 / (sa / se + sm / sut)
        n_soderberg = 1.0 / (sa / se + sm / sy)
        if sm == 0:
            n_gerber = se / sa
        else:
            r = sa / se
            n_gerber = (sut / sm) ** 2 * r / 2 * (-1 + math.sqrt(1 + (2 * sm * se / (sut * sa)) ** 2)) if sa > 0 else sut / sm
        note = ""
    n_yield = sy / (sa + abs(sm))
    warnings = [note] if note else []
    if min(n_goodman, n_yield) < 1:
        warnings.append("safety factor below 1: predicted to fail")
    life = finite_life(sa / (1 - sm / sut) if 0 <= sm < sut else sa, Se=se, Sut=sut)["results"]
    return result({"n_goodman": n_goodman, "n_soderberg": n_soderberg, "n_gerber": n_gerber, "n_yield_langer": n_yield,
                   "equivalent_reversed_stress_Pa": life["sigma_rev_Pa"], "cycles_to_failure": life["cycles"],
                   "life_regime": life["regime"]},
                  "Goodman 1/n = sa/Se + sm/Sut; Soderberg 1/n = sa/Se + sm/Sy; Gerber n sa/Se + (n sm/Sut)^2 = 1; Langer n = Sy/(sa+sm)",
                  ["uniaxial fluctuating stress", "Kf already applied", "steel S-N behaviour"], warnings)


def finite_life(sigma_rev: float, Se: float, Sut: float, f: Optional[float] = None) -> Dict[str, Any]:
    """Cycles to failure for a completely reversed stress (Basquin line between 10^3 and 10^6 cycles)."""
    s, se, sut = num("sigma_rev", sigma_rev, nonneg=True), num("Se", Se, positive=True), num("Sut", Sut, positive=True)
    if f is None:
        sf = sut + 345 * MPA                         # SAE approximation of the fatigue strength coefficient
        se_p = 0.5 * sut if sut <= 1400 * MPA else 700 * MPA
        b_ = -math.log10(sf / se_p) / math.log10(2e6)
        f = sf / sut * (2e3) ** b_
    a = (f * sut) ** 2 / se
    b = -math.log10(f * sut / se) / 3
    if s <= se:
        cycles, regime = math.inf, "infinite life (below the endurance limit)"
    elif s > f * sut:
        cycles, regime = None, "low-cycle (< 10^3 cycles): outside this method"
    else:
        cycles, regime = (s / a) ** (1 / b), "finite life (Basquin)"
    return result({"sigma_rev_Pa": s, "f": f, "a_Pa": a, "b": b, "cycles": cycles, "regime": regime},
                  "S_f = a N^b, a = (f Sut)^2/Se, b = -log10(f Sut/Se)/3", ["steel", "10^3..10^6 cycles", "median life (50% reliability unless Se includes ke)"])


# ------------------------------------------------------------------------------ shafts
def shaft(Ma: float, Mm: float, Ta: float, Tm: float, Sut: float, Sy: float, n: float = 2.0, Kf: float = 1.0, Kfs: float = 1.0,
          surface: str = "machined", reliability: float = 50, d: Optional[float] = None) -> Dict[str, Any]:
    """DE-Goodman shaft: size the diameter for safety factor n (d omitted), or check a given diameter d.
    Ma, Mm bending moments [N m] (alternating, mean), Ta, Tm torques [N m]. Iterates the size factor kb with d."""
    ma, mm, ta, tm = (num(k, v, nonneg=True) for k, v in (("Ma", Ma), ("Mm", Mm), ("Ta", Ta), ("Tm", Tm)))
    sut, sy = num("Sut", Sut, positive=True), num("Sy", Sy, positive=True)
    kf, kfs = num("Kf", Kf, lo=1.0), num("Kfs", Kfs, lo=1.0)
    A = math.sqrt(4 * (kf * ma) ** 2 + 3 * (kfs * ta) ** 2)
    B = math.sqrt(4 * (kf * mm) ** 2 + 3 * (kfs * tm) ** 2)
    if A == 0 and B == 0:
        raise EngError("no load on the shaft")
    if d is None:
        nn = num("n", n, positive=True)
        dd = 0.025
        for _ in range(50):
            se = marin(sut, surface, dd, "bending", None, reliability)["results"]["Se_Pa"]
            new = (16 * nn / math.pi * (A / se + B / sut)) ** (1 / 3)
            if abs(new - dd) < 1e-9:
                break
            dd = new
        mode = "sized"
    else:
        dd = num("d", d, positive=True)
        se = marin(sut, surface, dd, "bending", None, reliability)["results"]["Se_Pa"]
        mode = "checked"
    n_fatigue = 1.0 / (16 / (math.pi * dd ** 3) * (A / se + B / sut))
    sig_max = math.sqrt((32 * kf * (mm + ma) / (math.pi * dd ** 3)) ** 2 + 3 * (16 * kfs * (tm + ta) / (math.pi * dd ** 3)) ** 2)
    n_yield = sy / sig_max
    warnings = []
    if n_yield < 1 or n_fatigue < 1:
        warnings.append("safety factor below 1")
    elif n_yield < n_fatigue:
        warnings.append("first-cycle yield governs (von Mises maximum stress)")
    return result({"diameter_m": dd, "mode": mode, "Se_Pa": se, "n_fatigue_DE_Goodman": n_fatigue, "n_yield": n_yield,
                   "von_mises_max_Pa": sig_max},
                  "d = [16n/pi (sqrt(4(Kf Ma)^2 + 3(Kfs Ta)^2)/Se + sqrt(4(Kf Mm)^2 + 3(Kfs Tm)^2)/Sut)]^(1/3) (Shigley 7-8); "
                  "n_y = Sy / sqrt((32Kf(Mm+Ma)/(pi d^3))^2 + 3(16Kfs(Tm+Ta)/(pi d^3))^2)",
                  ["solid round steel shaft", "distortion-energy failure theory", "Kf, Kfs for the critical section supplied by the user",
                   "axial loads neglected"], warnings)


# ------------------------------------------------------------------------------ bolted joints
def tensile_stress_area(d: float, pitch: float) -> float:
    d, p = num("d", d, positive=True), num("pitch", pitch, positive=True)
    if p >= d / 2:
        raise EngError("pitch is too large for this diameter")
    return math.pi / 4 * (d - 0.9382 * p) ** 2


def bolted_joint(d: float, pitch: float, grip: float, load_per_bolt: float, property_class: str = "8.8", E_bolt: float = 207e9,
                 E_member: float = 207e9, preload_fraction: float = 0.75, thread_length: Optional[float] = None,
                 shear_per_bolt: float = 0.0) -> Dict[str, Any]:
    """Tension joint with one bolt (or the share per bolt). d nominal diameter [m], pitch [m], grip = clamped thickness [m],
    load_per_bolt = external separating load P [N]. Steel members (Wileman's fit) unless E_member is changed."""
    d, grip, P = num("d", d, positive=True), num("grip", grip, positive=True), num("load_per_bolt", load_per_bolt, nonneg=True)
    At = tensile_stress_area(d, pitch)
    cls = property_class
    if cls == "8.8" and d <= 0.016:
        cls = "8.8_small"
    if cls not in BOLT_CLASSES:
        raise EngError(f"property class must be one of {', '.join(k for k in BOLT_CLASSES if not k.endswith('_small'))}")
    sp, sut, sy = (v * MPA for v in BOLT_CLASSES[cls])
    pf = num("preload_fraction", preload_fraction, lo=0.0, hi=0.95)
    Fi = pf * At * sp
    Ad = math.pi * d * d / 4
    lt = min(grip, num("thread_length", thread_length, positive=True) if thread_length is not None else min(grip, 2 * d + 0.006))
    ld = max(0.0, grip - lt)
    kb = Ad * At * E_bolt / (Ad * lt + At * ld)
    km = num("E_member", E_member, positive=True) * d * 0.78715 * math.exp(0.62873 * d / grip)
    C = kb / (kb + km)
    Fb = C * P + Fi
    Fm = (1 - C) * P - Fi
    n_yield = sp * At / Fb
    n_load = (sp * At - Fi) / (C * P) if P > 0 else math.inf
    n_sep = Fi / (P * (1 - C)) if P > 0 else math.inf
    out = {"tensile_stress_area_m2": At, "proof_strength_Pa": sp, "preload_N": Fi, "bolt_stiffness_N_m": kb, "member_stiffness_N_m": km,
           "joint_constant_C": C, "bolt_load_N": Fb, "member_load_N": Fm, "n_proof_yield": n_yield, "n_load": n_load, "n_separation": n_sep}
    warnings = []
    if cls in BOLT_SE and P > 0:
        se = BOLT_SE[cls] * MPA
        sa = C * P / (2 * At)
        sm = sa + Fi / At
        si = Fi / At
        out["n_fatigue_goodman"] = se * (sut - si) / (sut * sa + se * (sm - si))
        out["thread_endurance_Se_Pa"] = se
    if shear_per_bolt:
        V = num("shear_per_bolt", shear_per_bolt, nonneg=True)
        tau = V / At
        out["shear_stress_on_threads_Pa"] = tau
        out["n_shear"] = 0.577 * sy / tau if tau > 0 else math.inf
        warnings.append("shear checked on the tensile stress area (threads in the shear plane); joints should normally carry shear by friction")
    if n_sep < 1:
        warnings.append("the joint separates under this load: increase preload or bolt count")
    if n_load < 1 or n_yield < 1:
        warnings.append("bolt overloaded")
    return result(out, "At = pi/4 (d - 0.9382p)^2; Fi = f At Sp; kb = Ad At E/(Ad lt + At ld); km = E d 0.78715 e^(0.62873 d/l) (Wileman, steel); "
                       "C = kb/(kb+km); n_L = (Sp At - Fi)/(C P); n_0 = Fi/(P(1-C)); Goodman with rolled-thread Se",
                  ["ISO metric coarse/fine thread", "properties per ISO 898-1 class", "steel members (Wileman)", "concentric load, no prying",
                   "preload achieved as specified (torque-tension scatter ignored)"], warnings)
