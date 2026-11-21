"""Direct-stiffness solvers for 2-D trusses and 2-D rigid frames (linear elastic, small displacement).

Truss element (2 DOF per node: u, v), axial only:
    k_local = EA/L [[1, -1], [-1, 1]],  K_global = T^T k_local T,  T = [[c, s, 0, 0], [0, 0, c, s]]
    member force N = EA/L (u2 - u1) . (c, s)   (tension positive), stress = N / A

Frame element (3 DOF per node: u, v, theta), Euler-Bernoulli beam + bar:
    axial EA/L; bending 12EI/L^3, 6EI/L^2, 4EI/L, 2EI/L; transformed with the 6x6 rotation matrix.
    Member uniformly distributed load w (local, perpendicular to the member, positive toward local +y) is applied
    through consistent (fixed-end) nodal loads [0, wL/2, wL^2/12, 0, wL/2, -wL^2/12]; member end forces add the
    fixed-end forces back, so end moments are exact for the load.

Solution: assemble K, partition into free (f) and restrained (s) DOF, solve K_ff u_f = F_f - K_fs u_s
(prescribed support settlements u_s allowed), reactions R = K_sf u_f + K_ss u_s - F_s (+ equivalent loads).
Statically indeterminate structures need nothing special: compatibility is built into the stiffness method.

Checks reported with every solution: global equilibrium (sum of forces and of moments of loads + reactions),
the degree of static indeterminacy, and the conditioning of K_ff. A mechanism (singular K_ff: missing supports or
an unstable member arrangement) is an error naming the free directions, never a silent large number.

Limitations: linear elastic, small displacements, no buckling or P-delta, no shear deformation (Timoshenko),
no member end releases (hinges inside frames), point loads only at nodes for trusses. This is a 2-D matrix
structural analysis tool, not a general finite-element package.
"""
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from . import EngError
from ._util import num

SUPPORT_DOF = {                              # restrained directions
    "pin": ("x", "y"), "roller": ("y",), "roller_x": ("x",), "fixed": ("x", "y", "r"), "free": (),
}


def _nodes(nodes: Dict[str, Sequence[float]]) -> Tuple[List[str], Dict[str, np.ndarray]]:
    if not isinstance(nodes, dict) or len(nodes) < 2:
        raise EngError("need at least two nodes as {name: [x, y]} in metres")
    pos = {}
    for n, xy in nodes.items():
        if not (isinstance(xy, (list, tuple)) and len(xy) == 2):
            raise EngError(f"node '{n}' must be [x, y]")
        pos[str(n)] = np.array([num(f"{n}.x", xy[0]), num(f"{n}.y", xy[1])])
    names = list(pos)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if np.linalg.norm(pos[a] - pos[b]) < 1e-12:
                raise EngError(f"nodes '{a}' and '{b}' are at the same position")
    return names, pos


def _member_list(members, E, A, I=None, frame=False) -> List[dict]:
    out = []
    if not isinstance(members, (list, tuple)) or not members:
        raise EngError("members must be a non-empty list")
    for k, m in enumerate(members):
        if isinstance(m, dict):
            ends = m.get("nodes")
            d = m
        elif isinstance(m, (list, tuple)) and len(m) >= 2:
            ends, d = (m[0], m[1]), {}
        else:
            raise EngError(f"member {k + 1}: use [node_a, node_b] or {{'nodes': [a, b], 'E': .., 'A': ..}}")
        if not (isinstance(ends, (list, tuple)) and len(ends) == 2):
            raise EngError(f"member {k + 1}: 'nodes' must be two node names")
        row = {"a": str(ends[0]), "b": str(ends[1]), "E": num(f"member {k + 1} E", d.get("E", E), positive=True),
               "A": num(f"member {k + 1} A", d.get("A", A), positive=True), "w": 0.0}
        if frame:
            row["I"] = num(f"member {k + 1} I", d.get("I", I), positive=True)
            row["c"] = d.get("c")
            row["w"] = num(f"member {k + 1} w", d.get("w", 0.0))
        out.append(row)
    return out


def _supports(supports: Dict[str, Any], names: List[str], frame: bool) -> Dict[str, Tuple[str, ...]]:
    out = {}
    for n, kind in (supports or {}).items():
        if str(n) not in names:
            raise EngError(f"support on unknown node '{n}'")
        if isinstance(kind, (list, tuple)):
            dirs = tuple(str(d) for d in kind)
        else:
            k = str(kind).lower()
            if k not in SUPPORT_DOF:
                raise EngError(f"support type must be one of {', '.join(SUPPORT_DOF)} (or a list of 'x', 'y', 'r')")
            dirs = SUPPORT_DOF[k]
        for d in dirs:
            if d not in ("x", "y", "r"):
                raise EngError(f"support direction '{d}' must be x, y or r")
            if d == "r" and not frame:
                raise EngError("trusses have no rotational degree of freedom: use pin, roller or roller_x")
        out[str(n)] = dirs
    if not out:
        raise EngError("the structure has no supports")
    return out


def _solve(K: np.ndarray, F: np.ndarray, fixed: List[int], settle: np.ndarray, dof_names: List[str]) -> Tuple[np.ndarray, float]:
    n = K.shape[0]
    free = [i for i in range(n) if i not in fixed]
    u = settle.copy()
    if free:
        Kff = K[np.ix_(free, free)]
        rhs = F[free] - (K[np.ix_(free, fixed)] @ settle[fixed] if fixed else 0.0)
        scale = np.max(np.abs(np.diag(Kff))) or 1.0
        w, v = np.linalg.eigh(Kff / scale)
        if w.min() < 1e-10:
            vec = v[:, int(np.argmin(w))]
            dirs = [dof_names[free[i]] for i in np.argsort(-np.abs(vec))[:3] if abs(vec[i]) > 0.2]
            raise EngError("the structure is a mechanism (singular stiffness): it can move freely along "
                           f"{', '.join(dirs)}. Add supports or members so it cannot move without deforming.")
        cond = float(w.max() / w.min())
        u[free] = np.linalg.solve(Kff, rhs)
    else:
        cond = 1.0
    return u, cond


# ------------------------------------------------------------------------------ truss
def truss_stiffness(nodes, members, supports, loads=None, E: float = 200e9, A: float = 1e-4,
                    settlements: Optional[Dict[str, Sequence[float]]] = None) -> Dict[str, Any]:
    """2-D pin-jointed truss by the direct stiffness method (determinate or indeterminate).
    nodes {name: [x, y]} m; members [[a, b]] or [{'nodes': [a, b], 'E': Pa, 'A': m^2}]; supports {node: 'pin'|'roller'|
    'roller_x'|['x','y']}; loads {node: [Fx, Fy]} N; settlements {node: [dx, dy]} m (prescribed support movement)."""
    names, pos = _nodes(nodes)
    mem = _member_list(members, E, A)
    sup = _supports(supports, names, frame=False)
    idx = {n: i for i, n in enumerate(names)}
    ndof = 2 * len(names)
    dof_names = [f"{n}.{d}" for n in names for d in ("x", "y")]
    K = np.zeros((ndof, ndof))
    geo = []
    for k, m in enumerate(mem):
        if m["a"] not in idx or m["b"] not in idx or m["a"] == m["b"]:
            raise EngError(f"member {k + 1} ({m['a']}-{m['b']}) uses unknown or identical nodes")
        d = pos[m["b"]] - pos[m["a"]]
        L = float(np.linalg.norm(d))
        c, s = d / L
        t = np.array([-c, -s, c, s])
        ke = m["E"] * m["A"] / L * np.outer(t, t)
        dofs = [2 * idx[m["a"]], 2 * idx[m["a"]] + 1, 2 * idx[m["b"]], 2 * idx[m["b"]] + 1]
        K[np.ix_(dofs, dofs)] += ke
        geo.append((dofs, t, L, m))
    F = np.zeros(ndof)
    for n, f in (loads or {}).items():
        if str(n) not in idx:
            raise EngError(f"load on unknown node '{n}'")
        if not (isinstance(f, (list, tuple)) and len(f) == 2):
            raise EngError(f"load on '{n}' must be [Fx, Fy]")
        F[2 * idx[str(n)]] += num(f"load {n}.Fx", f[0])
        F[2 * idx[str(n)] + 1] += num(f"load {n}.Fy", f[1])
    fixed = sorted(2 * idx[n] + (0 if d == "x" else 1) for n, dirs in sup.items() for d in dirs)
    settle = np.zeros(ndof)
    for n, dd in (settlements or {}).items():
        if str(n) not in sup:
            raise EngError(f"settlement on '{n}', which is not a support")
        for j, ax in enumerate(("x", "y")):
            if ax in sup[str(n)]:
                settle[2 * idx[str(n)] + j] = num(f"settlement {n}.{ax}", dd[j])
    u, cond = _solve(K, F, fixed, settle, dof_names)
    R_full = K @ u - F
    forces, stresses = {}, {}
    for dofs, t, L, m in geo:
        N = m["E"] * m["A"] / L * float(t @ u[dofs])
        key = f"{m['a']}-{m['b']}"
        forces[key], stresses[key] = N, N / m["A"]
    reactions = {dof_names[i]: float(R_full[i]) for i in fixed}
    sum_fx = float(sum(R_full[i] for i in fixed if i % 2 == 0) + F[0::2].sum())
    sum_fy = float(sum(R_full[i] for i in fixed if i % 2 == 1) + F[1::2].sum())
    mom = 0.0
    for i in range(len(names)):
        x, y = pos[names[i]]
        fx = F[2 * i] + (R_full[2 * i] if 2 * i in fixed else 0.0)
        fy = F[2 * i + 1] + (R_full[2 * i + 1] if 2 * i + 1 in fixed else 0.0)
        mom += x * fy - y * fx
    indet = len(mem) + len(fixed) - ndof
    scale = max(1.0, float(np.abs(F).sum()), float(np.abs(R_full[fixed]).sum()) if fixed else 1.0)
    warnings = []
    if cond > 1e10:
        warnings.append(f"stiffness matrix is ill-conditioned (condition number {cond:.1e}): check very different member stiffnesses or near-collinear members")
    return {"results": {"displacements_m": {n: (float(u[2 * i]), float(u[2 * i + 1])) for i, n in enumerate(names)},
                        "member_forces_N": forces, "member_stress_Pa": stresses,
                        "member_state": {k: ("tension" if v > 1e-9 * scale else "compression" if v < -1e-9 * scale else "zero-force") for k, v in forces.items()},
                        "reactions_N": reactions, "degree_of_indeterminacy": indet,
                        "equilibrium_residual": {"sum_Fx_N": sum_fx, "sum_Fy_N": sum_fy, "sum_M_Nm": float(mom)},
                        "condition_number": cond},
            "formula": "direct stiffness: k_e = EA/L t t^T (t = [-c,-s,c,s]); K u = F on free DOF; N = EA/L t.u_e (tension +)",
            "assumptions": ["pin joints, axial members", "linear elastic, small displacement", "loads at nodes only", "no buckling check"],
            "warnings": warnings}


# ------------------------------------------------------------------------------ frame
def _frame_k_local(E, A, I, L):
    a, b, c, d = E * A / L, 12 * E * I / L ** 3, 6 * E * I / L ** 2, E * I / L
    return np.array([[a, 0, 0, -a, 0, 0], [0, b, c, 0, -b, c], [0, c, 4 * d, 0, -c, 2 * d],
                     [-a, 0, 0, a, 0, 0], [0, -b, -c, 0, b, -c], [0, c, 2 * d, 0, -c, 4 * d]])


def _rot6(c, s):
    r = np.array([[c, s, 0], [-s, c, 0], [0, 0, 1.0]])
    T = np.zeros((6, 6))
    T[:3, :3], T[3:, 3:] = r, r
    return T


def frame(nodes, members, supports, loads=None, E: float = 200e9, A: float = 1e-3, I: float = 1e-6,
          settlements: Optional[Dict[str, Sequence[float]]] = None) -> Dict[str, Any]:
    """2-D rigid frame / continuous beam by the direct stiffness method.
    members [[a, b]] or [{'nodes': [a, b], 'E', 'A', 'I', 'c' (extreme-fibre distance, for stress), 'w' (UDL, N/m,
    local +y)}]; supports {node: 'fixed'|'pin'|'roller'|'roller_x'|['x','y','r']}; loads {node: [Fx, Fy, M]} (N, N m)."""
    names, pos = _nodes(nodes)
    mem = _member_list(members, E, A, I, frame=True)
    sup = _supports(supports, names, frame=True)
    idx = {n: i for i, n in enumerate(names)}
    ndof = 3 * len(names)
    dof_names = [f"{n}.{d}" for n in names for d in ("x", "y", "r")]
    K = np.zeros((ndof, ndof))
    F = np.zeros(ndof)
    geo = []
    for k, m in enumerate(mem):
        if m["a"] not in idx or m["b"] not in idx or m["a"] == m["b"]:
            raise EngError(f"member {k + 1} ({m['a']}-{m['b']}) uses unknown or identical nodes")
        d = pos[m["b"]] - pos[m["a"]]
        L = float(np.linalg.norm(d))
        c, s = d / L
        T = _rot6(c, s)
        kl = _frame_k_local(m["E"], m["A"], m["I"], L)
        dofs = [3 * idx[m["a"]] + j for j in range(3)] + [3 * idx[m["b"]] + j for j in range(3)]
        K[np.ix_(dofs, dofs)] += T.T @ kl @ T
        w = m["w"]
        fef = np.array([0.0, w * L / 2, w * L * L / 12, 0.0, w * L / 2, -w * L * L / 12])      # equivalent nodal loads (local)
        F[dofs] += T.T @ fef
        geo.append((dofs, T, kl, L, m, fef))
    P = np.zeros(ndof)                                   # applied nodal loads only (for the equilibrium check)
    for n, f in (loads or {}).items():
        if str(n) not in idx:
            raise EngError(f"load on unknown node '{n}'")
        if not (isinstance(f, (list, tuple)) and len(f) in (2, 3)):
            raise EngError(f"load on '{n}' must be [Fx, Fy] or [Fx, Fy, M]")
        for j, v in enumerate(f):
            P[3 * idx[str(n)] + j] += num(f"load {n}[{j}]", v)
    F += P
    fixed = sorted(3 * idx[n] + "xyr".index(d) for n, dirs in sup.items() for d in dirs)
    settle = np.zeros(ndof)
    for n, dd in (settlements or {}).items():
        if str(n) not in sup:
            raise EngError(f"settlement on '{n}', which is not a support")
        for j, ax in enumerate("xyr"):
            if ax in sup[str(n)] and j < len(dd):
                settle[3 * idx[str(n)] + j] = num(f"settlement {n}.{ax}", dd[j])
    u, cond = _solve(K, F, fixed, settle, dof_names)
    R_full = K @ u - F
    reactions = {dof_names[i]: float(R_full[i]) for i in fixed}
    member_out = {}
    max_stress = 0.0
    for dofs, T, kl, L, m, fef in geo:
        f_local = kl @ (T @ u[dofs]) - fef               # end forces on the member (local): [N1, V1, M1, N2, V2, M2]
        key = f"{m['a']}-{m['b']}"
        row = {"length_m": L, "N1": f_local[0], "V1": f_local[1], "M1": f_local[2], "N2": f_local[3], "V2": f_local[4], "M2": f_local[5],
               "axial_force_N": -f_local[0]}                 # tension positive
        if m["w"]:
            # sagging-positive moment along the member from the left free body: M(x) = -M1 + V1 x + w x^2/2
            xs = np.linspace(0, L, 401)
            Mx = -f_local[2] + f_local[1] * xs + m["w"] * xs ** 2 / 2
            row["max_moment_Nm"] = float(Mx[np.argmax(np.abs(Mx))])
        else:
            row["max_moment_Nm"] = float(max(-f_local[2], f_local[5], key=abs))      # linear between the ends
        if m.get("c") is not None:
            cc = num("c", m["c"], positive=True)
            sigma = abs(row["axial_force_N"]) / m["A"] + abs(row["max_moment_Nm"]) * cc / m["I"]
            row["max_normal_stress_Pa"] = sigma
            max_stress = max(max_stress, sigma)
        member_out[key] = {k: float(v) for k, v in row.items()}
    # equilibrium: applied nodal loads + member UDL resultants + reactions
    fx = float(P[0::3].sum() + sum(R_full[i] for i in fixed if i % 3 == 0))
    fy = float(P[1::3].sum() + sum(R_full[i] for i in fixed if i % 3 == 1))
    mz = 0.0
    for i, n in enumerate(names):
        x, y = pos[n]
        rx = R_full[3 * i] if 3 * i in fixed else 0.0
        ry = R_full[3 * i + 1] if 3 * i + 1 in fixed else 0.0
        rm = R_full[3 * i + 2] if 3 * i + 2 in fixed else 0.0
        mz += x * (P[3 * i + 1] + ry) - y * (P[3 * i] + rx) + P[3 * i + 2] + rm
    for dofs, T, kl, L, m, fef in geo:
        if m["w"]:
            d = pos[m["b"]] - pos[m["a"]]
            normal = np.array([-d[1], d[0]]) / L
            res = m["w"] * L * normal
            mid = (pos[m["a"]] + pos[m["b"]]) / 2
            fx += float(res[0])
            fy += float(res[1])
            mz += float(mid[0] * res[1] - mid[1] * res[0])
    indet = 3 * len(mem) + len(fixed) - ndof
    warnings = [f"stiffness matrix is ill-conditioned (condition number {cond:.1e})"] if cond > 1e12 else []
    return {"results": {"displacements": {n: {"ux_m": float(u[3 * i]), "uy_m": float(u[3 * i + 1]), "rot_rad": float(u[3 * i + 2])} for i, n in enumerate(names)},
                        "reactions": reactions, "members": member_out, "degree_of_indeterminacy": indet,
                        "max_normal_stress_Pa": max_stress or None,
                        "equilibrium_residual": {"sum_Fx_N": fx, "sum_Fy_N": fy, "sum_M_Nm": float(mz)}, "condition_number": cond},
            "formula": "direct stiffness, Euler-Bernoulli frame element (EA/L, 12EI/L^3, 6EI/L^2, 4EI/L, 2EI/L); UDL by consistent "
                       "nodal loads; member end forces f = k_local T u - f_fixed_end",
            "assumptions": ["rigid joints", "linear elastic, small displacement", "Euler-Bernoulli (no shear deformation)",
                            "no P-delta / buckling", "no member end releases"],
            "warnings": warnings}
