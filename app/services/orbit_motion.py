"""ORBIT's animation state engine for Prometheus (plain Python, tested; the painter reads it).

* `visual(state)` maps a real application state (the same names the avatar uses: IDLE, LISTENING, THINKING,
  PLANNING, RESEARCHING, BUILDING, RUNNING/EXECUTING, WARNING = waiting for approval, PAUSED, ADAPTING, SUCCESS,
  OFFLINE, ERROR, SPEAKING) to the parameters of the layered core: ring speed and tilt, particle flow, arcs,
  shield, pulse, tone. Unknown states fall back to IDLE: the engine never invents activity.
* `Settings` holds the owner's visual preferences (intensity, particle density, depth, camera, cinematic
  transitions, energy effects, reduced motion) and turns them into concrete budgets.
* `Effects` is a small queue of timed event effects (shockwave, pulse along a connection, materialise,
  dissolve, scan, celebrate) started by real events and aged by `tick`.
* `FrameMonitor` watches frame times and lowers the quality level when frames are too slow, so a weak GPU
  degrades gracefully instead of stuttering.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ring_speed (turns/min), tilt (deg spread between rings), flow (particle speed), inflow (+ toward the core,
# - outward), arcs (arc events per second), shield (outer shell alpha), pulse (core pulse Hz), tone, glow
_BASE = dict(ring_speed=1.2, tilt=18.0, flow=0.25, inflow=0.0, arcs=0.0, shield=0.10, pulse=0.18, tone="solar", glow=0.45, nodes=0.0, label="Idle")
STATES: Dict[str, Dict[str, object]] = {
    "IDLE": {},
    "LISTENING": dict(ring_speed=1.6, flow=0.5, inflow=1.0, shield=0.16, pulse=0.0, glow=0.55, label="Listening · microphone on"),
    "THINKING": dict(ring_speed=3.4, tilt=34.0, flow=0.9, arcs=0.4, shield=0.18, pulse=0.9, glow=0.7, nodes=0.5, label="Thinking"),
    "PLANNING": dict(ring_speed=2.6, tilt=28.0, flow=0.7, arcs=0.2, shield=0.16, pulse=0.6, glow=0.68, nodes=0.8, label="Planning"),
    "RESEARCHING": dict(ring_speed=2.8, tilt=40.0, flow=0.8, arcs=0.3, shield=0.14, pulse=0.5, tone="research", glow=0.62, nodes=1.0, label="Researching"),
    "BUILDING": dict(ring_speed=3.8, tilt=24.0, flow=1.0, arcs=0.8, shield=0.22, pulse=0.7, tone="forge", glow=0.8, nodes=0.7, label="Building"),
    "WORKING": dict(ring_speed=3.0, tilt=24.0, flow=0.8, arcs=0.5, shield=0.18, pulse=0.6, tone="forge", glow=0.72, nodes=0.5, label="Running a tool"),
    "RUNNING": dict(ring_speed=3.2, tilt=22.0, flow=0.9, arcs=0.6, shield=0.2, pulse=0.6, tone="forge", glow=0.75, nodes=1.0, label="Running the workflow"),
    "EXECUTING": dict(ring_speed=3.2, tilt=22.0, flow=0.9, arcs=0.6, shield=0.2, pulse=0.6, tone="forge", glow=0.75, nodes=1.0, label="Running the workflow"),
    "SPEAKING": dict(ring_speed=2.0, flow=0.6, inflow=-1.0, shield=0.2, pulse=0.0, glow=0.75, label="Speaking"),
    "WARNING": dict(ring_speed=0.3, tilt=8.0, flow=0.08, shield=0.32, pulse=0.35, tone="approval", glow=0.6, label="Waiting for your approval"),
    "PAUSED": dict(ring_speed=0.2, tilt=8.0, flow=0.05, shield=0.24, pulse=0.15, tone="approval", glow=0.4, label="Paused"),
    "ADAPTING": dict(ring_speed=4.2, tilt=46.0, flow=1.1, arcs=1.0, shield=0.2, pulse=1.1, tone="adapt", glow=0.8, label="Adapting"),
    "SUCCESS": dict(ring_speed=1.6, flow=0.4, inflow=-0.4, shield=0.18, pulse=0.3, glow=0.85, label="Done"),
    "OFFLINE": dict(ring_speed=0.15, tilt=6.0, flow=0.04, shield=0.04, pulse=0.0, tone="offline", glow=0.15, label="No provider"),
    "ERROR": dict(ring_speed=0.4, tilt=10.0, flow=0.1, shield=0.12, pulse=0.25, tone="error", glow=0.35, label="Something went wrong"),
}

#: colours per tone (r, g, b): solar identity first; approval champagne; errors a restrained red
TONES = {
    "solar": (244, 181, 44), "research": (247, 217, 139), "forge": (255, 138, 36), "approval": (247, 217, 139),
    "adapt": (255, 170, 60), "offline": (120, 124, 138), "error": (240, 110, 90),
}


def visual(state: str) -> Dict[str, object]:
    return {**_BASE, **STATES.get((state or "IDLE").upper(), {})}


INTENSITY = {"subtle": 0.45, "balanced": 0.75, "spectacular": 1.0}
DENSITY = {"low": 40, "medium": 90, "high": 160}
CAMERA = {"off": 0.0, "gentle": 0.012, "dynamic": 0.03}


@dataclass
class Settings:
    intensity: str = "spectacular"
    particles: str = "high"
    depth: str = "immersive"
    camera: str = "gentle"
    cinematic: bool = True
    energy: bool = True
    sound: bool = False
    volume: float = 0.5
    reduced_motion: bool = False

    @classmethod
    def from_store(cls, get) -> "Settings":
        def pick(key, allowed, default):
            v = get(key)
            return v if v in allowed else default

        vol = get("orbit_fx_volume")
        return cls(
            intensity=pick("orbit_fx_intensity", INTENSITY, "spectacular"), particles=pick("orbit_fx_particles", DENSITY, "high"),
            depth=pick("orbit_fx_depth", ("standard", "immersive"), "immersive"), camera=pick("orbit_fx_camera", CAMERA, "gentle"),
            cinematic=bool(get("orbit_fx_cinematic")), energy=bool(get("orbit_fx_energy")), sound=bool(get("orbit_fx_sound")),
            volume=max(0.0, min(1.0, float(vol))) if isinstance(vol, (int, float)) else 0.5, reduced_motion=bool(get("reduced_motion")),
        )

    def scale(self) -> float:
        return INTENSITY[self.intensity]

    def particle_count(self, quality: float = 1.0) -> int:
        if self.reduced_motion:
            return min(24, DENSITY[self.particles] // 4)
        return max(12, int(DENSITY[self.particles] * self.scale() * max(0.25, min(1.0, quality))))

    def ring_count(self) -> int:
        return {"subtle": 3, "balanced": 4, "spectacular": 5}[self.intensity]

    def animate(self) -> bool:
        return not self.reduced_motion

    def frame_interval_ms(self, quality: float = 1.0) -> int:
        """30 fps at full quality, slower when quality drops; no timer under reduced motion."""
        return 33 if quality >= 0.75 else 50 if quality >= 0.45 else 80


# ------------------------------------------------------------------ event effects

KINDS = {"shockwave": 1.4, "pulse": 1.1, "materialise": 0.7, "dissolve": 0.5, "scan": 1.2, "celebrate": 2.2, "arc": 0.35}


@dataclass
class Effect:
    kind: str
    age: float = 0.0
    life: float = 1.0
    target: str = ""  # a panel id, a connection "a>b", or "" for the core
    strength: float = 1.0

    @property
    def progress(self) -> float:
        return max(0.0, min(1.0, self.age / self.life))


@dataclass
class Effects:
    """Timed effects started by real events. Energy effects off → only structural ones (materialise, dissolve,
    scan) run, so panels still appear and vanish visibly but nothing flashes."""

    items: List[Effect] = field(default_factory=list)
    energy: bool = True
    limit: int = 40

    def start(self, kind: str, target: str = "", strength: float = 1.0) -> Optional[Effect]:
        if kind not in KINDS:
            raise ValueError(f"unknown effect {kind}")
        if not self.energy and kind in ("shockwave", "pulse", "celebrate", "arc"):
            return None
        e = Effect(kind, 0.0, KINDS[kind], target, max(0.0, min(1.5, strength)))
        self.items.append(e)
        del self.items[:-self.limit]
        return e

    def tick(self, dt: float) -> None:
        for e in self.items:
            e.age += max(0.0, dt)
        self.items = [e for e in self.items if e.age < e.life]

    def active(self, kind: Optional[str] = None) -> List[Effect]:
        return [e for e in self.items if kind is None or e.kind == kind]

    def clear(self) -> None:
        self.items.clear()


# real events → effects (what the page calls when something actually happened)
EVENT_EFFECTS = {
    "project.created": [("shockwave", ""), ("celebrate", "")],
    "plan.updated": [("shockwave", ""), ("scan", "plan")],
    "plan.approved": [("pulse", "core>plan"), ("shockwave", "")],
    "step.completed": [("pulse", "core>operations")],
    "workflow.completed": [("celebrate", ""), ("shockwave", "")],
    "file.written": [("pulse", "files>operations"), ("scan", "files")],
    "approval.requested": [("scan", "approvals")],
    "error": [("scan", "")],
}


def effects_for(event: str) -> List[tuple]:
    return list(EVENT_EFFECTS.get(event, []))


# ------------------------------------------------------------------ adaptive quality

@dataclass
class FrameMonitor:
    """Average frame time over a window; quality drops a step when frames are slow and recovers slowly."""

    window: int = 45
    slow_ms: float = 34.0
    fast_ms: float = 20.0
    quality: float = 1.0
    samples: List[float] = field(default_factory=list)

    def add(self, ms: float) -> float:
        self.samples.append(max(0.0, ms))
        if len(self.samples) >= self.window:
            avg = sum(self.samples) / len(self.samples)
            self.samples.clear()
            if avg > self.slow_ms:
                self.quality = max(0.25, round(self.quality - 0.25, 2))
            elif avg < self.fast_ms and self.quality < 1.0:
                self.quality = min(1.0, round(self.quality + 0.125, 3))
        return self.quality


# ------------------------------------------------------------------ particles (pure state, drawn by the page)

@dataclass
class Particle:
    angle: float
    radius: float  # in core radii
    speed: float
    size: float
    depth: float


def spawn(n: int, seed: int = 7) -> List[Particle]:
    rnd = random.Random(seed)
    return [Particle(rnd.uniform(0, math.tau), rnd.uniform(1.1, 3.2), rnd.uniform(0.4, 1.2), rnd.uniform(0.6, 2.2), rnd.uniform(0.3, 1.0)) for _ in range(n)]


def advance(ps: List[Particle], dt: float, flow: float, inflow: float) -> None:
    """Particles orbit; inflow > 0 draws them toward the core (listening), < 0 pushes them out (speaking)."""
    for p in ps:
        p.angle = (p.angle + dt * flow * p.speed * 0.6 / max(0.6, p.radius)) % math.tau
        p.radius += -inflow * dt * 0.35 * p.speed
        if p.radius < 1.05:
            p.radius = 3.2
        elif p.radius > 3.3:
            p.radius = 1.1
