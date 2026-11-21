"""Gesture-control stress testing.

Runs arm_gesture.GestureController over landmark sequences and measures what would reach the arm:

    jitter_mm          std of the commanded tip position while the hand is still (noise that leaks through)
    max_step_mm        largest change of the commanded tip between consecutive frames (a jump the arm must follow)
    lag_frames         frames from a step in hand position until the command covers 90 % of the step
    moved_while_lost   commanded-target changes while no usable hand was seen (must be 0)
    frames_to_stop     frames after the hand is lost until the controller stops sending (hold, then stop)
    sent_fraction      fraction of frames that produced a command

Sources: synthetic hands with controlled perturbations (noise, glitches, dropouts, occlusion, speed), and real
recordings (JSON lines written by `arm_demo.py --camera --record FILE --conditions "..."`) replayed through the same
metrics. Synthetic results show how the filter behaves on the perturbation it was given; only recordings of the real
MediaPipe tracker under real lighting say how it behaves in practice (pending: needs a webcam session).
"""
import json
import math
import random
from typing import Dict, Iterable, List, Optional, Sequence

import arm_gesture as gest

from . import EngError


def _noisy(hand, rng: random.Random, sigma: float):
    return [(x + rng.gauss(0, sigma), y + rng.gauss(0, sigma), z) for x, y, z in hand]


def scenario(name: str, frames: int = 240, seed: int = 0, noise: float = 0.0, speed: float = 1.0, dropout: float = 0.0,
             glitch: float = 0.0, occlusion: float = 0.0) -> List[Optional[list]]:
    """A synthetic hand sequence: settle (still), step right, sweep back, hold. Perturbations are per frame
    probabilities (dropout, glitch, occlusion) or a landmark noise std (image-width units)."""
    rng = random.Random(seed)
    out = []
    for i in range(frames):
        u = min(1.0, (i / frames) * speed)
        if u < 0.35:
            cx, cy = 0.40, 0.50
        elif u < 0.6:
            cx, cy = 0.55, 0.45                               # a step: for lag
        elif u < 0.85:
            v = (u - 0.6) / 0.25
            cx, cy = 0.55 - 0.15 * v, 0.45 + 0.05 * v
        else:
            cx, cy = 0.40, 0.50
        hand = gest.synthetic_hand(cx, cy, 0.13, 1.0)
        if noise:
            hand = _noisy(hand, rng, noise)
        r = rng.random()
        if r < dropout:
            out.append(None)
            continue
        if r < dropout + glitch:
            hand = gest.synthetic_hand(min(1.0, cx + 0.3), cy, 0.13, 1.0)       # tracker jumps to another blob
        if rng.random() < occlusion:
            hand = [list(p) for p in hand]
            hand[8] = [float("nan"), float("nan"), 0.0]                         # index tip occluded / NaN
        out.append(hand)
    return out


def evaluate(frames: Sequence[Optional[list]], controller: Optional[gest.GestureController] = None,
             step_frame: Optional[int] = None, still_range: Optional[tuple] = None) -> dict:
    ctrl = controller or gest.GestureController()
    cmds = [ctrl.step(f) for f in frames]
    targets = [c.target_m if c.send else None for c in cmds]
    sent = [t for t in targets if t is not None]
    steps = [math.dist(a, b) for a, b in zip(targets, targets[1:]) if a is not None and b is not None]
    moved_lost = 0
    last = None
    for f, c in zip(frames, cmds):
        usable = f is not None and gest.hand_features(f)[0] is not None
        if not usable and c.send and last is not None and c.target_m != last:
            moved_lost += 1
        if c.send:
            last = c.target_m
    out = {"frames": len(frames), "sent_fraction": len(sent) / max(1, len(frames)),
           "max_step_mm": 1000 * max(steps) if steps else 0.0, "moved_while_lost": moved_lost,
           "rejected_frames": ctrl.rejected_frames}
    if still_range:
        a, b = still_range
        pts = [t for t in targets[a:b] if t is not None]
        if len(pts) >= 3:
            m = [sum(p[i] for p in pts) / len(pts) for i in range(3)]
            out["jitter_mm"] = 1000 * math.sqrt(sum(math.dist(p, m) ** 2 for p in pts) / (len(pts) - 1))
    if step_frame is not None:
        before = next((t for t in reversed(targets[:step_frame]) if t is not None), None)
        after = [t for t in targets[step_frame:] if t is not None]
        if before is not None and after:
            final = after[min(len(after) - 1, 40)]
            total = math.dist(before, final)
            lag = None
            for k, t in enumerate(targets[step_frame:]):
                if t is not None and total > 1e-6 and math.dist(before, t) >= 0.9 * total:
                    lag = k
                    break
            out["lag_frames"] = lag
    # hand-loss behaviour: after the last usable frame, how long does it keep sending?
    lost_tail = 0
    for f, c in zip(reversed(frames), reversed(cmds)):
        if f is not None:
            break
        lost_tail += 1
    out["frames_to_stop_after_loss"] = None
    if lost_tail:
        tail = cmds[len(cmds) - lost_tail:]
        stop = next((k for k, c in enumerate(tail) if not c.send), None)
        out["frames_to_stop_after_loss"] = stop
    return out


def standard_suite(seed: int = 0) -> Dict[str, dict]:
    """The synthetic stress suite: each scenario isolates one perturbation."""
    n = 240
    step = int(0.35 * n)
    still = (40, step - 2)
    res = {
        "clean": evaluate(scenario("clean", n, seed), step_frame=step, still_range=still),
        "noise_0.003": evaluate(scenario("noise", n, seed, noise=0.003), step_frame=step, still_range=still),
        "noise_0.008": evaluate(scenario("noise", n, seed, noise=0.008), step_frame=step, still_range=still),
        "glitch_5pct": evaluate(scenario("glitch", n, seed, glitch=0.05), still_range=still),
        "dropout_10pct": evaluate(scenario("dropout", n, seed, dropout=0.10), still_range=still),
        "occlusion_10pct": evaluate(scenario("occlusion", n, seed, occlusion=0.10), still_range=still),
        "fast_2x": evaluate(scenario("fast", n, seed, speed=2.0), step_frame=int(0.35 * n / 2)),
    }
    lost = scenario("loss", 120, seed)[:80] + [None] * 40
    res["hand_lost"] = evaluate(lost)
    return res


def tuning_sweep(alphas=(0.15, 0.25, 0.35, 0.5, 0.7), deadbands=(0.0, 0.002, 0.004, 0.008), noise: float = 0.005, seed: int = 0) -> List[dict]:
    """Jitter (noise leak) against lag (responsiveness) for filter settings: the trade-off to tune on real data."""
    n = 240
    step = int(0.35 * n)
    frames = scenario("noise", n, seed, noise=noise)
    rows = []
    for a in alphas:
        for d in deadbands:
            r = evaluate(frames, gest.GestureController(alpha=a, deadband_m=d), step_frame=step, still_range=(40, step - 2))
            rows.append({"alpha": a, "deadband_m": d, "jitter_mm": r.get("jitter_mm"), "lag_frames": r.get("lag_frames"),
                         "max_step_mm": r["max_step_mm"]})
    return rows


def write_recording(path: str, frames: Iterable[Optional[list]], conditions: dict, fps: float = 30.0) -> int:
    """Store a real landmark session as JSON lines: a header with the conditions, then one frame per line."""
    if not isinstance(conditions, dict):
        raise EngError("conditions must be a dict (lighting, camera position, background, hand orientation, ...)")
    n = 0
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"schema": "prometheus.gesture_recording/1", "fps": fps, "conditions": conditions}) + "\n")
        for fr in frames:
            f.write(json.dumps({"landmarks": fr}) + "\n")
            n += 1
    return n


def read_recording(path: str) -> tuple:
    with open(path, encoding="utf-8") as f:
        header = json.loads(f.readline())
        if header.get("schema") != "prometheus.gesture_recording/1":
            raise EngError("not a Prometheus gesture recording")
        frames = [json.loads(line)["landmarks"] for line in f if line.strip()]
    return header, frames
