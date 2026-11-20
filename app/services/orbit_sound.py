"""ORBIT's optional sound identity for Prometheus: short tones synthesised on the fly (no recorded or licensed
assets), quiet by design, off by default.

Rules: nothing plays unless the owner switched ORBIT sounds on; nothing plays while Prometheus is speaking (a
sound never covers a spoken reply); a cue that cannot be played is silently skipped (sound is decoration,
never needed to understand anything).
"""

from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional, Tuple

SR = 22050
# cue → list of (frequency Hz, start s, duration s, gain) partials; warm, low, short
CUES: Dict[str, List[Tuple[float, float, float, float]]] = {
    "enter": [(196.0, 0.0, 1.2, 0.5), (293.7, 0.25, 1.0, 0.35), (392.0, 0.5, 0.9, 0.25), (587.3, 0.75, 0.7, 0.12)],
    "panel": [(523.3, 0.0, 0.18, 0.25), (784.0, 0.04, 0.16, 0.12)],
    "connect": [(440.0, 0.0, 0.22, 0.2), (660.0, 0.08, 0.2, 0.14)],
    "select": [(659.3, 0.0, 0.08, 0.18)],
    "confirm": [(392.0, 0.0, 0.16, 0.3), (587.3, 0.12, 0.24, 0.26)],
    "milestone": [(261.6, 0.0, 1.1, 0.3), (329.6, 0.08, 1.0, 0.24), (392.0, 0.16, 0.95, 0.22), (523.3, 0.3, 0.9, 0.16)],
    "exit": [(392.0, 0.0, 0.5, 0.25), (261.6, 0.18, 0.6, 0.2)],
}


def synth(cue: str, volume: float = 0.5):
    """The cue as float32 samples in -1..1 (soft attack, exponential release; peak ≤ 0.35 × volume)."""
    import numpy as np

    parts = CUES[cue]
    length = max(s + d for _, s, d, _ in parts) + 0.05
    t = np.arange(int(SR * length)) / SR
    out = np.zeros_like(t)
    for f, start, dur, gain in parts:
        m = (t >= start) & (t < start + dur)
        tt = t[m] - start
        env = np.minimum(1.0, tt / 0.02) * np.exp(-3.2 * tt / dur)
        out[m] += gain * env * (np.sin(2 * math.pi * f * tt) + 0.15 * np.sin(4 * math.pi * f * tt))
    peak = float(np.max(np.abs(out))) or 1.0
    return (out / peak * 0.35 * max(0.0, min(1.0, volume))).astype("float32")


class Sounds:
    def __init__(self, enabled: Callable[[], bool], volume: Callable[[], float], speaking: Callable[[], bool], player: Optional[Callable] = None):
        self.enabled, self.volume, self.speaking = enabled, volume, speaking
        self.player = player
        self._cache: Dict[Tuple[str, float], object] = {}

    def play(self, cue: str) -> bool:
        if cue not in CUES or not self.enabled() or self.volume() <= 0 or self.speaking():
            return False
        try:
            key = (cue, round(self.volume(), 2))
            if key not in self._cache:
                self._cache[key] = synth(cue, self.volume())
            data = self._cache[key]
            if self.player is not None:
                self.player(data, SR)
            else:
                import sounddevice as sd

                sd.play(data, SR, blocking=False)
            return True
        except Exception:
            return False
