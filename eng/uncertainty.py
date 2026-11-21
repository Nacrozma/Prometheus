"""Uncertainty: measurement statistics, linear (GUM) propagation, Monte Carlo propagation, sensitivities.

Three different things are called "uncertainty" and are kept apart:
    measurement   scatter of repeated readings (Type A, s/sqrt(n)) and instrument limits (Type B, e.g. resolution/sqrt(12))
    model         what the equations leave out (assumptions); estimated by comparing models or with data, not by statistics here
    numerical     discretisation / iteration error (e.g. trajectory.convergence, solver tolerances)
This module handles the first, and propagates any stated input uncertainty through a model.

GUM (JCGM 100:2008) first-order propagation for uncorrelated inputs:
    u_y^2 = sum_i (c_i u_i)^2,  c_i = df/dx_i (central differences)
Expanded uncertainty U = k u_c with k from Student's t at the effective degrees of freedom (Welch-Satterthwaite).
Monte Carlo (JCGM 101:2008 idea): sample the inputs, evaluate the model, take percentiles. Needed when the model is
non-linear over the input spread; the two agree when it is linear.
"""
import math
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np

from . import EngError

# two-sided 95 % Student t quantiles
_T95 = [(1, 12.706), (2, 4.303), (3, 3.182), (4, 2.776), (5, 2.571), (6, 2.447), (7, 2.365), (8, 2.306), (9, 2.262), (10, 2.228),
        (12, 2.179), (15, 2.131), (20, 2.086), (25, 2.060), (30, 2.042), (40, 2.021), (60, 2.000), (120, 1.980)]


def t95(dof: float) -> float:
    if dof is None or dof == math.inf or dof > 1e6:
        return 1.960
    if dof < 1:
        raise EngError("degrees of freedom must be at least 1")
    for (d0, t0), (d1, t1) in zip(_T95, _T95[1:]):
        if d0 <= dof <= d1:
            w = (1 / dof - 1 / d0) / (1 / d1 - 1 / d0)                # interpolate in 1/dof
            return t0 + w * (t1 - t0)
    if dof < 1 + 1e-9:
        return _T95[0][1]
    w = (1 / dof - 1 / 120) / (0 - 1 / 120)
    return 1.980 + w * (1.960 - 1.980)


def measurement_summary(values: Sequence[float], resolution: Optional[float] = None, instrument_u: Optional[float] = None) -> dict:
    """Repeated readings of one quantity -> mean, Type A and B standard uncertainties, combined and expanded (95 %)."""
    v = [float(x) for x in values]
    if len(v) < 1 or not all(math.isfinite(x) for x in v):
        raise EngError("need at least one finite reading")
    n = len(v)
    mean = sum(v) / n
    s = math.sqrt(sum((x - mean) ** 2 for x in v) / (n - 1)) if n > 1 else 0.0
    uA = s / math.sqrt(n) if n > 1 else 0.0
    uB_parts = []
    if resolution is not None:
        if resolution <= 0:
            raise EngError("resolution must be positive")
        uB_parts.append(resolution / math.sqrt(12))
    if instrument_u is not None:
        if instrument_u < 0:
            raise EngError("instrument uncertainty must not be negative")
        uB_parts.append(instrument_u)
    uB = math.sqrt(sum(u * u for u in uB_parts))
    uc = math.sqrt(uA * uA + uB * uB)
    if uc == 0:
        dof = math.inf
    elif uA == 0:
        dof = math.inf
    else:
        dof = uc ** 4 / (uA ** 4 / (n - 1))                         # Welch-Satterthwaite; Type B taken as exact
    k = t95(dof)
    warn = []
    if n < 3:
        warn.append("fewer than 3 readings: the scatter is poorly known")
    if not uB_parts:
        warn.append("no instrument uncertainty given: Type B is missing, the result is optimistic")
    return {"n": n, "mean": mean, "std": s, "u_typeA": uA, "u_typeB": uB, "u_combined": uc, "dof_effective": dof,
            "coverage_factor_k95": k, "expanded_U95": k * uc, "warnings": warn}


def _call(f: Callable[..., float], x: Dict[str, float]) -> float:
    y = f(**x)
    if not isinstance(y, (int, float)) or not math.isfinite(y):
        raise EngError("the model must return a finite number")
    return float(y)


def sensitivities(f: Callable[..., float], x: Dict[str, float], rel_step: float = 1e-6) -> Dict[str, float]:
    """c_i = df/dx_i by central differences (step relative to |x_i|, absolute 1e-9 for zero)."""
    out = {}
    for k, v in x.items():
        h = rel_step * abs(v) if v != 0 else 1e-9
        hi, lo = dict(x), dict(x)
        hi[k], lo[k] = v + h, v - h
        out[k] = (_call(f, hi) - _call(f, lo)) / (2 * h)
    return out


def propagate_linear(f: Callable[..., float], x: Dict[str, float], u: Dict[str, float]) -> dict:
    """GUM first-order propagation (uncorrelated inputs). Returns u_y, contributions and normalised sensitivities."""
    for k in u:
        if k not in x:
            raise EngError(f"uncertainty given for unknown input '{k}'")
        if u[k] < 0:
            raise EngError(f"uncertainty of '{k}' must not be negative")
    y = _call(f, x)
    c = sensitivities(f, x)
    terms = {k: (c[k] * u.get(k, 0.0)) ** 2 for k in x}
    uy = math.sqrt(sum(terms.values()))
    return {"y": y, "u_y": uy, "relative_u_y": uy / abs(y) if y else None, "sensitivity": c,
            "normalised_sensitivity": {k: c[k] * x[k] / y if y else None for k in x},
            "contribution_pct": {k: 100 * t / (uy * uy) if uy > 0 else 0.0 for k, t in terms.items()},
            "method": "GUM first order, uncorrelated inputs"}


def monte_carlo(f: Callable[..., float], x: Dict[str, float], u: Dict[str, float], n: int = 20000, seed: int = 0,
                distribution: Optional[Dict[str, str]] = None) -> dict:
    """Sample each input (normal with std u, or 'uniform' with half-width sqrt(3) u, same std), evaluate f."""
    if n < 100:
        raise EngError("use at least 100 samples")
    rng = np.random.default_rng(seed)
    dist = distribution or {}
    samples = {}
    for k, v in x.items():
        s = u.get(k, 0.0)
        if dist.get(k, "normal") == "uniform":
            a = math.sqrt(3) * s
            samples[k] = rng.uniform(v - a, v + a, n)
        else:
            samples[k] = rng.normal(v, s, n) if s > 0 else np.full(n, v)
    ys, failed = [], 0
    for i in range(n):
        try:
            ys.append(_call(f, {k: float(samples[k][i]) for k in x}))
        except (EngError, ValueError, ZeroDivisionError, OverflowError):
            failed += 1
    if len(ys) < n // 2:
        raise EngError(f"{failed} of {n} samples were invalid inputs for the model: the input spread is too wide")
    a = np.array(ys)
    return {"n": len(ys), "failed_samples": failed, "mean": float(a.mean()), "std": float(a.std(ddof=1)),
            "p2_5": float(np.percentile(a, 2.5)), "p50": float(np.percentile(a, 50)), "p97_5": float(np.percentile(a, 97.5)),
            "method": f"Monte Carlo, {len(ys)} samples, seed {seed}"}
