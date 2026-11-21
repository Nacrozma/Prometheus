"""Dependency-free SVG plots for engineering results (deterministic output, real data only).

    svg = line_plot([{"x": [...], "y": [...], "label": "measured", "style": "points"}], title=..., xlabel="t [s]", ylabel="h [m]")

Every plot states its axes with units; the caller passes the data a calculation produced. Styles: line, points,
dashed. Optional logarithmic axes. Colours follow Prometheus's solar palette, distinguishable in print.
"""
import html
import math
from typing import Dict, List, Optional, Sequence

from . import EngError

PALETTE = ["#f4b52c", "#4fb3d9", "#e5533d", "#7ac36a", "#b292ff", "#f7d98b", "#c97a2b", "#9aa4b8"]


def _ticks(lo: float, hi: float, n: int = 6) -> List[float]:
    if hi <= lo:
        hi = lo + (abs(lo) or 1.0)
    span = hi - lo
    raw = span / max(1, n - 1)
    mag = 10 ** math.floor(math.log10(raw))
    step = min((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw), default=10 * mag)
    start = math.ceil(lo / step - 1e-9) * step
    out = []
    v = start
    while v <= hi + 1e-9 * span:
        out.append(round(v, 12))
        v += step
    return out


def _fmt(v: float) -> str:
    if v == 0:
        return "0"
    a = abs(v)
    if a >= 1e5 or a < 1e-3:
        return f"{v:.2e}"
    return f"{v:.4g}"


def line_plot(series: Sequence[Dict], title: str = "", xlabel: str = "", ylabel: str = "", width: int = 720, height: int = 420,
              log_x: bool = False, log_y: bool = False, note: str = "") -> str:
    if not series:
        raise EngError("nothing to plot")
    pts = []
    for s in series:
        xs, ys = list(s.get("x", [])), list(s.get("y", []))
        if len(xs) != len(ys):
            raise EngError(f"series '{s.get('label', '')}': x and y lengths differ")
        for x, y in zip(xs, ys):
            if x is None or y is None or not (math.isfinite(x) and math.isfinite(y)):
                continue
            if (log_x and x <= 0) or (log_y and y <= 0):
                continue
            pts.append((x, y))
    if not pts:
        raise EngError("no finite points to plot")
    tx = (lambda v: math.log10(v)) if log_x else (lambda v: v)
    ty = (lambda v: math.log10(v)) if log_y else (lambda v: v)
    xs_t, ys_t = [tx(p[0]) for p in pts], [ty(p[1]) for p in pts]
    x0, x1, y0, y1 = min(xs_t), max(xs_t), min(ys_t), max(ys_t)
    if x1 == x0:
        x0, x1 = x0 - 1, x1 + 1
    if y1 == y0:
        y0, y1 = y0 - (abs(y0) * 0.1 or 1), y1 + (abs(y1) * 0.1 or 1)
    pad = 0.05 * (y1 - y0)
    y0, y1 = y0 - pad, y1 + pad
    L, R, Tm, B = 78, 24, 46, 58
    W, H = width - L - R, height - Tm - B

    def X(v):
        return L + (tx(v) - x0) / (x1 - x0) * W

    def Y(v):
        return Tm + H - (ty(v) - y0) / (y1 - y0) * H

    e = html.escape
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="12">',
           f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
           f'<text x="{width / 2}" y="22" text-anchor="middle" font-size="14" font-weight="600" fill="#1d1f24">{e(title)}</text>']
    def log_ticks(a, b):
        mult = (1, 2, 5) if b - a < 3 else (1,)
        return [m * 10 ** k for k in range(math.floor(a), math.ceil(b) + 1) for m in mult]

    xt = log_ticks(x0, x1) if log_x else _ticks(x0, x1)
    yt = log_ticks(y0, y1) if log_y else _ticks(y0, y1)
    for v in xt:
        if x0 - 1e-12 <= tx(v) <= x1 + 1e-12:
            px = X(v)
            out.append(f'<line x1="{px:.1f}" y1="{Tm}" x2="{px:.1f}" y2="{Tm + H}" stroke="#e6e8ee"/>')
            out.append(f'<text x="{px:.1f}" y="{Tm + H + 16}" text-anchor="middle" fill="#4a4f5c">{_fmt(v)}</text>')
    for v in yt:
        if y0 - 1e-12 <= ty(v) <= y1 + 1e-12:
            py = Y(v)
            out.append(f'<line x1="{L}" y1="{py:.1f}" x2="{L + W}" y2="{py:.1f}" stroke="#e6e8ee"/>')
            out.append(f'<text x="{L - 6}" y="{py + 4:.1f}" text-anchor="end" fill="#4a4f5c">{_fmt(v)}</text>')
    out.append(f'<rect x="{L}" y="{Tm}" width="{W}" height="{H}" fill="none" stroke="#9aa0ad"/>')
    out.append(f'<text x="{L + W / 2}" y="{height - 16}" text-anchor="middle" fill="#1d1f24">{e(xlabel)}</text>')
    out.append(f'<text transform="translate(18,{Tm + H / 2}) rotate(-90)" text-anchor="middle" fill="#1d1f24">{e(ylabel)}</text>')
    for i, s in enumerate(series):
        col = s.get("color") or PALETTE[i % len(PALETTE)]
        data = [(x, y) for x, y in zip(s.get("x", []), s.get("y", [])) if x is not None and y is not None and math.isfinite(x) and math.isfinite(y)
                and (not log_x or x > 0) and (not log_y or y > 0)]
        style = s.get("style", "line")
        if style == "points":
            for x, y in data:
                out.append(f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="3.2" fill="{col}" stroke="#1d1f24" stroke-width="0.5"/>')
        else:
            dash = ' stroke-dasharray="6 4"' if style == "dashed" else ""
            path = " ".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in data)
            out.append(f'<polyline fill="none" stroke="{col}" stroke-width="2"{dash} points="{path}"/>')
    lx, ly = L + 10, Tm + 12
    for i, s in enumerate(series):
        if not s.get("label"):
            continue
        col = s.get("color") or PALETTE[i % len(PALETTE)]
        out.append(f'<rect x="{lx}" y="{ly - 8 + i * 17}" width="14" height="4" fill="{col}"/>')
        out.append(f'<text x="{lx + 20}" y="{ly - 2 + i * 17}" fill="#1d1f24">{e(s["label"])}</text>')
    if note:
        out.append(f'<text x="{width - R}" y="{height - 4}" text-anchor="end" font-size="10" fill="#6b7180">{e(note)}</text>')
    out.append("</svg>")
    return "\n".join(out)
