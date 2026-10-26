"""
gui_birth.py — the "birth of a star" startup animation for the Prometheus HUD.

The intro is a real loading screen, not a fake spinner:
  * The timeline walks through the stages of star formation —
      0.00-0.36  gravitational collapse of a molecular cloud
      0.24-0.56  protostar + accretion disk + bipolar jets
      0.56       HOLD POINT — if the speech model is still loading, the
                 protostar keeps swirling here until it's ready (capped)
      0.54-0.70  fusion ignition
      0.70       flash + shockwave
      0.70-1.00  the new star grows to full size and the nebula disperses
  * The HUD pre-loads the Whisper model in the background at startup, and
    calls BirthTimeline.mark_ready() when it finishes; the star only ignites
    once the thing it was "waiting for" is actually ready.

BirthTimeline is plain Python (no Qt/GL), so the whole state machine —
hold, skip, easing, finish — is unit-tested headless. The overlay shader is
drawn on top of the main solar shader with premultiplied-alpha blending:
dust occludes (alpha > 0) while glows add (alpha = 0, colour > 0).
"""

import math

BIRTH_VERTEX_SHADER = """
#version 330 core
layout (location = 0) in vec2 aPos;
void main() {
    gl_Position = vec4(aPos, 0.0, 1.0);
}
"""

BIRTH_FRAGMENT_SHADER = """
#version 330 core
out vec4 FragColor;

uniform vec2 u_resolution;
uniform float u_time;
uniform float u_birth;   // timeline position, 0..1

float hash(vec2 p) {
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
}

float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float a = hash(i);
    float b = hash(i + vec2(1.0, 0.0));
    float c = hash(i + vec2(0.0, 1.0));
    float d = hash(i + vec2(1.0, 1.0));
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}

float fbm(vec2 p) {
    float v = 0.0;
    float a = 0.5;
    mat2 m = mat2(0.8, 0.6, -0.6, 0.8);
    for (int i = 0; i < 5; i++) {
        v += a * noise(p);
        p = m * p * 2.0;
        a *= 0.5;
    }
    return v;
}

mat2 rot(float a) {
    float c = cos(a);
    float s = sin(a);
    return mat2(c, -s, s, c);
}

void main() {
    vec2 uv = (gl_FragCoord.xy - 0.5 * u_resolution.xy) / min(u_resolution.x, u_resolution.y);
    float t = u_birth;
    float r = length(uv);

    // ---- timeline weights -------------------------------------------------
    float collapse = smoothstep(0.00, 0.36, t);
    float proto    = smoothstep(0.24, 0.52, t);
    float ignite   = smoothstep(0.54, 0.70, t);
    float fx       = (t - 0.70) / 0.03;
    float flash    = exp(-fx * fx);
    float settle   = smoothstep(0.70, 1.00, t);
    float fadeOut  = 1.0 - smoothstep(0.84, 1.00, t);

    vec3 emit = vec3(0.0);

    // ---- 1. collapsing molecular cloud (occludes the starfield) -----------
    float cloudR = mix(0.95, 0.34, collapse) * (1.0 + 1.6 * settle);
    float swirl = u_time * 0.30 + collapse * 4.0;
    float twist = swirl * (0.35 + 0.65 / (0.12 + r * 3.2));   // inner gas spins faster
    vec2 q = rot(twist) * uv;
    float dustA = fbm(q * 3.0 + vec2(0.0, u_time * 0.04));
    float dustB = fbm(q * 6.5 - vec2(u_time * 0.05, 3.7));
    float dust = smoothstep(0.30, 0.85, dustA * 0.65 + dustB * 0.45);
    float rc = r / cloudR;
    float env = exp(-rc * rc * 1.8);
    float cloudAmt = mix(0.60, 1.0, collapse) * (1.0 - settle);
    float occl = clamp(dust * env * cloudAmt, 0.0, 0.92);
    vec3 dustCol = mix(vec3(0.16, 0.07, 0.30), vec3(0.62, 0.24, 0.10), collapse);
    dustCol = mix(dustCol, vec3(0.95, 0.55, 0.20), proto * exp(-r * 4.0));   // heated near the core

    // glittering motes spiralling inward with the gas
    vec2 sp = q * 26.0;
    vec2 sid = floor(sp);
    vec2 sg = fract(sp) - 0.5;
    float hh = hash(sid);
    float mote = 0.0;
    if (hh > 0.965) {
        vec2 off = (vec2(hash(sid + 1.3), hash(sid + 2.7)) - 0.5) * 0.5;
        float md = length(sg - off);
        mote = smoothstep(0.09, 0.0, md) * (0.5 + 0.5 * sin(u_time * 4.0 + hh * 40.0));
    }
    mote *= env * cloudAmt * (0.4 + collapse);
    emit += vec3(1.0, 0.80, 0.60) * mote * 0.9;

    // ---- 2. accretion disk (viewed nearly edge-on) ------------------------
    vec2 dv = vec2(uv.x, uv.y * 3.4);
    float dr = length(dv);
    float diskOut = mix(0.50, 0.20, collapse);
    float diskMask = smoothstep(0.04, 0.09, dr) * (1.0 - smoothstep(diskOut * 0.55, diskOut, dr));
    vec2 dq = rot(u_time * 1.3 / (dr * 6.0 + 0.6)) * dv;      // differential rotation, no atan seam
    float turb = fbm(dq * 9.0);
    float diskAmt = proto * (1.0 - smoothstep(0.70, 0.90, t));
    vec3 diskCol = mix(vec3(1.0, 0.86, 0.55), vec3(0.85, 0.22, 0.05), smoothstep(0.05, 0.42, dr));
    emit += diskCol * diskMask * (0.35 + 0.9 * turb) * diskAmt * 1.6;

    // ---- 3. bipolar jets ---------------------------------------------------
    float jetAmt = smoothstep(0.42, 0.60, t) * (1.0 - smoothstep(0.72, 0.90, t));
    float ay = abs(uv.y);
    float jw = 0.012 + ay * 0.06;
    float jx = uv.x / jw;
    float jet = exp(-jx * jx) * smoothstep(0.03, 0.12, ay) * exp(-ay * 2.4);
    jet *= 0.65 + 0.35 * sin(ay * 46.0 - u_time * 16.0);
    emit += vec3(0.55, 0.78, 1.0) * jet * jetAmt * 1.5;

    // ---- 4. protostar core -------------------------------------------------
    float pulse = 1.0 + 0.10 * sin(u_time * 3.0) * (1.0 - ignite);
    float coreR = mix(0.018, 0.055, ignite) * pulse;
    float core = exp(-(r * r) / (coreR * coreR));
    float halo = exp(-r * mix(9.0, 4.0, ignite));
    vec3 coreCol = mix(vec3(1.0, 0.30, 0.06), vec3(1.0, 0.92, 0.65), ignite);
    float coreAmt = smoothstep(0.20, 0.50, t) * (1.0 - smoothstep(0.86, 1.00, t));
    emit += coreCol * (core * 2.4 + halo * 0.45) * coreAmt;

    // ---- 5. ignition flash + lens spikes -----------------------------------
    float spikeH = exp(-abs(uv.y) * 55.0) * exp(-abs(uv.x) * 2.5);
    float spikeV = exp(-abs(uv.x) * 55.0) * exp(-abs(uv.y) * 2.5);
    emit += vec3(1.0, 0.95, 0.85) * flash * (exp(-r * 2.2) * 1.8 + 0.6 * spikeH + 0.6 * spikeV);

    // ---- 6. shockwave -------------------------------------------------------
    float sr = max(t - 0.70, 0.0) * 3.0;
    float swAmt = smoothstep(0.695, 0.71, t) * (1.0 - smoothstep(0.80, 0.97, t));
    float sx1 = (r - sr) / 0.02;
    float sx2 = (r - sr * 0.62) / 0.03;
    emit += vec3(1.0, 0.82, 0.55) * (exp(-sx1 * sx1) + 0.4 * exp(-sx2 * sx2)) * swAmt * 0.9;

    // ---- compose (premultiplied alpha: dust occludes, glow adds) -----------
    emit = emit / (1.0 + emit * 0.6);
    float a = occl * fadeOut;
    vec3 rgb = (dustCol * occl + emit) * fadeOut;
    FragColor = vec4(rgb, a);
}
"""

# --- timeline constants ---------------------------------------------------------
DURATION = 7.5       # seconds of animation time to traverse t = 0 -> 1
HOLD_T = 0.56        # protostar waits here if loading isn't finished
HOLD_MAX = 20.0      # never hold longer than this (seconds), ready or not
FAST_FORWARD = 6.0   # speed multiplier once the operator skips

BASE_ENERGY = 0.55   # matches SolarSunWidget.STATE_ENERGY[0] (idle)


def smoothstep(e0: float, e1: float, x: float) -> float:
    if e1 == e0:
        return 0.0 if x < e0 else 1.0
    t = max(0.0, min(1.0, (x - e0) / (e1 - e0)))
    return t * t * (3.0 - 2.0 * t)


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


class BirthTimeline:
    """Pure state machine for the intro. tick(dt) advances it; the widget reads
    .t / .scale / .energy each frame and feeds them to the shaders."""

    def __init__(self, duration: float = DURATION):
        self.duration = duration
        self.active = False
        self.ready = False
        self.fast = False
        self.clock = 0.0
        self.hold_elapsed = 0.0
        self.timed_out = False

    # -- control ---------------------------------------------------------------
    def start(self, ready: bool = False) -> None:
        self.active = True
        self.ready = ready
        self.fast = False
        self.clock = 0.0
        self.hold_elapsed = 0.0
        self.timed_out = False

    def mark_ready(self) -> None:
        self.ready = True

    def skip(self) -> None:
        if self.active:
            self.fast = True
            self.ready = True

    def tick(self, dt: float) -> bool:
        """Advance by dt seconds. Returns True on the frame the intro finishes."""
        if not self.active:
            return False
        hold_clock = HOLD_T * self.duration
        if not self.ready and not self.fast and self.clock >= hold_clock:
            self.hold_elapsed += dt
            self.clock = hold_clock
            if self.hold_elapsed >= HOLD_MAX:
                self.timed_out = True
                self.ready = True   # give up waiting; carry on
        else:
            self.clock += dt * (FAST_FORWARD if self.fast else 1.0)
        if self.clock >= self.duration:
            self.clock = self.duration
            self.active = False
            return True
        return False

    # -- derived values -----------------------------------------------------------
    @property
    def t(self) -> float:
        return max(0.0, min(1.0, self.clock / self.duration))

    @property
    def holding(self) -> bool:
        return (self.active and not self.ready and not self.fast
                and self.clock >= HOLD_T * self.duration - 1e-9)

    @property
    def scale(self) -> float:
        """Radius multiplier for the main star (0 = not born yet, 1 = full size)."""
        t = self.t
        early = smoothstep(0.52, 0.70, t) * 0.14
        s = smoothstep(0.70, 1.00, t)
        grow = 1.0 - (1.0 - s) ** 3          # ease-out cubic
        return early + grow * 0.86

    @property
    def energy(self) -> float:
        """Luminosity fed to the main shader: dark, ignition surge, settle to idle."""
        t = self.t
        fx = (t - 0.70) / 0.03
        flash = math.exp(-fx * fx)
        hot = smoothstep(0.50, 0.70, t) * 2.0 + 1.6 * flash
        return lerp(hot, BASE_ENERGY, smoothstep(0.70, 1.00, t))

    @property
    def phase_label(self) -> str:
        t = self.t
        if self.holding:
            return "AWAITING SPEECH CORE"
        if t < 0.30:
            return "GRAVITATIONAL COLLAPSE"
        if t < HOLD_T:
            return "PROTOSTAR ACCRETION"
        if t < 0.70:
            return "FUSION IGNITION"
        if t < 0.80:
            return "STELLAR FLASH"
        return "MAIN SEQUENCE ACHIEVED"
