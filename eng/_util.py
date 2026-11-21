"""Shared input validation for the eng package."""
import math
from typing import Any

from . import EngError


def num(name: str, v: Any, positive: bool = False, nonneg: bool = False, lo: float = None, hi: float = None) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise EngError(f"'{name}' must be a number")
    v = float(v)
    if not math.isfinite(v):
        raise EngError(f"'{name}' must be finite")
    if positive and v <= 0:
        raise EngError(f"'{name}' must be greater than zero (got {v})")
    if nonneg and v < 0:
        raise EngError(f"'{name}' must not be negative (got {v})")
    if lo is not None and v < lo:
        raise EngError(f"'{name}' must be at least {lo} (got {v})")
    if hi is not None and v > hi:
        raise EngError(f"'{name}' must be at most {hi} (got {v})")
    return v


def result(results: dict, formula: str, assumptions: list, warnings: list = None, **extra) -> dict:
    """The common shape every calculator returns (matches engineering.py)."""
    out = {"results": results, "formula": formula, "assumptions": assumptions, "warnings": warnings or []}
    out.update(extra)
    return out
