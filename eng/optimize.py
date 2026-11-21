"""Design sweeps: mass against safety factor and deflection, with constraints and a Pareto front.

The evaluator for each candidate is an existing, validated calculation (engineering.beam / section properties or
eng.structures.truss_stiffness), so the sweep is only as good as that model and inherits its assumptions.

Problems:
    cantilever_section  a cantilever of length L with a tip load P; candidates are rectangular (b, h), round (d) or
                        round tube (d_outer, wall) sections in a material; mass, max bending stress, factor of safety
                        against yield, tip deflection
    truss_sizing        one truss geometry with every member given the same cross-section area A from a list (or each
                        member group its own area); mass, worst |stress|, factor of safety, max nodal displacement;
                        compressive members also get an Euler buckling factor for a solid round bar of that area

Output: every candidate with its constraint violations, the feasible ones, the best (lightest feasible), and the
Pareto front on (mass, safety factor): no other candidate is both lighter and safer.
"""
import itertools
import math
from typing import Any, Dict, Iterable, List, Optional, Sequence

import engineering

from . import EngError
from ._util import num
from . import structures

MATERIALS = {   # density kg/m^3, E Pa, yield Pa (typical handbook values; use your supplier's certificate for design)
    "steel_s275": (7850.0, 200e9, 275e6),
    "aluminium_6061_t6": (2700.0, 69e9, 276e6),
    "pla_printed": (1240.0, 3.5e9, 50e6),
    "petg_printed": (1270.0, 2.1e9, 45e6),
}


def pareto_front(rows: List[dict], minimise: str = "mass_kg", maximise: str = "safety_factor") -> List[dict]:
    """Non-dominated rows: no other row has lower (or equal) `minimise` and higher (or equal) `maximise` with one strict."""
    front = []
    for r in rows:
        dominated = any((o[minimise] <= r[minimise] and o[maximise] >= r[maximise]) and (o[minimise] < r[minimise] or o[maximise] > r[maximise])
                        for o in rows if o is not r)
        if not dominated:
            front.append(r)
    return sorted(front, key=lambda r: r[minimise])


def _material(material: str):
    if material not in MATERIALS:
        raise EngError(f"material must be one of {', '.join(MATERIALS)}")
    return MATERIALS[material]


def cantilever_section(length: float, load: float, material: str = "aluminium_6061_t6", shape: str = "rectangle",
                       sizes: Optional[Dict[str, Sequence[float]]] = None, min_safety_factor: float = 2.0,
                       max_deflection: Optional[float] = None) -> Dict[str, Any]:
    L, P = num("length", length, positive=True), num("load", load, positive=True)
    rho, E, sy = _material(material)
    nmin = num("min_safety_factor", min_safety_factor, positive=True)
    dmax = None if max_deflection is None else num("max_deflection", max_deflection, positive=True)
    defaults = {"rectangle": {"b": [0.005, 0.01, 0.015, 0.02], "h": [0.01, 0.02, 0.03, 0.04, 0.05]},
                "circle": {"d": [0.01, 0.015, 0.02, 0.025, 0.03, 0.04]},
                "tube": {"d_outer": [0.02, 0.03, 0.04, 0.05], "wall": [0.001, 0.002, 0.003, 0.005]}}
    if shape not in defaults:
        raise EngError("shape must be rectangle, circle or tube")
    grid = sizes or defaults[shape]
    keys = list(defaults[shape])
    for k in keys:
        if k not in grid or not grid[k]:
            raise EngError(f"sizes needs a list for '{k}'")
    rows = []
    for combo in itertools.product(*(grid[k] for k in keys)):
        dims = dict(zip(keys, (num(k, v, positive=True) for k, v in zip(keys, combo))))
        if shape == "tube":
            if 2 * dims["wall"] >= dims["d_outer"]:
                continue
            sec = engineering.section_properties("hollow_circle", d_outer=dims["d_outer"], d_inner=dims["d_outer"] - 2 * dims["wall"])["results"]
        else:
            sec = engineering.section_properties(shape, **dims)["results"]
        bm = engineering.beam("cantilever", "point", L, P, E, sec["I_m4"])["results"]
        sigma = bm["max_moment_Nm"] * sec["c_m"] / sec["I_m4"]
        row = {**{k: dims[k] for k in keys}, "mass_kg": rho * sec["area_m2"] * L, "max_stress_Pa": sigma, "safety_factor": sy / sigma,
               "tip_deflection_m": bm["max_deflection_m"]}
        viol = []
        if row["safety_factor"] < nmin:
            viol.append(f"safety factor {row['safety_factor']:.2f} < {nmin}")
        if dmax is not None and row["tip_deflection_m"] > dmax:
            viol.append(f"deflection {row['tip_deflection_m'] * 1000:.2f} mm > {dmax * 1000:.2f} mm")
        row["violations"] = viol
        row["feasible"] = not viol
        rows.append(row)
    if not rows:
        raise EngError("no valid candidate in the size grid")
    feasible = [r for r in rows if r["feasible"]]
    return {"problem": "cantilever_section", "inputs": {"length_m": L, "load_N": P, "material": material, "shape": shape, "sizes": grid,
                                                        "min_safety_factor": nmin, "max_deflection_m": dmax},
            "material_properties": {"density_kg_m3": rho, "E_Pa": E, "yield_Pa": sy, "source": "typical handbook values"},
            "candidates": rows, "feasible": feasible, "best": min(feasible, key=lambda r: r["mass_kg"]) if feasible else None,
            "pareto_front": pareto_front(rows),
            "assumptions": ["Euler-Bernoulli cantilever, tip point load", "linear elastic, yield criterion on max bending stress",
                            "self-weight neglected", "no buckling (lateral-torsional) or stress concentration"]}


def truss_sizing(nodes, members, supports, loads, areas: Iterable[float], material: str = "steel_s275",
                 min_safety_factor: float = 2.0, max_displacement: Optional[float] = None) -> Dict[str, Any]:
    rho, E, sy = _material(material)
    nmin = num("min_safety_factor", min_safety_factor, positive=True)
    dmax = None if max_displacement is None else num("max_displacement", max_displacement, positive=True)
    rows = []
    for A in areas:
        A = num("area", A, positive=True)
        sol = structures.truss_stiffness(nodes, members, supports, loads, E=E, A=A)["results"]
        lengths = {}
        for m in members:
            a, b = (m["nodes"] if isinstance(m, dict) else m)[:2]
            lengths[f"{a}-{b}"] = math.dist(nodes[a], nodes[b])
        mass = rho * A * sum(lengths.values())
        worst = max(abs(s) for s in sol["member_stress_Pa"].values())
        n_y = sy / worst if worst > 0 else math.inf
        r = math.sqrt(A / math.pi)
        I = math.pi * r ** 4 / 4
        n_b = math.inf
        for k, N in sol["member_forces_N"].items():
            if N < 0:
                n_b = min(n_b, math.pi ** 2 * E * I / lengths[k] ** 2 / -N)
        disp = max(math.hypot(*v) for v in sol["displacements_m"].values())
        sf = min(n_y, n_b)
        row = {"area_m2": A, "mass_kg": mass, "max_stress_Pa": worst, "n_yield": n_y, "n_buckling_round_bar": n_b, "safety_factor": sf,
               "max_displacement_m": disp}
        viol = []
        if sf < nmin:
            viol.append(f"safety factor {sf:.2f} < {nmin}" + (" (buckling governs)" if n_b < n_y else ""))
        if dmax is not None and disp > dmax:
            viol.append(f"displacement {disp * 1000:.2f} mm > {dmax * 1000:.2f} mm")
        row["violations"], row["feasible"] = viol, not viol
        rows.append(row)
    if not rows:
        raise EngError("give at least one area")
    feasible = [r for r in rows if r["feasible"]]
    return {"problem": "truss_sizing", "candidates": rows, "feasible": feasible,
            "best": min(feasible, key=lambda r: r["mass_kg"]) if feasible else None, "pareto_front": pareto_front(rows),
            "material_properties": {"density_kg_m3": rho, "E_Pa": E, "yield_Pa": sy, "source": "typical handbook values"},
            "assumptions": ["one area for every member", "pin-jointed, linear elastic", "Euler buckling of a pinned solid round bar for compression members"]}
