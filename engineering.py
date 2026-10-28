"""
engineering.py - deterministic mechanical / aerospace calculators for Prometheus.

Every calculation is a plain function over SI inputs (metres, newtons, pascals, kilograms,
seconds, radians unless the parameter name says otherwise). Nothing here is evaluated from
strings, nothing touches the network or the disk, and every result carries the formula used
and the assumptions behind it, so an answer can be checked by hand.

Verified against textbook values in tests/test_engineering.py. These are first-pass design
calculations (linear elastic, small deflection, ideal pins, standard atmosphere): they are
not a substitute for FEA, a code check, or a licensed engineer.
"""
import math
from typing import Any, Callable, Dict, List, Tuple

G0 = 9.80665                      # standard gravity, m/s^2
R_AIR = 287.05287                 # specific gas constant of dry air, J/(kg K)
GAMMA_AIR = 1.4
BODIES = {                         # mu [m^3/s^2], mean/equatorial radius [m]
    "earth": (3.986004418e14, 6378137.0),
    "moon": (4.9048695e12, 1737400.0),
    "mars": (4.282837e13, 3396200.0),
}


class CalcError(ValueError):
    """Bad input: the message says what to fix."""


def _num(name: str, v: Any, positive: bool = False, nonneg: bool = False) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise CalcError(f"'{name}' must be a number")
    v = float(v)
    if not math.isfinite(v):
        raise CalcError(f"'{name}' must be finite")
    if positive and v <= 0:
        raise CalcError(f"'{name}' must be greater than zero")
    if nonneg and v < 0:
        raise CalcError(f"'{name}' must not be negative")
    return v


# ------------------------------------------------------------------------------ units
_UNITS: Dict[str, Dict[str, float]] = {
    "length": {"m": 1.0, "mm": 1e-3, "cm": 1e-2, "km": 1e3, "in": 0.0254, "ft": 0.3048, "mi": 1609.344, "nmi": 1852.0},
    "force": {"n": 1.0, "kn": 1e3, "lbf": 4.4482216152605, "kgf": G0},
    "pressure": {"pa": 1.0, "kpa": 1e3, "mpa": 1e6, "gpa": 1e9, "psi": 6894.757293168, "bar": 1e5, "atm": 101325.0},
    "mass": {"kg": 1.0, "g": 1e-3, "lb": 0.45359237, "slug": 14.5939029372},
    "energy": {"j": 1.0, "kj": 1e3, "kwh": 3.6e6, "btu": 1055.05585262, "ftlbf": 1.3558179483},
    "speed": {"m/s": 1.0, "km/h": 1 / 3.6, "mph": 0.44704, "kn": 1852 / 3600, "ft/s": 0.3048},
    "angle": {"rad": 1.0, "deg": math.pi / 180, "rev": 2 * math.pi},
    "torque": {"nm": 1.0, "kgcm": G0 / 100, "ozin": 0.0070615518, "lbfin": 0.1129848290},
}
_TEMP = {"c", "k", "f"}


def convert_units(value: float, from_unit: str, to_unit: str) -> Dict[str, Any]:
    v = _num("value", value)
    a, b = str(from_unit).strip().lower().replace(" ", ""), str(to_unit).strip().lower().replace(" ", "")
    if a in _TEMP and b in _TEMP:
        kelvin = {"c": v + 273.15, "k": v, "f": (v - 32) * 5 / 9 + 273.15}[a]
        out = {"c": kelvin - 273.15, "k": kelvin, "f": (kelvin - 273.15) * 9 / 5 + 32}[b]
        if kelvin < 0:
            raise CalcError("temperature below absolute zero")
        return {"results": {"value": out, "unit": to_unit}, "formula": "temperature offset/scale conversion"}
    for kind, table in _UNITS.items():
        if a in table and b in table:
            return {"results": {"value": v * table[a] / table[b], "unit": to_unit, "quantity": kind},
                    "formula": "value x (from-factor / to-factor), both relative to the SI unit"}
    known = sorted({u for t in _UNITS.values() for u in t} | _TEMP)
    raise CalcError(f"cannot convert '{from_unit}' to '{to_unit}' (different quantities or unknown unit). Known: {', '.join(known)}")


# ------------------------------------------------------------------------------ sections
def section_properties(shape: str, **dims) -> Dict[str, Any]:
    """Area, second moment of area I (bending, about the horizontal centroidal axis), polar J, extreme-fibre distance c."""
    s = str(shape).lower()
    if s == "rectangle":
        b, h = _num("b", dims.get("b"), positive=True), _num("h", dims.get("h"), positive=True)
        area, i, j, c = b * h, b * h ** 3 / 12, b * h * (b * b + h * h) / 12, h / 2
        formula = "A=bh, I=bh^3/12 (h = depth in the bending direction), J~=bh(b^2+h^2)/12 (polar moment of area, not the torsion constant)"
    elif s == "circle":
        d = _num("d", dims.get("d"), positive=True)
        area, i, j, c = math.pi * d * d / 4, math.pi * d ** 4 / 64, math.pi * d ** 4 / 32, d / 2
        formula = "A=pi d^2/4, I=pi d^4/64, J=pi d^4/32"
    elif s == "hollow_circle":
        do, di = _num("d_outer", dims.get("d_outer"), positive=True), _num("d_inner", dims.get("d_inner"), nonneg=True)
        if di >= do:
            raise CalcError("'d_inner' must be smaller than 'd_outer'")
        area = math.pi * (do ** 2 - di ** 2) / 4
        i, j, c = math.pi * (do ** 4 - di ** 4) / 64, math.pi * (do ** 4 - di ** 4) / 32, do / 2
        formula = "A=pi(do^2-di^2)/4, I=pi(do^4-di^4)/64, J=pi(do^4-di^4)/32"
    else:
        raise CalcError("shape must be rectangle (b,h), circle (d) or hollow_circle (d_outer,d_inner)")
    return {"results": {"area_m2": area, "I_m4": i, "J_m4": j, "c_m": c, "section_modulus_m3": i / c}, "formula": formula,
            "assumptions": ["dimensions in metres"]}


# ------------------------------------------------------------------------------ beams
def beam(support: str, load: str, length: float, magnitude: float, E: float, I: float, position: float = None) -> Dict[str, Any]:
    """Statically determinate beams, small deflection, uniform EI.
    support: simply_supported | cantilever.  load: point (N) | udl (N/m).
    position = distance of a point load from the left support / the fixed end (default: midspan / free end)."""
    L, W = _num("length", length, positive=True), _num("magnitude", magnitude, positive=True)
    E, I = _num("E", E, positive=True), _num("I", I, positive=True)
    sup, ld = str(support).lower(), str(load).lower()
    EI = E * I
    warnings: List[str] = []
    if sup == "simply_supported" and ld == "point":
        a = L / 2 if position is None else _num("position", position, nonneg=True)
        if not 0 < a < L:
            raise CalcError("'position' must be strictly between the supports")
        b = L - a
        sm = min(a, b)
        res = {"reaction_left_N": W * b / L, "reaction_right_N": W * a / L, "max_moment_Nm": W * a * b / L,
               "deflection_under_load_m": W * a * a * b * b / (3 * EI * L),
               "max_deflection_m": W * sm * (L * L - sm * sm) ** 1.5 / (9 * math.sqrt(3) * L * EI)}
        formula = "R1=Pb/L, R2=Pa/L, Mmax=Pab/L, d_load=Pa^2b^2/(3EIL), dmax=Pb(L^2-b^2)^1.5/(9 sqrt3 L EI) (b = shorter segment)"
    elif sup == "simply_supported" and ld == "udl":
        res = {"reaction_left_N": W * L / 2, "reaction_right_N": W * L / 2, "max_moment_Nm": W * L * L / 8,
               "max_deflection_m": 5 * W * L ** 4 / (384 * EI)}
        formula = "R=wL/2, Mmax=wL^2/8, dmax=5wL^4/(384EI)"
    elif sup == "cantilever" and ld == "point":
        a = L if position is None else _num("position", position, positive=True)
        if a > L:
            raise CalcError("'position' cannot exceed the length")
        res = {"reaction_force_N": W, "max_moment_Nm": W * a,
               "max_deflection_m": W * a * a * (3 * L - a) / (6 * EI)}
        formula = "R=P, Mmax=Pa, dtip=Pa^2(3L-a)/(6EI) (a = load position from the wall; a=L gives PL^3/3EI)"
    elif sup == "cantilever" and ld == "udl":
        res = {"reaction_force_N": W * L, "max_moment_Nm": W * L * L / 2, "max_deflection_m": W * L ** 4 / (8 * EI)}
        formula = "R=wL, Mmax=wL^2/2, dtip=wL^4/(8EI)"
    else:
        raise CalcError("support must be simply_supported or cantilever; load must be point or udl")
    res["span_to_deflection_ratio"] = L / res["max_deflection_m"] if res["max_deflection_m"] else float("inf")
    if res["span_to_deflection_ratio"] < 250:
        warnings.append("deflection exceeds L/250, a common serviceability limit for floors; check the requirement for your use")
    return {"results": res, "formula": formula, "warnings": warnings,
            "assumptions": ["linear elastic", "small deflection", "uniform EI", "self-weight not included"]}


def bending_stress(moment: float, I: float, c: float) -> Dict[str, Any]:
    m, i, cc = _num("moment", moment), _num("I", I, positive=True), _num("c", c, positive=True)
    return {"results": {"sigma_Pa": m * cc / i}, "formula": "sigma = M c / I", "assumptions": ["elastic bending, c = distance to the extreme fibre"]}


def safety_factor(strength: float, stress: float) -> Dict[str, Any]:
    s, t = _num("strength", strength, positive=True), _num("stress", stress, positive=True)
    n = s / t
    return {"results": {"factor_of_safety": n}, "formula": "n = strength / stress",
            "warnings": ["factor of safety below 1: it fails"] if n < 1 else (["factor of safety below 1.5: little margin for most designs"] if n < 1.5 else [])}


def torsion_shear(torque: float, d: float, d_inner: float = 0.0) -> Dict[str, Any]:
    t = _num("torque", torque)
    do, di = _num("d", d, positive=True), _num("d_inner", d_inner, nonneg=True)
    if di >= do:
        raise CalcError("'d_inner' must be smaller than 'd'")
    j = math.pi * (do ** 4 - di ** 4) / 32
    return {"results": {"tau_max_Pa": t * (do / 2) / j, "J_m4": j}, "formula": "tau = T r / J, J = pi(d^4 - di^4)/32",
            "assumptions": ["circular shaft", "elastic", "no stress concentration"]}


def euler_buckling(E: float, I: float, length: float, end_condition: str = "pinned_pinned") -> Dict[str, Any]:
    k_table = {"pinned_pinned": 1.0, "fixed_free": 2.0, "fixed_pinned": 0.699, "fixed_fixed": 0.5}
    ec = str(end_condition).lower()
    if ec not in k_table:
        raise CalcError(f"end_condition must be one of {sorted(k_table)}")
    e, i, l = _num("E", E, positive=True), _num("I", I, positive=True), _num("length", length, positive=True)
    k = k_table[ec]
    return {"results": {"critical_load_N": math.pi ** 2 * e * i / (k * l) ** 2, "effective_length_factor_K": k},
            "formula": "Pcr = pi^2 E I / (K L)^2",
            "assumptions": ["slender column (check slenderness; Euler overestimates for short columns)", "ideal end conditions", "perfectly straight"]}


def plane_stress(sigma_x: float, sigma_y: float, tau_xy: float) -> Dict[str, Any]:
    sx, sy, t = _num("sigma_x", sigma_x), _num("sigma_y", sigma_y), _num("tau_xy", tau_xy)
    centre, radius = (sx + sy) / 2, math.hypot((sx - sy) / 2, t)
    s1, s2 = centre + radius, centre - radius
    return {"results": {"sigma_1_Pa": s1, "sigma_2_Pa": s2, "tau_max_Pa": radius,
                        "principal_angle_deg": math.degrees(0.5 * math.atan2(2 * t, sx - sy)),
                        "von_mises_Pa": math.sqrt(sx * sx - sx * sy + sy * sy + 3 * t * t)},
            "formula": "s1,2 = (sx+sy)/2 +/- sqrt(((sx-sy)/2)^2+t^2); tau_max = R; von Mises = sqrt(sx^2 - sx sy + sy^2 + 3t^2)",
            "assumptions": ["plane stress", "compression negative"]}


def thermal_expansion(length: float, alpha: float, delta_T: float) -> Dict[str, Any]:
    l, a, dt = _num("length", length, positive=True), _num("alpha", alpha), _num("delta_T", delta_T)
    return {"results": {"delta_L_m": a * l * dt}, "formula": "dL = alpha L dT", "assumptions": ["linear, constant alpha"]}


# ------------------------------------------------------------------------------ trusses
def _solve(a: List[List[float]], b: List[float]) -> List[float]:
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-10:
            raise CalcError("the structure is unstable or mis-specified (singular equations): check supports and that members form triangles")
        m[col], m[piv] = m[piv], m[col]
        for r in range(col + 1, n):
            f = m[r][col] / m[col][col]
            for c in range(col, n + 1):
                m[r][c] -= f * m[col][c]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (m[r][n] - sum(m[r][c] * x[c] for c in range(r + 1, n))) / m[r][r]
    return x


def truss(nodes: Dict[str, Tuple[float, float]], members: List[Tuple[str, str]], supports: Dict[str, str],
          loads: Dict[str, Tuple[float, float]]) -> Dict[str, Any]:
    """2-D statically determinate pin-jointed truss by the method of joints.
    supports: node -> 'pin' (Rx,Ry) | 'roller' (Ry only) | 'roller_x' (Rx only). loads: node -> (Fx, Fy) in N.
    Member force: tension positive."""
    names = list(nodes)
    if len(names) < 2 or not members:
        raise CalcError("need at least two nodes and one member")
    pos = {}
    for n, xy in nodes.items():
        if not (isinstance(xy, (list, tuple)) and len(xy) == 2):
            raise CalcError(f"node '{n}' must be (x, y)")
        pos[n] = (_num(f"{n}.x", xy[0]), _num(f"{n}.y", xy[1]))
    reactions: List[Tuple[str, str]] = []
    for n, kind in supports.items():
        if n not in pos:
            raise CalcError(f"support on unknown node '{n}'")
        k = str(kind).lower()
        if k == "pin":
            reactions += [(n, "x"), (n, "y")]
        elif k == "roller":
            reactions.append((n, "y"))
        elif k == "roller_x":
            reactions.append((n, "x"))
        else:
            raise CalcError("support type must be pin, roller or roller_x")
    for n in loads:
        if n not in pos:
            raise CalcError(f"load on unknown node '{n}'")
    m_count, r_count, n_count = len(members), len(reactions), len(names)
    if m_count + r_count != 2 * n_count:
        raise CalcError(f"not statically determinate: members + reactions = {m_count + r_count} but 2 x nodes = {2 * n_count}. "
                        "This calculator only solves determinate trusses.")
    index = {n: i for i, n in enumerate(names)}
    a = [[0.0] * (m_count + r_count) for _ in range(2 * n_count)]
    unit = []
    for k, (n1, n2) in enumerate(members):
        if n1 not in pos or n2 not in pos or n1 == n2:
            raise CalcError(f"member {k + 1} ({n1}-{n2}) uses unknown or identical nodes")
        dx, dy = pos[n2][0] - pos[n1][0], pos[n2][1] - pos[n1][1]
        length = math.hypot(dx, dy)
        if length == 0:
            raise CalcError(f"member {n1}-{n2} has zero length")
        ux, uy = dx / length, dy / length
        unit.append((ux, uy, length))
        a[2 * index[n1]][k] += ux
        a[2 * index[n1] + 1][k] += uy
        a[2 * index[n2]][k] -= ux
        a[2 * index[n2] + 1][k] -= uy
    for j, (n, axis) in enumerate(reactions):
        a[2 * index[n] + (0 if axis == "x" else 1)][m_count + j] += 1.0
    rhs = [0.0] * (2 * n_count)
    for n, (fx, fy) in loads.items():
        rhs[2 * index[n]] -= _num(f"load {n}.Fx", fx)
        rhs[2 * index[n] + 1] -= _num(f"load {n}.Fy", fy)
    x = _solve(a, rhs)
    forces = {f"{n1}-{n2}": x[k] for k, (n1, n2) in enumerate(members)}
    out_reactions = {f"{n}.R{axis}": x[m_count + j] for j, (n, axis) in enumerate(reactions)}
    return {"results": {"member_forces_N": forces,
                        "member_state": {k: ("tension" if v > 1e-9 else "compression" if v < -1e-9 else "zero-force") for k, v in forces.items()},
                        "reactions_N": out_reactions},
            "formula": "equilibrium of every joint (sum Fx = 0, sum Fy = 0) solved as one linear system; tension positive",
            "assumptions": ["pin joints", "loads only at joints", "members carry axial force only", "statically determinate"]}


# ------------------------------------------------------------------------------ atmosphere & flight
def isa_atmosphere(altitude_m: float) -> Dict[str, Any]:
    h = _num("altitude_m", altitude_m)
    if not 0 <= h <= 20000:
        raise CalcError("this implementation covers 0 to 20,000 m of the International Standard Atmosphere")
    if h <= 11000:
        t = 288.15 - 0.0065 * h
        p = 101325.0 * (t / 288.15) ** (G0 / (0.0065 * R_AIR))
    else:
        t = 216.65
        p = 22632.06 * math.exp(-G0 * (h - 11000.0) / (R_AIR * t))
    rho = p / (R_AIR * t)
    mu = 1.458e-6 * t ** 1.5 / (t + 110.4)
    return {"results": {"temperature_K": t, "pressure_Pa": p, "density_kg_m3": rho, "speed_of_sound_m_s": math.sqrt(GAMMA_AIR * R_AIR * t),
                        "dynamic_viscosity_Pa_s": mu},
            "formula": "ISA: T = 288.15 - 0.0065 h (to 11 km), isothermal 216.65 K above; p from hydrostatics + ideal gas; Sutherland viscosity",
            "assumptions": ["standard day", "dry air"]}


def lift(density: float, speed: float, area: float, cl: float) -> Dict[str, Any]:
    r, v, s, c = _num("density", density, positive=True), _num("speed", speed, nonneg=True), _num("area", area, positive=True), _num("cl", cl)
    return {"results": {"lift_N": 0.5 * r * v * v * s * c, "dynamic_pressure_Pa": 0.5 * r * v * v}, "formula": "L = 1/2 rho V^2 S CL"}


def stall_speed(weight_N: float, density: float, area: float, cl_max: float) -> Dict[str, Any]:
    w, r, s, c = _num("weight_N", weight_N, positive=True), _num("density", density, positive=True), _num("area", area, positive=True), _num("cl_max", cl_max, positive=True)
    return {"results": {"stall_speed_m_s": math.sqrt(2 * w / (r * s * c))}, "formula": "Vs = sqrt(2 W / (rho S CLmax))", "assumptions": ["level 1 g flight"]}


def reynolds_number(density: float, speed: float, length: float, viscosity: float) -> Dict[str, Any]:
    r, v, l, mu = _num("density", density, positive=True), _num("speed", speed, nonneg=True), _num("length", length, positive=True), _num("viscosity", viscosity, positive=True)
    return {"results": {"reynolds": r * v * l / mu}, "formula": "Re = rho V L / mu"}


# ------------------------------------------------------------------------------ orbital mechanics & rockets
def _body(name: str) -> Tuple[float, float]:
    b = str(name).lower()
    if b not in BODIES:
        raise CalcError(f"body must be one of {sorted(BODIES)}")
    return BODIES[b]


def circular_orbit(altitude_m: float, body: str = "earth") -> Dict[str, Any]:
    mu, rad = _body(body)
    r = rad + _num("altitude_m", altitude_m, nonneg=True)
    v = math.sqrt(mu / r)
    return {"results": {"radius_m": r, "speed_m_s": v, "period_s": 2 * math.pi * r / v, "escape_speed_m_s": math.sqrt(2) * v},
            "formula": "v = sqrt(mu/r), T = 2 pi sqrt(r^3/mu), v_esc = sqrt(2) v", "assumptions": ["two-body, spherical body, circular orbit"]}


def vis_viva(radius_m: float, semi_major_axis_m: float, body: str = "earth") -> Dict[str, Any]:
    mu, _ = _body(body)
    r, a = _num("radius_m", radius_m, positive=True), _num("semi_major_axis_m", semi_major_axis_m, positive=True)
    if r > 2 * a:
        raise CalcError("radius cannot exceed 2a for a bound orbit")
    return {"results": {"speed_m_s": math.sqrt(mu * (2 / r - 1 / a))}, "formula": "v = sqrt(mu (2/r - 1/a))"}


def hohmann(altitude_1_m: float, altitude_2_m: float, body: str = "earth") -> Dict[str, Any]:
    mu, rad = _body(body)
    r1, r2 = rad + _num("altitude_1_m", altitude_1_m, nonneg=True), rad + _num("altitude_2_m", altitude_2_m, nonneg=True)
    if r1 == r2:
        raise CalcError("the two orbits are the same")
    at = (r1 + r2) / 2
    v1, v2 = math.sqrt(mu / r1), math.sqrt(mu / r2)
    vt1, vt2 = math.sqrt(mu * (2 / r1 - 1 / at)), math.sqrt(mu * (2 / r2 - 1 / at))
    dv1, dv2 = abs(vt1 - v1), abs(v2 - vt2)
    return {"results": {"delta_v1_m_s": dv1, "delta_v2_m_s": dv2, "total_delta_v_m_s": dv1 + dv2,
                        "transfer_time_s": math.pi * math.sqrt(at ** 3 / mu), "transfer_semi_major_axis_m": at},
            "formula": "dv1 = |sqrt(mu(2/r1-1/a_t)) - sqrt(mu/r1)|, dv2 likewise at r2, t = pi sqrt(a_t^3/mu)",
            "assumptions": ["coplanar circular orbits", "impulsive burns"]}


def rocket_equation(isp_s: float, mass_initial_kg: float = None, mass_final_kg: float = None, delta_v_m_s: float = None) -> Dict[str, Any]:
    isp = _num("isp_s", isp_s, positive=True)
    ve = isp * G0
    if delta_v_m_s is None:
        m0, mf = _num("mass_initial_kg", mass_initial_kg, positive=True), _num("mass_final_kg", mass_final_kg, positive=True)
        if mf >= m0:
            raise CalcError("final mass must be less than initial mass")
        return {"results": {"delta_v_m_s": ve * math.log(m0 / mf), "mass_ratio": m0 / mf, "propellant_fraction": 1 - mf / m0,
                            "exhaust_velocity_m_s": ve},
                "formula": "dv = Isp g0 ln(m0/mf)", "assumptions": ["no gravity or drag losses (ideal rocket equation)"]}
    dv = _num("delta_v_m_s", delta_v_m_s, positive=True)
    ratio = math.exp(dv / ve)
    return {"results": {"mass_ratio": ratio, "propellant_fraction": 1 - 1 / ratio, "exhaust_velocity_m_s": ve},
            "formula": "m0/mf = exp(dv / (Isp g0))", "assumptions": ["no gravity or drag losses (ideal rocket equation)"]}


# ------------------------------------------------------------------------------ registry
CALCULATIONS: Dict[str, Tuple[Callable[..., Dict[str, Any]], str]] = {
    "convert_units": (convert_units, "convert_units(value, from_unit, to_unit): length, force, pressure, mass, energy, speed, angle, torque, temperature"),
    "section_properties": (section_properties, "section_properties(shape='rectangle'|'circle'|'hollow_circle', b,h | d | d_outer,d_inner): area, I, J, section modulus"),
    "beam": (beam, "beam(support='simply_supported'|'cantilever', load='point'|'udl', length, magnitude, E, I, position?): reactions, max moment, deflection"),
    "bending_stress": (bending_stress, "bending_stress(moment, I, c): sigma = Mc/I"),
    "safety_factor": (safety_factor, "safety_factor(strength, stress)"),
    "torsion_shear": (torsion_shear, "torsion_shear(torque, d, d_inner=0): shaft shear stress"),
    "euler_buckling": (euler_buckling, "euler_buckling(E, I, length, end_condition): critical column load"),
    "plane_stress": (plane_stress, "plane_stress(sigma_x, sigma_y, tau_xy): principal stresses, max shear, von Mises"),
    "thermal_expansion": (thermal_expansion, "thermal_expansion(length, alpha, delta_T)"),
    "truss": (truss, "truss(nodes={name:[x,y]}, members=[[n1,n2]], supports={node:'pin'|'roller'|'roller_x'}, loads={node:[Fx,Fy]}): member forces"),
    "isa_atmosphere": (isa_atmosphere, "isa_atmosphere(altitude_m): T, p, rho, speed of sound, viscosity (0-20 km)"),
    "lift": (lift, "lift(density, speed, area, cl)"),
    "stall_speed": (stall_speed, "stall_speed(weight_N, density, area, cl_max)"),
    "reynolds_number": (reynolds_number, "reynolds_number(density, speed, length, viscosity)"),
    "circular_orbit": (circular_orbit, "circular_orbit(altitude_m, body='earth'): speed, period, escape speed"),
    "vis_viva": (vis_viva, "vis_viva(radius_m, semi_major_axis_m, body='earth')"),
    "hohmann": (hohmann, "hohmann(altitude_1_m, altitude_2_m, body='earth'): transfer delta-v and time"),
    "rocket_equation": (rocket_equation, "rocket_equation(isp_s, mass_initial_kg, mass_final_kg) or (isp_s, delta_v_m_s)"),
}


def calculate(calc: str, **params) -> Dict[str, Any]:
    """Run a named calculation. Never raises: bad input comes back as {'status': 'error', 'message': ...}."""
    entry = CALCULATIONS.get(str(calc))
    if entry is None:
        return {"status": "error", "message": f"unknown calculation '{calc}'. Available: {', '.join(sorted(CALCULATIONS))}"}
    try:
        out = entry[0](**params)
    except CalcError as e:
        return {"status": "error", "calc": calc, "message": str(e)}
    except TypeError as e:
        return {"status": "error", "calc": calc, "message": f"wrong parameters ({e}). Usage: {entry[1]}"}
    except (OverflowError, ZeroDivisionError, ValueError) as e:
        return {"status": "error", "calc": calc, "message": f"numerical problem: {e}"}
    out.update({"status": "success", "calc": calc, "inputs": params})
    out.setdefault("warnings", [])
    return out


def catalog() -> str:
    return "\n".join(f"- {name}: {doc}" for name, (_, doc) in sorted(CALCULATIONS.items()))
