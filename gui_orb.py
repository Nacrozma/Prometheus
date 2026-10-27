#!/usr/bin/env python3
import sys
import os
import re
import time
import math
import json
import queue
import threading
import asyncio
import io
import traceback
import html as _html
import numpy as np
import sounddevice as sd
import soundfile as sf
import edge_tts
import whisper

os.environ["QT_LOGGING_RULES"] = "qt.qpa.window=false"

from PyQt6.QtCore import (
    Qt, QTimer, QThread, QObject, pyqtSignal, QPropertyAnimation, QEasingCurve, QByteArray
)
from PyQt6.QtGui import (
    QFont, QSurfaceFormat, QShortcut, QKeySequence, QColor, QPainter, QPen, QDesktopServices
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QTextEdit, QTextBrowser, QLabel, QFrame, QPushButton, QProgressBar, QDialog,
    QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QMessageBox, QCheckBox,
    QSpinBox, QDialogButtonBox, QPlainTextEdit
)
from PyQt6.QtOpenGLWidgets import QOpenGLWidget

try:
    from OpenGL import GL
except ImportError:
    raise ImportError("PyOpenGL is required. Install via: pip install PyOpenGL PyOpenGL_accelerate")

try:
    from prometheus import (
        llm_router,             # shared rotating multi-key router (cost-ranked, auto-failover)
        SYSTEM_PROMPT,
        load_memory_context as get_memory_context,  # NOTE: not `load_memory` — that returns the
        TOOLS,                                        # raw dict, not the formatted context string.
        dispatch_tool,
        adaptation_engine,
        conscience_engine,
        build_context_block,   # auto memory + RAG retrieval for the current turn
        rag_store,              # used by the GUI's own /rag slash command
        tool_get_system_telemetry,
        tool_get_router_status,
        DANGEROUS_TOOLS,
    )
except ImportError as err:
    raise ImportError(f"Ensure 'prometheus.py' is in the same execution path. Details: {err}")
except RuntimeError as err:
    # prometheus.py builds the LLM router at import time and raises this when no
    # provider key is configured - say so plainly instead of a raw traceback.
    raise SystemExit(f"Prometheus could not start: {err}")

import prometheus as _prometheus_core  # PROVIDER_PRIORITY / default models are adjusted from the saved settings
from gui_config import AppConfig, parse_csv, parse_model_overrides
from gui_session import (
    load_session, save_session, sanitize_messages, trim_messages, cap_text, TOOL_RESULT_CHAR_CAP,
)
import gui_markdown as md
from gui_birth import BirthTimeline, BIRTH_VERTEX_SHADER, BIRTH_FRAGMENT_SHADER

# Constants
_HERE = os.path.dirname(os.path.abspath(__file__))
THOUGHT_FILE = os.path.join(_HERE, "prom_thought.txt")  # absolute: a relative name depended on the launch directory
DEFAULT_VOICE = "en-US-ChristopherNeural"
MAX_TOOL_ITERATIONS = 8  # hard cap so a tool-calling loop can't run forever
SESSION_FILE = os.path.join(_HERE, "session.json")
MAX_SESSION_MESSAGES = 80       # history kept on disk and re-sent each turn (never cuts a tool exchange)
MAX_CONSOLE_TOOL_CHARS = 4000   # one huge tool result must not freeze the console (it re-renders as a whole)
MAX_RESPONSE_TOKENS = 2000      # 1200 truncated long tool-call arguments mid-JSON
STREAM_EMIT_INTERVAL = 0.06     # seconds between live-markdown re-renders while streaming

# Cross-model fallback chain tried (in order) if the router's default model
# errors or is rate-limited. Only applies when router.provider == "openrouter".
# This is the built-in default; Settings -> Fallback Models overrides it
# per-install via gui_config.py without touching source.
FALLBACK_MODELS = [
    "openai/gpt-4o",
    "google/gemini-2.0-flash-001",
]

# Master HUD Palette
THEME = {
    "bg":          "#020204",
    "panel":       "rgba(8, 8, 14, 0.92)",
    "panel_alt":   "rgba(4, 4, 8, 0.85)",
    "border":      "rgba(255, 140, 0, 0.30)",
    "border_soft": "rgba(255, 140, 0, 0.15)",
    "amber":       "#FFB300",
    "amber_dim":   "#8A6200",
    "amber_glow":  "#FF8C00",
    "cyan":        "#00E5FF",
    "cobalt":      "#00BFFF",
    "mint":        "#00FFCC",
    "red":         "#FF3B3B",
    "text":        "#EAEAF2",
    "text_dim":    "#7C7C92",
}
# gui_markdown's renderer wants the same palette, under its own key names.
MD_THEME = dict(md.DEFAULT_THEME, **{
    "text": THEME["text"], "dim": THEME["text_dim"], "amber": THEME["amber"], "cyan": THEME["cyan"],
})


class _CrashRelay(QObject):
    """Qt widgets may only be touched from the GUI thread, but unhandled
    exceptions can arrive from worker / TTS / voice threads. The hook only emits
    this signal (queued across threads); the dialog is built in the GUI thread."""
    crashed = pyqtSignal(str)


def install_crash_handler(app: QApplication):
    """A crash anywhere otherwise kills the window with no message at all. This
    logs the full traceback to gui_crash.log and shows a copyable dialog instead
    of a silent disappearance - for the Qt thread AND for background threads."""
    log_path = os.path.join(_HERE, "gui_crash.log")
    relay = _CrashRelay(app)
    showing = []  # one dialog at a time: a repeating error must not stack dialogs

    def show_dialog(text: str):
        if showing:
            return
        showing.append(True)
        try:
            box = QMessageBox()
            box.setWindowTitle("Prometheus — Unhandled Error")
            box.setIcon(QMessageBox.Icon.Critical)
            box.setTextFormat(Qt.TextFormat.PlainText)
            box.setText("Something went wrong that wasn't caught cleanly. Prometheus is still running.")
            box.setDetailedText(text)
            box.setStandardButtons(QMessageBox.StandardButton.Ok)
            box.exec()
        except Exception:
            pass
        finally:
            showing.clear()

    relay.crashed.connect(show_dialog)

    def report(exc_type, exc_value, exc_tb):
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n{text}")
        except Exception:
            pass
        print(text, file=sys.stderr)
        relay.crashed.emit(text)

    sys.excepthook = report
    threading.excepthook = lambda args: report(args.exc_type, args.exc_value, args.exc_traceback)
    app._crash_relay = relay  # keep the relay alive for the life of the app


def _load_session() -> list:
    """Atomic-write / quarantine / repair logic lives in gui_session.py (testable without Qt)."""
    return load_session(SESSION_FILE)


def _save_session(messages: list):
    if not save_session(SESSION_FILE, messages):
        print("[Session Save Error]: could not write session.json")


# Provider priority and per-provider model overrides were stored by gui_config
# but nothing ever read them. These make them real: the defaults are captured
# once, so clearing a setting restores the original behaviour in the same run.
_DEFAULT_PROVIDER_PRIORITY = list(_prometheus_core.PROVIDER_PRIORITY)
_DEFAULT_MODELS = {name: client.default_model for name, client in llm_router._clients.items()}


def apply_router_settings(config: AppConfig) -> list:
    """Apply the saved provider priority and model overrides to the shared
    router. Returns plain-text notes about anything that had to be ignored."""
    notes = []
    wanted = config.get("provider_priority") or []
    known = [p for p in wanted if p in _prometheus_core.PROVIDER_ENDPOINTS]
    notes += [f"Ignored unknown provider '{p}' in provider priority." for p in wanted if p not in known]
    _prometheus_core.PROVIDER_PRIORITY[:] = known if known else _DEFAULT_PROVIDER_PRIORITY

    overrides = config.get("model_overrides") or {}
    for name, client in llm_router._clients.items():
        client.default_model = overrides.get(name) or _DEFAULT_MODELS[name]
    notes += [f"Model override for '{n}' ignored: no key is configured for that provider."
              for n in overrides if n not in llm_router._clients]
    return notes


# ==============================================================================
# ADVANCED SOLAR CORE & MAHORAGA COBALT SHADER (GLSL 330 CORE)
# ==============================================================================
FRAGMENT_SHADER = """
#version 330 core
out vec4 FragColor;

uniform vec2 u_resolution;
uniform float u_time;
uniform float u_audio;
uniform int u_state;        // 0: IDLE, 1: THINKING, 2: SPEAKING, 3: ADAPTING
uniform float u_state_mix;  // Smooth interpolation transition factor (0.0 to 1.0)
uniform float u_energy;     // Eased luminosity baseline
uniform float u_birth_scale; // 0 during the star-birth intro, ramps to 1

#define PI 3.14159265359

float hash(vec2 p) {
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
}

vec2 hash2(vec2 p) {
    p = vec2(dot(p, vec2(127.1, 311.7)), dot(p, vec2(269.5, 183.3)));
    return fract(sin(p) * 43758.5453);
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
    mat2 rot = mat2(0.8, 0.6, -0.6, 0.8);
    for (int i = 0; i < 5; i++) {
        v += a * noise(p);
        p = rot * p * 2.0;
        a *= 0.5;
    }
    return v;
}

float fluidPlasma(vec2 p, float t) {
    vec2 q = vec2(fbm(p + vec2(0.0, t * 0.08)), fbm(p + vec2(5.2, 1.3 - t * 0.1)));
    vec2 r = vec2(fbm(p + 3.5 * q + vec2(1.7, 9.2 - t * 0.12)), fbm(p + 3.5 * q + vec2(8.3, 2.8 + t * 0.08)));
    return fbm(p + 2.8 * r);
}

float solarGranules(vec2 uv, float t) {
    vec2 st = uv * 28.0;
    vec2 i_st = floor(st);
    vec2 f_st = fract(st);

    float min_dist = 1.0;
    for (int y = -1; y <= 1; y++) {
        for (int x = -1; x <= 1; x++) {
            vec2 neighbor = vec2(float(x), float(y));
            vec2 point = hash2(i_st + neighbor);
            point = 0.5 + 0.45 * sin(t * 1.5 + 6.2831 * point);
            vec2 diff = neighbor + point - f_st;
            min_dist = min(min_dist, length(diff));
        }
    }
    return smoothstep(0.0, 0.85, min_dist);
}

// Dark solar magnetic active regions (sunspots) with penumbra edge
float sunspots(vec2 uv, float t) {
    vec2 spotUV = uv * 4.5 + vec2(t * 0.03, t * 0.01);
    float n = fbm(spotUV);
    float spot = smoothstep(0.68, 0.78, n);
    float penumbra = smoothstep(0.62, 0.82, n);
    return (1.0 - spot * 0.85) * (1.0 - penumbra * 0.35);
}

// Solar prominence arcs expanding from rim
float solarProminence(vec2 uv, float angle, float r, float R, float t) {
    float arc = sin(angle * 6.0 + t * 0.8) * 0.5 + 0.5;
    arc *= pow(sin(angle * 3.0 - t * 0.4) * 0.5 + 0.5, 2.0);
    float height = R + 0.01 + arc * 0.08 * (1.0 + u_audio * 0.6);
    float dist = abs(r - height);
    return exp(-dist * 55.0) * arc;
}

// Rotating flare rays for realistic dynamic corona
float solarRays(vec2 uv, float t) {
    float ang = atan(uv.y, uv.x);
    float rays = sin(ang * 16.0 + t * 1.4) * 0.5 + 0.5;
    rays *= sin(ang * 8.0 - t * 0.6) * 0.5 + 0.5;
    return rays;
}

vec3 drawCircularStarfield(vec2 uv) {
    vec2 gridUV = uv * 90.0;
    vec2 id = floor(gridUV);
    vec2 gv = fract(gridUV) - 0.5;

    float n = hash(id);
    if (n > 0.962) {
        vec2 offset = vec2(hash(id + 1.0), hash(id + 2.0)) * 0.6 - 0.3;
        float dist = length(gv - offset);
        float radius = 0.025 + (n - 0.962) * 0.35;
        float starShape = smoothstep(radius, radius - 0.012, dist);
        float twinkle = sin(u_time * 2.8 + n * 6.28) * 0.35 + 0.65;
        float brightness = starShape * twinkle;
        vec3 tint = mix(vec3(0.75, 0.88, 1.0), vec3(1.0, 0.92, 0.80), hash(id + 7.0));
        return brightness * tint;
    }
    return vec3(0.0);
}

vec3 nebulaBackdrop(vec2 uv, float t) {
    float n = fbm(uv * 1.3 + vec2(t * 0.015, -t * 0.01));
    vec3 hue = mix(vec3(0.02, 0.01, 0.06), vec3(0.07, 0.02, 0.12), n);
    return hue * smoothstep(0.2, 0.95, n);
}

vec3 ACESFilm(vec3 x) {
    float a = 2.51;
    float b = 0.03;
    float c = 2.43;
    float d = 0.59;
    float e = 0.14;
    return clamp((x * (a * x + b)) / (x * (c * x + d) + e), 0.0, 1.0);
}

void main() {
    vec2 uv = (gl_FragCoord.xy - 0.5 * u_resolution.xy) / min(u_resolution.x, u_resolution.y);
    float r = length(uv);
    float angle = atan(uv.y, uv.x);
    float t = u_time * 0.22;

    float flicker = 0.0;
    if (u_state == 1) {
        flicker = sin(u_time * 4.5) * 0.14;
    } else if (u_state == 2) {
        flicker = u_audio * 0.95;
    } else if (u_state == 3) {
        flicker = sin(u_time * 9.0) * 0.28;
    }

    float luminosity = u_energy + flicker;
    float R = (0.31 + (u_audio * 0.025)) * u_birth_scale;
    vec3 col = vec3(0.0);

    // GOLDEN SOLAR PALETTE
    vec3 gold_deepCore   = vec3(0.55, 0.04, 0.00);
    vec3 gold_mainSurf   = vec3(1.00, 0.32, 0.01);
    vec3 gold_crestColor = vec3(1.00, 0.60, 0.05);
    vec3 gold_highIncand = vec3(1.00, 0.88, 0.35);
    vec3 gold_innerCor   = vec3(1.00, 0.50, 0.05);
    vec3 gold_softCor    = vec3(0.85, 0.22, 0.01);

    // COBALT BLUE MAHORAGA PALETTE
    vec3 blue_deepCore   = vec3(0.01, 0.06, 0.48);
    vec3 blue_mainSurf   = vec3(0.02, 0.28, 0.98);
    vec3 blue_crestColor = vec3(0.12, 0.60, 1.00);
    vec3 blue_highIncand = vec3(0.70, 0.92, 1.00);
    vec3 blue_innerCor   = vec3(0.05, 0.45, 1.00);
    vec3 blue_softCor    = vec3(0.01, 0.18, 0.65);

    float blendFactor = u_state_mix;

    vec3 deepCore       = mix(gold_deepCore, blue_deepCore, blendFactor);
    vec3 mainSurf       = mix(gold_mainSurf, blue_mainSurf, blendFactor);
    vec3 crestColor     = mix(gold_crestColor, blue_crestColor, blendFactor);
    vec3 highIncand     = mix(gold_highIncand, blue_highIncand, blendFactor);
    vec3 innerCoronaCol = mix(gold_innerCor, blue_innerCor, blendFactor);
    vec3 softCoronaCol  = mix(gold_softCor, blue_softCor, blendFactor);

    if (r < R) {
        float z = sqrt(R * R - r * r);
        vec3 norm = normalize(vec3(uv.x, uv.y, z));

        float latitude = asin(norm.y);
        float diffRotation = 1.0 - 0.25 * pow(sin(latitude), 2.0);

        vec2 sphereUV = vec2(atan(norm.x, norm.z) / PI, latitude / (PI * 0.5));
        vec2 animatedUV = sphereUV * 3.2 + vec2(t * 0.08 * diffRotation, t * 0.02);

        float plasma = fluidPlasma(animatedUV, t);
        float granules = solarGranules(animatedUV, t);
        float spots = sunspots(animatedUV, t);

        col = mix(deepCore, mainSurf, smoothstep(0.08, 0.55, plasma));
        col = mix(col, crestColor, granules * 0.42);
        col = mix(col, highIncand, smoothstep(0.65, 0.95, plasma));

        col *= spots;

        col += (deepCore * 0.85) * (1.0 - r / R);

        float limb = pow(z / R, 0.42);
        col *= mix(0.15, 1.0, limb);
        col *= luminosity;

    } else {
        float rotAngle = t * 0.01;
        mat2 rot2 = mat2(cos(rotAngle), -sin(rotAngle), sin(rotAngle), cos(rotAngle));
        col = nebulaBackdrop(uv, t) + drawCircularStarfield(rot2 * uv);

        float dist = r - R;

        float microRim = fbm(vec2(angle * 12.0, t * 1.6 + dist * 8.0));
        float innerGlow = exp(-dist * 48.0);
        float softAura  = exp(-dist * 13.5);
        float outerGlow = exp(-dist * 3.6);

        vec3 innerCorona = innerCoronaCol * innerGlow * 4.0 * luminosity;
        vec3 softCorona  = softCoronaCol * softAura * 1.7 * luminosity;
        vec3 ambientHalo = deepCore * outerGlow * 0.45 * luminosity;

        float edgeRim = smoothstep(R + 0.035, R, r) * (0.7 + 0.3 * microRim);
        vec3 prominenceRim = crestColor * edgeRim * innerGlow * luminosity;

        float rays = solarRays(uv, t) * exp(-dist * 8.5);
        vec3 rayColor = crestColor * rays * 0.55 * luminosity;

        float promArcs = solarProminence(uv, angle, r, R, t);
        vec3 arcColor = highIncand * promArcs * 2.2 * luminosity;

        col += innerCorona + softCorona + ambientHalo + prominenceRim + rayColor + arcColor;
    }

    // Lens diffraction cross-spikes for brilliant core flare
    float spikeHorizontal = exp(-abs(uv.y) * 45.0) * exp(-abs(uv.x) * 4.0);
    float spikeVertical   = exp(-abs(uv.x) * 45.0) * exp(-abs(uv.y) * 4.0);
    vec3 flareSpikes = highIncand * (spikeHorizontal + spikeVertical) * 0.18 * (luminosity - 0.3);
    col += max(vec3(0.0), flareSpikes);

    // Subtle edge vignette
    vec2 vigUV = gl_FragCoord.xy / u_resolution.xy;
    vigUV *= 1.0 - vigUV.yx;
    float vig = pow(vigUV.x * vigUV.y * 18.0, 0.25);
    col *= mix(0.50, 1.0, clamp(vig, 0.0, 1.0));

    col = ACESFilm(col * 1.05);
    col = pow(col, vec3(1.0 / 1.15));

    FragColor = vec4(col, 1.0);
}
"""

VERTEX_SHADER = """
#version 330 core
layout (location = 0) in vec2 aPos;
void main() {
    gl_Position = vec4(aPos, 0.0, 1.0);
}
"""


# ==============================================================================
# OPENGL WIDGET WITH INTERACTIVE OVERLAY
# ==============================================================================
class SolarSunWidget(QOpenGLWidget):
    STATE_ENERGY = {0: 0.55, 1: 1.08, 2: 1.60, 3: 1.50}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = 0
        self.state_mix = 0.0
        self.audio_level = 0.0
        self.energy = self.STATE_ENERGY[0]
        self.time = 0.0
        self.birth = BirthTimeline()
        self._birth_scale = 1.0
        self._birth_finished_cb = None
        self._last_tick = time.perf_counter()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance_frame)
        self.timer.start(16)

    def start_birth(self, ready: bool, on_finished=None):
        self._birth_finished_cb = on_finished
        self.birth.start(ready=ready)

    def skip_birth(self):
        self.birth.skip()

    def mark_birth_ready(self):
        self.birth.mark_ready()

    def mousePressEvent(self, event):
        if self.birth.active:
            self.birth.skip()
        super().mousePressEvent(event)

    def advance_frame(self):
        # Real elapsed time (clamped), not a fixed 16 ms: the 7.5 s intro and the
        # shader clock stay true to wall time when frames are slow or the timer jitters.
        now = time.perf_counter()
        dt = max(0.0, min(0.1, now - self._last_tick))
        self._last_tick = now
        self.time += dt

        if self.birth.active:
            finished = self.birth.tick(dt)
            self._birth_scale = self.birth.scale
            self.energy = self.birth.energy
            if finished and self._birth_finished_cb:
                self._birth_finished_cb()
        else:
            self._birth_scale = 1.0
            target_mix = 1.0 if self.state == 3 else 0.0
            self.state_mix += (target_mix - self.state_mix) * 0.08
            target_energy = self.STATE_ENERGY.get(self.state, 0.55)
            self.energy += (target_energy - self.energy) * 0.06

        self.update()

    def set_state_str(self, state_str: str):
        if state_str == "THINKING":
            self.state = 1
        elif state_str == "SPEAKING":
            self.state = 2
        elif state_str == "ADAPTING":
            self.state = 3
        else:
            self.state = 0

    def set_audio_level(self, level: float):
        self.audio_level = level

    def _compile_shader(self, shader_type, source):
        shader = GL.glCreateShader(shader_type)
        GL.glShaderSource(shader, source)
        GL.glCompileShader(shader)
        if not GL.glGetShaderiv(shader, GL.GL_COMPILE_STATUS):
            log = GL.glGetShaderInfoLog(shader).decode("utf-8", errors="ignore")
            raise RuntimeError(f"Shader compile error: {log}")
        return shader

    def _link_program(self, vert_src, frag_src):
        vert = self._compile_shader(GL.GL_VERTEX_SHADER, vert_src)
        frag = self._compile_shader(GL.GL_FRAGMENT_SHADER, frag_src)
        program = GL.glCreateProgram()
        GL.glAttachShader(program, vert)
        GL.glAttachShader(program, frag)
        GL.glLinkProgram(program)
        if not GL.glGetProgramiv(program, GL.GL_LINK_STATUS):
            log = GL.glGetProgramInfoLog(program).decode("utf-8", errors="ignore")
            raise RuntimeError(f"Shader link error: {log}")
        return program

    def initializeGL(self):
        GL.glClearColor(0.005, 0.005, 0.01, 1.0)

        self.program = self._link_program(VERTEX_SHADER, FRAGMENT_SHADER)
        self.birth_program = self._link_program(BIRTH_VERTEX_SHADER, BIRTH_FRAGMENT_SHADER)

        vertices = np.array([-1.0, -1.0, 1.0, -1.0, -1.0, 1.0, 1.0, 1.0], dtype=np.float32)

        self.vao = GL.glGenVertexArrays(1)
        vbo = GL.glGenBuffers(1)

        GL.glBindVertexArray(self.vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, vertices.nbytes, vertices, GL.GL_STATIC_DRAW)

        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, GL.GL_FALSE, 0, None)

        self.u_res = GL.glGetUniformLocation(self.program, "u_resolution")
        self.u_time = GL.glGetUniformLocation(self.program, "u_time")
        self.u_audio = GL.glGetUniformLocation(self.program, "u_audio")
        self.u_state = GL.glGetUniformLocation(self.program, "u_state")
        self.u_state_mix = GL.glGetUniformLocation(self.program, "u_state_mix")
        self.u_energy = GL.glGetUniformLocation(self.program, "u_energy")
        self.u_birth_scale = GL.glGetUniformLocation(self.program, "u_birth_scale")

        self.bu_res = GL.glGetUniformLocation(self.birth_program, "u_resolution")
        self.bu_time = GL.glGetUniformLocation(self.birth_program, "u_time")
        self.bu_birth = GL.glGetUniformLocation(self.birth_program, "u_birth")

    def _framebuffer_size(self):
        """gl_FragCoord is in DEVICE pixels but width()/height() are logical, so on
        a scaled display (125%/150%/200%) the shader's centre and aspect were wrong."""
        dpr = self.devicePixelRatioF()
        return float(self.width() * dpr), float(self.height() * dpr)

    def _release_gl_state(self):
        """Leave no program/VAO bound before QPainter draws: Qt's painter assumes a
        clean GL state and misrenders on some drivers otherwise."""
        GL.glUseProgram(0)
        GL.glBindVertexArray(0)

    def paintGL(self):
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)

        GL.glUseProgram(self.program)
        GL.glUniform2f(self.u_res, *self._framebuffer_size())
        GL.glUniform1f(self.u_time, self.time)
        GL.glUniform1f(self.u_audio, float(self.audio_level))
        GL.glUniform1i(self.u_state, self.state)
        GL.glUniform1f(self.u_state_mix, float(self.state_mix))
        GL.glUniform1f(self.u_energy, float(self.energy))
        GL.glUniform1f(self.u_birth_scale, float(self._birth_scale))
        GL.glBindVertexArray(self.vao)
        GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)

        if self.birth.active:
            # Premultiplied-alpha composite: the overlay shader already
            # bakes its own alpha into the emitted colour, so GL_ONE here
            # (not GL_SRC_ALPHA) avoids darkening it a second time.
            GL.glEnable(GL.GL_BLEND)
            GL.glBlendFunc(GL.GL_ONE, GL.GL_ONE_MINUS_SRC_ALPHA)
            GL.glUseProgram(self.birth_program)
            GL.glUniform2f(self.bu_res, *self._framebuffer_size())
            GL.glUniform1f(self.bu_time, self.time)
            GL.glUniform1f(self.bu_birth, float(self.birth.t))
            GL.glBindVertexArray(self.vao)
            GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
            GL.glDisable(GL.GL_BLEND)
            self._release_gl_state()
            self._draw_birth_caption()
        else:
            self._release_gl_state()
            self._draw_hud_overlay()

    def _draw_birth_caption(self):
        """The intro can hold for up to 20 s waiting on the speech model; say what
        it is doing and how to skip, instead of an unexplained wait."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        w, h = self.width(), self.height()
        align = int(Qt.AlignmentFlag.AlignHCenter)
        painter.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        painter.setPen(QPen(QColor(255, 179, 0, 190)))
        painter.drawText(0, h - 48, w, 18, align, self.birth.phase_label)
        painter.setFont(QFont("Consolas", 8))
        painter.setPen(QPen(QColor(255, 255, 255, 110)))
        painter.drawText(0, h - 30, w, 16, align, "ESC or click to skip")
        painter.end()

    def _draw_hud_overlay(self):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w // 2, h // 2

        color_amber = QColor(255, 179, 0, 120)
        color_cobalt = QColor(0, 191, 255, 140)
        active_color = color_cobalt if self.state == 3 else color_amber

        pen = QPen(active_color, 1, Qt.PenStyle.DashLine)
        painter.setPen(pen)

        r_reticle = min(w, h) * 0.28
        painter.drawEllipse(int(cx - r_reticle), int(cy - r_reticle), int(r_reticle * 2), int(r_reticle * 2))

        pen_solid = QPen(active_color, 1.5)
        painter.setPen(pen_solid)
        corner_len = 18

        painter.drawLine(20, 20, 20 + corner_len, 20)
        painter.drawLine(20, 20, 20, 20 + corner_len)
        painter.drawLine(w - 20, 20, w - 20 - corner_len, 20)
        painter.drawLine(w - 20, 20, w - 20, 20 + corner_len)
        painter.drawLine(20, h - 20, 20 + corner_len, h - 20)
        painter.drawLine(20, h - 20, 20, h - 20 - corner_len)
        painter.drawLine(w - 20, h - 20, w - 20 - corner_len, h - 20)
        painter.drawLine(w - 20, h - 20, w - 20, h - 20 - corner_len)

        painter.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        painter.setPen(QPen(QColor(255, 255, 255, 160)))
        painter.drawText(30, 36, "SOLAR CORE TELEMETRY // STELLAR CONVECTION ACTIVE")

        temp_str = "CORE TEMP: 5,778 K | ROTATION: 25.38d" if self.state != 3 else "CORE TEMP: 14,200 K | MAHORAGA ADAPTATION"
        painter.drawText(30, 52, temp_str)

        bar_count = 24
        bar_width = 4
        bar_gap = 3
        start_x = cx - ((bar_count * (bar_width + bar_gap)) // 2)
        base_y = h - 35

        for i in range(bar_count):
            wave_val = math.sin(self.time * 6.0 + i * 0.4) * 0.5 + 0.5
            bar_h = 4 + int((wave_val * 0.3 + self.audio_level * 0.7) * 28)
            x = start_x + i * (bar_width + bar_gap)
            painter.fillRect(x, base_y - bar_h, bar_width, bar_h, active_color)

        painter.end()


# ==============================================================================
# AUDIO PIPELINE: STT & TTS & BACKGROUND THOUGHTS
# ==============================================================================
class WhisperVoiceThread(QThread):
    transcription_done = pyqtSignal(str)
    status_signal = pyqtSignal(str)
    audio_level_signal = pyqtSignal(float)

    def __init__(self, sample_rate=16000):
        super().__init__()
        self.sample_rate = sample_rate
        self.is_recording = False
        self.audio_data = []
        self._model = None
        self._model_lock = threading.Lock()

    def _get_model(self):
        with self._model_lock:
            if self._model is None:
                self.status_signal.emit("LOADING WHISPER MODEL...")
                self._model = whisper.load_model("base")
            return self._model

    def preload_model(self):
        """Load the model ahead of time (e.g. during the startup animation)
        so the first mic press doesn't stall for several seconds. Guarded
        by the same lock _get_model() uses, so a recording that starts
        mid-preload just waits for that same load instead of double-loading."""
        self._get_model()

    MIN_SECONDS = 0.35  # shorter is a stray click, and Whisper invents text for near-silence

    def start_recording(self) -> bool:
        """False if the previous recording is still being transcribed: start() on a
        running QThread does nothing, so the UI would show REC while recording nothing."""
        if self.isRunning():
            self.status_signal.emit("STILL TRANSCRIBING - TRY AGAIN IN A MOMENT")
            return False
        self.audio_data = []
        self.is_recording = True
        self.start()
        return True

    def stop_recording(self):
        self.is_recording = False

    def run(self):
        try:
            model = self._get_model()
        except Exception as e:
            self.is_recording = False
            self.status_signal.emit(f"SPEECH MODEL ERROR: {e}")
            return
        self.status_signal.emit("LISTENING...")

        def callback(indata, frames, time_info, status):
            if self.is_recording:
                self.audio_data.append(indata.copy())
                rms = np.sqrt(np.mean(indata**2)) if len(indata) > 0 else 0.0
                norm_amp = float(np.clip(rms * 5.5, 0.0, 1.0))
                self.audio_level_signal.emit(norm_amp)

        try:
            with sd.InputStream(samplerate=self.sample_rate, channels=1, callback=callback):
                while self.is_recording:
                    self.msleep(40)
        except Exception as e:  # no microphone, device busy, permission denied...
            self.is_recording = False
            self.audio_level_signal.emit(0.0)
            self.status_signal.emit(f"MICROPHONE ERROR: {e}")
            return

        self.audio_level_signal.emit(0.0)
        if not self.audio_data:
            return

        audio_np = np.concatenate(self.audio_data, axis=0).flatten().astype(np.float32)
        if len(audio_np) < self.sample_rate * self.MIN_SECONDS:
            self.status_signal.emit("RECORDING TOO SHORT - IGNORED")
            return

        self.status_signal.emit("TRANSCRIBING AUDIO...")
        try:
            result = model.transcribe(audio_np)
            text = result.get("text", "").strip()
            self.transcription_done.emit(text)
        except Exception as e:
            self.status_signal.emit(f"STT ERROR: {e}")


class ModelPreloadThread(QThread):
    """Loads the Whisper model in the background at startup. The star-birth
    intro's hold point waits on this thread's `ready` signal — the star
    doesn't ignite until the speech core is actually usable, or the hold
    timeout is reached, whichever comes first."""
    ready = pyqtSignal()

    def __init__(self, voice_thread: WhisperVoiceThread):
        super().__init__()
        self.voice_thread = voice_thread

    def run(self):
        try:
            self.voice_thread.preload_model()
        except Exception as e:
            print(f"[Whisper Preload Error]: {e}")
        self.ready.emit()


class TTSManager:
    """
    MAJOR UPGRADE (speech quality): two problems with the old version —
    (1) speak() played each queued sentence with a fetch-then-play cycle,
    so if edge-tts took a moment to synthesize the next sentence, there was
    an audible gap between sentences; (2) each utterance was played back as
    many small 40ms chunks via repeated sd.play()/sd.wait() calls, and
    restarting playback that often can itself introduce clicks/micro-gaps.

    Fixed with a two-stage pipeline:
      - a synthesis thread pulls queued text and fetches audio for it,
        running AHEAD of playback (it doesn't wait for the current
        utterance to finish speaking before fetching the next one) — by
        the time one sentence finishes playing, the next is already
        synthesized and ready, so there's no network-wait gap between them.
      - a playback thread plays each fully-synthesized utterance as ONE
        continuous sounddevice.OutputStream (the documented callback +
        finished_callback pattern), instead of many small blocking calls —
        smooth audio for the duration of a sentence, with the audio level
        for the orb visualization still updated every callback block.
    Both stages are plain FIFO queues, so ordering is automatic — no
    reordering logic needed.
    """
    def __init__(self, voice: str = DEFAULT_VOICE, audio_callback=None, rate_percent: int = 0):
        self.voice = voice
        self.audio_callback = audio_callback
        self.is_speaking = False
        self.muted = False
        self.rate_percent = rate_percent
        self._text_queue: "queue.Queue[str]" = queue.Queue()
        self._audio_queue: "queue.Queue" = queue.Queue(maxsize=3)  # cap how far synthesis can run ahead
        threading.Thread(target=self._synthesis_worker, daemon=True).start()
        threading.Thread(target=self._playback_worker, daemon=True).start()

    @property
    def is_busy(self) -> bool:
        return self.is_speaking or not self._text_queue.empty() or not self._audio_queue.empty()

    def set_voice(self, voice: str):
        self.voice = voice

    def set_rate(self, percent: int):
        self.rate_percent = max(-50, min(100, int(percent)))

    def _rate_str(self) -> str:
        p = self.rate_percent
        return f"{'+' if p >= 0 else ''}{p}%"

    def speak(self, text: str):
        if self.muted or not text or not text.strip():
            return
        self._text_queue.put(text.strip())

    def set_muted(self, muted: bool):
        """Independent of Stop: Stop halts *generation*, this halts *speech*
        — clears anything queued and cuts off whatever's playing right now
        (the playback callback checks `muted` every audio block, so it
        stops within tens of milliseconds, not at the next sentence)."""
        self.muted = muted
        if muted:
            self._drain(self._text_queue)
            self._drain(self._audio_queue)

    @staticmethod
    def _drain(q: "queue.Queue"):
        while True:
            try:
                q.get_nowait()
                q.task_done()
            except queue.Empty:
                break

    def wait_until_idle(self):
        """Block the calling thread until every queued utterance has been
        both synthesized and played."""
        self._text_queue.join()
        self._audio_queue.join()

    def _synthesis_worker(self):
        while True:
            text = self._text_queue.get()
            try:
                data, fs = asyncio.run(self._synthesize(text))
                self._audio_queue.put((data, fs))
            except Exception as e:
                print(f"[TTS Synthesis Error]: {e}")
                self._audio_queue.put((None, None))
            finally:
                self._text_queue.task_done()

    async def _synthesize(self, text: str):
        """Fetches audio for `text` and returns (float32 numpy array,
        samplerate), or (None, None) on failure. float32 specifically —
        sounddevice/PortAudio doesn't accept float64, which is what
        soundfile.read() returns by default."""
        communicate = edge_tts.Communicate(text, self.voice, rate=self._rate_str())
        audio_bytes = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_bytes.extend(chunk["data"])
        if not audio_bytes:
            return None, None
        data, fs = sf.read(io.BytesIO(bytes(audio_bytes)), dtype="float32")
        return data, fs

    def _playback_worker(self):
        while True:
            data, fs = self._audio_queue.get()
            try:
                if data is not None and fs and len(data) > 0:
                    self._play(data, fs)
            except Exception as e:
                print(f"[TTS Playback Error]: {e}")
            finally:
                self._audio_queue.task_done()

    def _play(self, data, fs):
        """One continuous stream for the whole utterance — the standard
        sounddevice callback + finished_callback pattern, not a loop of
        small blocking sd.play()/sd.wait() calls."""
        self.is_speaking = True
        finished_event = threading.Event()
        position = 0
        n = len(data)
        mono = (data.ndim == 1)
        channels = 1 if mono else data.shape[1]

        def callback(outdata, frames, time_info, status):
            nonlocal position
            if self.muted:
                outdata[:] = 0
                raise sd.CallbackStop()
            chunk = data[position:position + frames]
            valid = len(chunk)
            if mono:
                outdata[:valid, 0] = chunk
                if valid < frames:
                    outdata[valid:, 0] = 0
            else:
                outdata[:valid] = chunk
                if valid < frames:
                    outdata[valid:] = 0
            position += valid

            rms = float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2))) if valid else 0.0
            if self.audio_callback:
                self.audio_callback(float(np.clip(rms * 4.8, 0.0, 1.0)))

            if valid < frames:
                raise sd.CallbackStop()

        def on_finished():
            finished_event.set()

        try:
            with sd.OutputStream(samplerate=fs, channels=channels, dtype="float32",
                                  callback=callback, finished_callback=on_finished):
                finished_event.wait(timeout=max(2.0, n / max(fs, 1) + 5.0))
        finally:
            self.is_speaking = False
            if self.audio_callback:
                self.audio_callback(0.0)


class BackgroundSpeakerThread(QThread):
    text_captured = pyqtSignal(str)
    audio_amplitude = pyqtSignal(float)
    speaking_state = pyqtSignal(bool)

    def __init__(self, voice=DEFAULT_VOICE):
        super().__init__()
        self.tts = TTSManager(voice=voice, audio_callback=self.receive_amplitude)
        self.keep_running = True

    def receive_amplitude(self, level: float):
        self.audio_amplitude.emit(level)

    def run(self):
        claim_path = THOUGHT_FILE + ".processing"
        while self.keep_running:
            try:
                # Claim the file by RENAMING it: anything written while we speak lands
                # in a fresh prom_thought.txt. The old read-speak-truncate silently
                # destroyed whatever was appended in between.
                source = claim_path if os.path.exists(claim_path) else None  # leftover from a crash
                if source is None and os.path.exists(THOUGHT_FILE) and os.path.getsize(THOUGHT_FILE) > 0:
                    os.replace(THOUGHT_FILE, claim_path)
                    source = claim_path
                if source:
                    with open(source, "r", encoding="utf-8") as f:
                        text = f.read().strip()
                    os.remove(source)
                    if text:
                        self.text_captured.emit(text)
                        self.speaking_state.emit(True)
                        self.tts.speak(text)
                        self.tts.wait_until_idle()
                        self.speaking_state.emit(False)
            except Exception as e:
                print(f"[BackgroundSpeaker Error]: {e}")
                self.msleep(1000)  # e.g. the writer still has the file open (Windows): retry shortly

            self.msleep(200)

    def stop(self):
        self.keep_running = False
        self.tts.is_speaking = False


# ==============================================================================
# PROMETHEUS AGENTIC WORKER — STREAMING + TOOL LOOP + CONFIRMATION GATE
# ==============================================================================
class PrometheusWorker(QThread):
    state_changed = pyqtSignal(str)
    response_received = pyqtSignal(str)                 # final, conscience-checked full text
    text_delta = pyqtSignal(str)                         # accumulated raw text so far (re-rendered live)
    status_updated = pyqtSignal(str, str)
    tool_executed = pyqtSignal(str, str, str)          # tool_name, args_json, result_json
    partial_text = pyqtSignal(str)                      # speech-cleaned sentence, fed straight to TTS
    confirmation_requested = pyqtSignal(str, str)       # tool_name, args_json — blocks worker until answered

    _SENTENCE_END_RE = re.compile(r'[.!?]["\')\]]?(?:\s|$)')

    def __init__(self, router, messages, auto_approve: bool = False, fallback_models=None):
        super().__init__()
        self.router = router
        self.messages = messages
        self.auto_approve = auto_approve
        self.fallback_models = fallback_models if fallback_models is not None else FALLBACK_MODELS
        self._stop_requested = False
        self._confirm_event = threading.Event()
        self._confirm_result = False

    def request_stop(self):
        self._stop_requested = True
        # Don't leave the worker hanging on a confirmation dialog forever.
        if not self._confirm_event.is_set():
            self._confirm_result = False
            self._confirm_event.set()

    def provide_confirmation(self, approved: bool):
        self._confirm_result = approved
        self._confirm_event.set()

    def _confirm_tool(self, tool_name: str, args_str: str) -> bool:
        if self.auto_approve or tool_name not in DANGEROUS_TOOLS:
            return True
        self._confirm_event.clear()
        self.confirmation_requested.emit(tool_name, args_str)
        self._confirm_event.wait()
        return self._confirm_result

    def _find_sentence_break(self, text: str):
        m = self._SENTENCE_END_RE.search(text)
        return m.end() if m else None

    def _tool_message(self, tc, result, tool_name=None):
        """The tool-result message for one call. default=str so a non-JSON-able
        result can't raise AFTER the assistant's tool_calls were already recorded;
        capped so one huge result can't evict the rest of the context."""
        return {
            "role": "tool",
            "tool_call_id": tc["id"],
            "name": tool_name or tc["function"]["name"] or "unknown_tool",
            "content": cap_text(json.dumps(result, default=str), TOOL_RESULT_CHAR_CAP),
        }

    def _finish_stopped(self):
        self.status_updated.emit("STOPPED BY OPERATOR.", THEME["amber"])
        self.state_changed.emit("IDLE")

    def _stream_completion(self, messages, fallback_models):
        """
        Streams the completion instead of waiting for the full response.
        Two parallel outputs per chunk of new text: text_delta carries the
        raw accumulated markdown (the console re-renders it live, throttled to
        STREAM_EMIT_INTERVAL - re-rendering per token is O(n^2)), and
        partial_text carries that same text run through SpeechFilter - code
        fences and markup stripped, so TTS speaks prose and announces code
        once instead of reading out backticks and syntax. Tool calls (which
        stream as fragmented deltas) are reassembled into the same shape a
        non-streaming response would have.
        Returns (content, tool_calls, finish_reason).
        """
        stream = self.router.completion(
            messages=messages,
            tools=TOOLS,
            max_tokens=MAX_RESPONSE_TOKENS,
            fallback_models=fallback_models,
            stream=True,
        )

        content_buf = []
        pending = ""
        tool_frags = {}
        speech_filter = md.SpeechFilter()
        finish_reason = None
        last_emit = 0.0

        try:
            for chunk in stream:
                if self._stop_requested:
                    break
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                if getattr(choice, "finish_reason", None):
                    finish_reason = choice.finish_reason
                delta = choice.delta

                if delta and delta.content:
                    content_buf.append(delta.content)
                    pending += delta.content
                    now = time.monotonic()
                    if now - last_emit >= STREAM_EMIT_INTERVAL:
                        last_emit = now
                        self.text_delta.emit("".join(content_buf))

                    while True:
                        cut = self._find_sentence_break(pending)
                        if cut is None:
                            break
                        sentence, pending = pending[:cut], pending[cut:]
                        spoken = speech_filter.feed(sentence)
                        if spoken.strip():
                            self.partial_text.emit(spoken)

                if delta and delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        slot = tool_frags.setdefault(idx, {"id": None, "name": None, "arguments": ""})
                        if tc_delta.id:
                            slot["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                slot["name"] = tc_delta.function.name
                            if tc_delta.function.arguments:
                                slot["arguments"] += tc_delta.function.arguments
        finally:
            close = getattr(stream, "close", None)  # release the connection even when we stop early
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

        if pending.strip():
            spoken = speech_filter.feed(pending)
            if spoken.strip():
                self.partial_text.emit(spoken)

        full_content = "".join(content_buf)
        if full_content:
            self.text_delta.emit(full_content)  # final flush: the throttle may have skipped the tail
        tool_calls = None
        if tool_frags:
            tool_calls = [
                {
                    "id": v["id"] or f"call_{i}",
                    "type": "function",
                    "function": {"name": v["name"] or "unknown_tool", "arguments": v["arguments"]},
                }
                for i, v in sorted(tool_frags.items())
            ]
        return full_content, tool_calls, finish_reason

    def run(self):
        try:
            self._run_turn()
        except Exception as e:
            traceback.print_exc()
            adaptation_engine.register_failure()
            self.status_updated.emit(f"CORE ERROR: {e}", THEME["red"])
            self.state_changed.emit("IDLE")
        finally:
            # Safety net: whatever happened above, never leave an assistant tool
            # call without its result in the history that is saved and re-sent -
            # providers reject such a history and every later turn would fail.
            self.messages[:] = sanitize_messages(self.messages)

    def _run_turn(self):
        self.state_changed.emit("THINKING")
        self.status_updated.emit("PROMETHEUS SYNTHESIZING RESPONSE...", THEME["amber_glow"])

        last_user_text = ""
        for m in reversed(self.messages):
            if m.get("role") == "user":
                last_user_text = str(m.get("content", ""))
                break
        mutated_prompt = adaptation_engine.mutate_prompt(SYSTEM_PROMPT, last_user_text)
        # build_context_block() auto-retrieves relevant RAG hits for this
        # specific message, on top of persistent memory — previously RAG
        # was manual-query-only via /rag.
        active_sys_prompt = f"{mutated_prompt}\n\n{build_context_block(last_user_text)}"

        # Always pass the chain: non-OpenRouter clients ignore it, and the router can
        # rotate to OpenRouter mid-request even when it wasn't first in line.
        fallbacks = self.fallback_models or None

        for _ in range(MAX_TOOL_ITERATIONS):
            if self._stop_requested:
                self._finish_stopped()
                return

            full_messages = [{"role": "system", "content": active_sys_prompt}] + self.messages

            try:
                content, tool_calls, finish_reason = self._stream_completion(full_messages, fallbacks)
            except Exception as e:
                adaptation_engine.register_failure()
                self.status_updated.emit(f"CORE ERROR: {e}", THEME["red"])
                self.state_changed.emit("IDLE")
                return

            if self._stop_requested:
                # Keep what was actually said; drop half-streamed tool calls, which
                # would be left without results.
                if content:
                    self.messages.append({"role": "assistant", "content": content})
                self._finish_stopped()
                return

            if finish_reason == "length":
                self.status_updated.emit("RESPONSE HIT THE TOKEN LIMIT AND WAS CUT OFF.", THEME["amber"])

            clean_msg = {"role": "assistant", "content": content or ""}
            if tool_calls:
                clean_msg["tool_calls"] = tool_calls
            self.messages.append(clean_msg)

            if not tool_calls:
                adaptation_engine.register_success()
                if content:
                    final_text = conscience_engine.evaluate_response(content)
                    self.response_received.emit(final_text)
                return

            self.state_changed.emit("ADAPTING")

            for pos, tc in enumerate(tool_calls):
                tool_name = tc["function"]["name"] or "unknown_tool"
                if self._stop_requested:
                    # Answer every remaining call so the saved history stays valid.
                    for rest in tool_calls[pos:]:
                        self.messages.append(self._tool_message(
                            rest, {"status": "cancelled", "reason": "Stopped by operator."}))
                    break

                raw_args = tc["function"]["arguments"]
                result = None
                args = {}
                try:
                    args = json.loads(raw_args) if raw_args else {}
                    if not isinstance(args, dict):
                        raise ValueError("arguments must be a JSON object")
                    args_str = json.dumps(args, indent=2)
                except ValueError as bad_args:  # JSONDecodeError is a ValueError
                    # Don't run the tool with {} - a truncated or garbled call must not execute.
                    args_str = (raw_args or "")[:2000]
                    result = {"status": "error",
                              "message": f"Tool arguments were not valid JSON ({bad_args}); nothing was executed."}

                if result is None:
                    if not self._confirm_tool(tool_name, args_str):
                        result = {"status": "refused", "reason": "Operator denied execution."}
                    else:
                        self.status_updated.emit(f"ADAPTING SYSTEM LOGIC: {tool_name}", THEME["cobalt"])
                        try:
                            result = dispatch_tool(tool_name, args)
                        except Exception as tool_err:
                            traceback.print_exc()
                            result = {"status": "execution_error", "exception": str(tool_err)}

                res_str = json.dumps(result, indent=2, default=str) if isinstance(result, (dict, list)) else str(result)
                self.tool_executed.emit(tool_name, args_str, res_str)
                self.messages.append(self._tool_message(tc, result, tool_name))

            if not self._stop_requested:
                self.state_changed.emit("THINKING")

        adaptation_engine.register_failure()
        self.status_updated.emit(f"TOOL LOOP LIMIT ({MAX_TOOL_ITERATIONS}) REACHED — STOPPING.", THEME["red"])
        self.state_changed.emit("IDLE")


# ==============================================================================
# MAIN PROMETHEUS HUD WINDOW
# ==============================================================================
class SettingsDialog(QDialog):
    """Everything here is a real, applied setting — nothing is shown that
    doesn't actually do something once you hit Save."""

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Prometheus Settings")
        self.setMinimumWidth(460)
        self.setStyleSheet(
            f"QDialog {{ background: {THEME['bg']}; color: {THEME['text']}; }}"
            f"QLabel {{ color: {THEME['text']}; }}"
            f"QLineEdit, QSpinBox, QPlainTextEdit {{ background: rgba(0,0,0,0.4); color: {THEME['text']}; "
            f"border: 1px solid {THEME['border']}; border-radius: 6px; padding: 4px 6px; }}"
        )

        form = QFormLayout()
        form.setSpacing(10)

        self.voice_edit = QLineEdit(config.get("voice", DEFAULT_VOICE))
        self.voice_edit.setToolTip("An edge-tts voice name, e.g. en-US-ChristopherNeural, en-GB-SoniaNeural.")
        form.addRow("Voice:", self.voice_edit)

        self.speech_enabled_chk = QCheckBox()
        self.speech_enabled_chk.setChecked(bool(config.get("speech_enabled", True)))
        form.addRow("Speech on at launch:", self.speech_enabled_chk)

        self.rate_spin = QSpinBox()
        self.rate_spin.setRange(-50, 100)
        self.rate_spin.setSuffix("%")
        self.rate_spin.setValue(int(config.get("speech_rate", 0)))
        form.addRow("Speech rate:", self.rate_spin)

        self.fallback_edit = QLineEdit(", ".join(config.get("fallback_models", [])))
        self.fallback_edit.setPlaceholderText("openai/gpt-4o, google/gemini-2.0-flash-001")
        form.addRow("Fallback models:", self.fallback_edit)

        self.priority_edit = QLineEdit(", ".join(config.get("provider_priority", [])))
        self.priority_edit.setPlaceholderText("groq, openrouter, cerebras   (blank = default order)")
        self.priority_edit.setToolTip("Providers to try first, in order. Unknown names are ignored.")
        form.addRow("Provider priority:", self.priority_edit)

        self.overrides_edit = QLineEdit(", ".join(f"{k}={v}" for k, v in config.get("model_overrides", {}).items()))
        self.overrides_edit.setPlaceholderText("groq=llama-3.3-70b-versatile, openrouter=<model id>")
        self.overrides_edit.setToolTip("Use a different model for a provider: name=model, comma-separated.")
        form.addRow("Model overrides:", self.overrides_edit)

        self.obsidian_edit = QLineEdit(config.get("obsidian_vault", ""))
        self.obsidian_edit.setPlaceholderText("C:\\Users\\you\\Documents\\MyVault   (blank = off)")
        self.obsidian_edit.setToolTip("Your Obsidian vault folder (the one containing .obsidian). Prometheus only ever "
                                      "writes inside a 'Prometheus' folder in it. Use /obsidian to export.")
        form.addRow("Obsidian vault:", self.obsidian_edit)

        self.intro_chk = QCheckBox()
        self.intro_chk.setChecked(bool(config.get("play_intro", True)))
        form.addRow("Star-birth intro on launch:", self.intro_chk)

        self.console_cap_spin = QSpinBox()
        self.console_cap_spin.setRange(50, 5000)
        self.console_cap_spin.setValue(int(config.get("max_console_entries", 400)))
        form.addRow("Max console entries:", self.console_cap_spin)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def apply_to_config(self):
        self.config.set("voice", self.voice_edit.text().strip() or DEFAULT_VOICE)
        self.config.set("speech_enabled", self.speech_enabled_chk.isChecked())
        self.config.set("speech_rate", self.rate_spin.value())
        self.config.set("fallback_models", parse_csv(self.fallback_edit.text()))
        self.config.set("provider_priority", parse_csv(self.priority_edit.text()))
        self.config.set("model_overrides", parse_model_overrides(self.overrides_edit.text()))
        self.config.set("obsidian_vault", self.obsidian_edit.text().strip())
        self.config.set("play_intro", self.intro_chk.isChecked())
        self.config.set("max_console_entries", self.console_cap_spin.value())
        self.config.save()


class PrometheusMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = AppConfig()
        router_notes = apply_router_settings(self.config)
        _prometheus_core.set_obsidian_vault(self.config.get("obsidian_vault", ""))
        self.setWindowTitle("PROMETHEUS — SOVEREIGN STELLAR HUD v5.0")
        self.resize(1420, 880)
        self.setMinimumSize(1120, 700)
        self.setStyleSheet(f"background-color: {THEME['bg']};")

        self.router = llm_router  # shared with prometheus.py's CLI/tools — one rotation state, one usage log
        self.messages = _load_session()
        trim_messages(self.messages, MAX_SESSION_MESSAGES)
        self.tts = TTSManager(
            audio_callback=self.update_audio_level,
            voice=self.config.get("voice", DEFAULT_VOICE),
            rate_percent=self.config.get("speech_rate", 0),
        )
        self._smoothed_audio = 0.0
        self._turn_had_speech = False
        self.auto_approve_tools = False
        self._adapt_test_active = False

        # Console is a list of HTML entries re-rendered as a whole rather
        # than incrementally appended — that's what makes a *live* streaming
        # markdown entry possible (re-render the same slot in place) and
        # gives max_console_entries something concrete to enforce.
        self._console_entries = []
        self._code_registry = {}
        self._entry_seq = 0
        self._streaming_idx = None

        self.voice_thread = WhisperVoiceThread()
        self.voice_thread.transcription_done.connect(self.handle_transcription)
        self.voice_thread.status_signal.connect(self.handle_voice_status)
        self.voice_thread.audio_level_signal.connect(self.update_audio_level)
        self.voice_thread.finished.connect(self._on_voice_finished)

        # Pre-load the speech model in the background instead of on first
        # mic press — also what the star-birth intro's hold point waits on.
        self.model_preload_thread = ModelPreloadThread(self.voice_thread)
        self.model_preload_thread.ready.connect(self._on_model_ready)
        self.model_preload_thread.start()

        self.worker = None

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        app_layout = QVBoxLayout(central_widget)
        app_layout.setContentsMargins(12, 12, 12, 12)
        app_layout.setSpacing(10)

        self.setup_telemetry_bar(app_layout)

        main_layout = QHBoxLayout()
        main_layout.setSpacing(12)

        self.sun_container = QFrame(self)
        self.sun_container.setStyleSheet(
            "QFrame { background-color: #010103; border: 1px solid rgba(255, 140, 0, 0.32); "
            "border-radius: 14px; }"
        )
        self._apply_glow(self.sun_container, THEME["amber_glow"], blur=50, alpha=85)
        sun_layout = QVBoxLayout(self.sun_container)
        sun_layout.setContentsMargins(2, 2, 2, 2)

        self.sun_widget = SolarSunWidget(self.sun_container)
        sun_layout.addWidget(self.sun_widget)

        sidebar = QFrame(self)
        sidebar.setFixedWidth(440)
        sidebar.setStyleSheet(
            f"QFrame {{ background-color: {THEME['panel']}; border: 1px solid {THEME['border']}; "
            "border-radius: 14px; }"
        )
        self._apply_glow(sidebar, "#000000", blur=36, alpha=140, y_offset=6)

        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(16, 16, 16, 16)
        sidebar_layout.setSpacing(10)

        header_box = QHBoxLayout()
        self.lbl_title = QLabel("PROMETHEUS // SOVEREIGN HUD", self)
        self.lbl_title.setFont(QFont("Segoe UI Semibold", 11, QFont.Weight.Bold))
        self.lbl_title.setStyleSheet(f"color: {THEME['amber']}; letter-spacing: 1.5px; border: none;")

        self.lbl_mode = QLabel("IDLE", self)
        self.lbl_mode.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        self.lbl_mode.setStyleSheet(
            f"color: {THEME['amber']}; background: rgba(255, 179, 0, 0.12); padding: 3px 10px; "
            "border-radius: 8px; border: 1px solid rgba(255, 179, 0, 0.35);"
        )

        self.btn_settings = QPushButton("SET", self)
        self.btn_settings.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        self.btn_settings.setFixedSize(38, 22)
        self.btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_settings.setToolTip("Settings")
        self.btn_settings.setStyleSheet(
            "QPushButton { color: #9a9ab0; background: transparent; border: 1px solid rgba(255,255,255,0.15); "
            "border-radius: 5px; }"
            "QPushButton:hover { color: #EAEAF2; border: 1px solid rgba(255,255,255,0.35); }"
        )
        self.btn_settings.clicked.connect(self.open_settings)

        header_box.addWidget(self.lbl_title)
        header_box.addStretch()
        header_box.addWidget(self.btn_settings)
        header_box.addSpacing(8)
        header_box.addWidget(self.lbl_mode)
        sidebar_layout.addLayout(header_box)

        divider = QFrame(self)
        divider.setFixedHeight(1)
        divider.setStyleSheet("background: rgba(255, 179, 0, 0.14); border: none;")
        sidebar_layout.addWidget(divider)

        lbl_activity = QLabel("TELEMETRY & COMMAND LOG", self)
        lbl_activity.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        lbl_activity.setStyleSheet(f"color: {THEME['text_dim']}; border: none; letter-spacing: 1px;")
        sidebar_layout.addWidget(lbl_activity)

        self.console = QTextBrowser(self)
        self.console.setReadOnly(True)
        self.console.setFont(QFont("Consolas", 9))
        self.console.setOpenLinks(False)          # we route anchors ourselves (COPY links + external links)
        self.console.setOpenExternalLinks(False)
        self.console.anchorClicked.connect(self._on_console_link)
        self.console.setStyleSheet(
            f"QTextEdit {{ background: {THEME['panel_alt']}; border: 1px solid rgba(255, 140, 0, 0.18); "
            "border-radius: 10px; color: #FFE680; padding: 12px; }"
            "QScrollBar:vertical { background: transparent; width: 8px; margin: 4px; }"
            "QScrollBar::handle:vertical { background: rgba(255, 153, 0, 0.35); border-radius: 4px; min-height: 24px; }"
            "QScrollBar::handle:vertical:hover { background: rgba(255, 153, 0, 0.6); }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }"
        )
        sidebar_layout.addWidget(self.console, stretch=1)

        lbl_input = QLabel("COMMAND DISPATCH", self)
        lbl_input.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        lbl_input.setStyleSheet(f"color: {THEME['text_dim']}; border: none; letter-spacing: 1px;")
        sidebar_layout.addWidget(lbl_input)

        input_box = QHBoxLayout()
        input_box.setSpacing(8)
        self.input_field = QLineEdit(self)
        self.input_field.setFont(QFont("Segoe UI", 10))
        self.input_field.setPlaceholderText("Type a query, command, or /help...")
        self.input_field.setFixedHeight(40)
        self.input_field.setStyleSheet(
            "QLineEdit { background: rgba(0, 0, 0, 0.75); border: 1px solid rgba(179, 125, 0, 0.4); "
            "border-radius: 8px; color: #FFFFFF; padding: 0 12px; }"
            f"QLineEdit:focus {{ border: 1px solid {THEME['amber_glow']}; background: rgba(20, 14, 0, 0.75); }}"
        )
        self.input_field.returnPressed.connect(self.submit_prompt)

        self.btn_stop = QPushButton("■", self)
        self.btn_stop.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        self.btn_stop.setFixedSize(40, 40)
        self.btn_stop.setToolTip("Stop the current request")
        self.btn_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet(
            "QPushButton { background: rgba(255, 59, 59, 0.14); border: 1px solid rgba(255, 59, 59, 0.45); "
            f"color: {THEME['red']}; border-radius: 8px; }}"
            "QPushButton:hover:enabled { background: rgba(255, 59, 59, 0.28); }"
            "QPushButton:disabled { color: #4a4a55; border: 1px solid rgba(255,255,255,0.08); background: transparent; }"
        )
        self.btn_stop.clicked.connect(self.request_stop_generation)

        self.btn_mute = QPushButton("MUTE", self)
        self.btn_mute.setCheckable(True)
        self.btn_mute.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        self.btn_mute.setFixedSize(54, 40)
        self.btn_mute.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_mute.setToolTip("Silence speech immediately — independent of Stop, which only halts generation.")
        self.btn_mute.setStyleSheet(
            "QPushButton { background: rgba(0, 229, 255, 0.10); border: 1px solid rgba(0, 229, 255, 0.35); "
            f"color: {THEME['cyan']}; border-radius: 8px; }}"
            "QPushButton:hover { background: rgba(0, 229, 255, 0.20); }"
            "QPushButton:checked { background: rgba(255, 59, 59, 0.25); border: 1px solid rgba(255,59,59,0.6); color: #fff; }"
        )
        self.btn_mute.toggled.connect(self._on_mute_toggled)
        self.btn_mute.setChecked(not bool(self.config.get("speech_enabled", True)))

        self.btn_mic = QPushButton("● MIC", self)
        self.btn_mic.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        self.btn_mic.setFixedSize(76, 40)
        self.btn_mic.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_mic.setToolTip("Click to start recording, click again to stop and send.")
        self._mic_idle_style = (
            "QPushButton { background: rgba(255, 140, 0, 0.16); border: 1px solid #FF8C00; "
            f"color: {THEME['amber']}; border-radius: 8px; padding: 6px; }}"
            "QPushButton:hover { background: rgba(255, 140, 0, 0.28); }"
            "QPushButton:pressed { background: rgba(255, 140, 0, 0.5); color: #FFFFFF; }"
        )
        self._mic_rec_style = (
            "QPushButton { background: rgba(255, 51, 0, 0.35); border: 1px solid #FF3300; "
            "color: #FFFFFF; border-radius: 8px; padding: 6px; }"
        )
        self.btn_mic.setStyleSheet(self._mic_idle_style)
        self.btn_mic.clicked.connect(self.toggle_voice_input)  # toggle, not push-to-hold

        self.mic_glow = QGraphicsDropShadowEffect(self.btn_mic)
        self.mic_glow.setColor(QColor(THEME["amber_glow"]))
        self.mic_glow.setBlurRadius(18)
        self.mic_glow.setOffset(0, 0)
        self.btn_mic.setGraphicsEffect(self.mic_glow)

        self.mic_pulse_anim = QPropertyAnimation(self.mic_glow, b"blurRadius", self)
        self.mic_pulse_anim.setDuration(650)
        self.mic_pulse_anim.setLoopCount(-1)
        self.mic_pulse_anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self.mic_pulse_anim.setKeyValueAt(0.0, 14)
        self.mic_pulse_anim.setKeyValueAt(0.5, 42)
        self.mic_pulse_anim.setKeyValueAt(1.0, 14)

        input_box.addWidget(self.input_field)
        input_box.addWidget(self.btn_stop)
        input_box.addWidget(self.btn_mute)
        input_box.addWidget(self.btn_mic)
        sidebar_layout.addLayout(input_box)

        main_layout.addWidget(self.sun_container, stretch=1)
        main_layout.addWidget(sidebar)
        app_layout.addLayout(main_layout, stretch=1)

        self.idle_check_timer = QTimer(self)
        self.idle_check_timer.timeout.connect(self.check_idle_state)
        self.idle_check_timer.start(200)

        # Hotkeys: [T] toggles Cobalt Blue Mahoraga State, [Ctrl+L] clears
        # console, [Ctrl+Shift+N] starts a fresh session, [Escape] skips the
        # star-birth intro if it's still playing.
        QShortcut(QKeySequence("T"), self, self.toggle_adapt_test)
        QShortcut(QKeySequence("Ctrl+L"), self, self.clear_console)
        QShortcut(QKeySequence("Ctrl+Shift+N"), self, self.start_new_session)
        QShortcut(QKeySequence("Escape"), self, self.sun_widget.skip_birth)

        self.bg_speaker = BackgroundSpeakerThread()
        self.bg_speaker.audio_amplitude.connect(self.update_audio_level)
        self.bg_speaker.text_captured.connect(self.handle_bg_thought)
        self.bg_speaker.speaking_state.connect(self.handle_bg_speaking_state)
        self.bg_speaker.start()
        self.bg_speaker.tts.set_muted(self.btn_mute.isChecked())  # the mute button only existed for the main voice

        self.append_console("SYSTEM", "PROMETHEUS STELLAR CORE INITIALIZED. READY.", THEME["mint"])
        if self.config.load_error:
            self.append_console("SYSTEM", f"Settings problem: {self.config.load_error}", THEME["amber"])
        for note in router_notes:
            self.append_console("SYSTEM", note, THEME["amber"])
        if self.messages:
            self.append_console("SYSTEM", f"Restored {len(self.messages)} messages from the previous session.", THEME["cyan"])

        geo = self.config.get("window_geometry", "")
        if geo:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geo.encode("ascii")))
            except Exception:
                pass

        if self.config.get("play_intro", True):
            self.sun_widget.start_birth(ready=False, on_finished=self._on_birth_finished)

    # -- setup helpers ---------------------------------------------------------

    def _apply_glow(self, widget, color, blur=40, alpha=120, y_offset=0):
        effect = QGraphicsDropShadowEffect(widget)
        glow_color = QColor(color)
        glow_color.setAlpha(alpha)
        effect.setColor(glow_color)
        effect.setBlurRadius(blur)
        effect.setOffset(0, y_offset)
        widget.setGraphicsEffect(effect)

    def setup_telemetry_bar(self, parent_layout):
        telemetry_frame = QFrame(self)
        telemetry_frame.setFixedHeight(36)
        telemetry_frame.setStyleSheet(
            f"QFrame {{ background-color: {THEME['panel_alt']}; border: 1px solid rgba(255, 140, 0, 0.2); "
            "border-radius: 10px; }"
        )
        bar_layout = QHBoxLayout(telemetry_frame)
        bar_layout.setContentsMargins(14, 0, 14, 0)
        bar_layout.setSpacing(6)

        self.status_dot = QLabel("●", self)
        self.status_dot.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
        self.status_dot.setStyleSheet(f"color: {THEME['mint']}; border: none;")

        lbl_node = QLabel("SYSTEM: ONLINE", self)
        lbl_node.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        lbl_node.setStyleSheet(f"color: {THEME['mint']}; border: none; letter-spacing: 0.5px;")

        self.lbl_route = QLabel(f"ROUTE: {self.router.provider.upper()} / {self.router.default_model}", self)
        self.lbl_route.setFont(QFont("Consolas", 8))
        self.lbl_route.setStyleSheet(f"color: {THEME['text_dim']}; border: none;")
        self.lbl_route.setToolTip("Which provider actually served the last request — rotates automatically on errors/cooldowns.")

        self.audio_meter = QProgressBar(self)
        self.audio_meter.setFixedSize(120, 10)
        self.audio_meter.setRange(0, 100)
        self.audio_meter.setValue(0)
        self.audio_meter.setTextVisible(False)
        self.audio_meter.setStyleSheet(
            "QProgressBar { background: rgba(250, 250, 250, 0.06); border: 1px solid rgba(255, 140, 0, 0.3); "
            "border-radius: 5px; }"
            "QProgressBar::chunk { border-radius: 5px; "
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            "stop:0 #FFB300, stop:0.6 #FF8C00, stop:1 #FF3300); }"
        )

        self.btn_auto_approve = QPushButton("AUTO-APPROVE: OFF", self)
        self.btn_auto_approve.setCheckable(True)
        self.btn_auto_approve.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        self.btn_auto_approve.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_auto_approve.setToolTip(
            "When OFF, Prometheus pauses and asks before running tools with real-world "
            "effects (code execution, desktop control, launching apps)."
        )
        self.btn_auto_approve.setStyleSheet(
            "QPushButton { color: #7C7C92; background: transparent; border: 1px solid rgba(255,255,255,0.15); "
            "border-radius: 6px; padding: 3px 8px; }"
            "QPushButton:checked { color: #FF3B3B; border: 1px solid rgba(255,59,59,0.5); background: rgba(255,59,59,0.12); }"
        )
        self.btn_auto_approve.toggled.connect(self._on_auto_approve_toggled)

        lbl_hotkey = QLabel("[T] MAHORAGA  [Ctrl+L] CLEAR  [Ctrl+Shift+N] NEW", self)
        lbl_hotkey.setFont(QFont("Consolas", 8))
        lbl_hotkey.setStyleSheet("color: #555577; border: none;")

        bar_layout.addWidget(self.status_dot)
        bar_layout.addWidget(lbl_node)
        bar_layout.addSpacing(15)
        bar_layout.addWidget(self.lbl_route)
        bar_layout.addStretch()
        audio_lbl = QLabel("AUDIO:", self)
        audio_lbl.setStyleSheet(f"color: {THEME['text_dim']}; font-size: 10px; border: none;")
        bar_layout.addWidget(audio_lbl)
        bar_layout.addWidget(self.audio_meter)
        bar_layout.addSpacing(12)
        bar_layout.addWidget(self.btn_auto_approve)
        bar_layout.addSpacing(12)
        bar_layout.addWidget(lbl_hotkey)

        parent_layout.addWidget(telemetry_frame)
        self._make_opacity_effect(self.status_dot)

    def _make_opacity_effect(self, widget):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", widget)
        anim.setDuration(1400)
        anim.setLoopCount(-1)
        anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        anim.setKeyValueAt(0.0, 1.0)
        anim.setKeyValueAt(0.5, 0.35)
        anim.setKeyValueAt(1.0, 1.0)
        anim.start()
        return effect

    # -- settings ---------------------------------------------------------------

    def open_settings(self):
        dlg = SettingsDialog(self.config, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            dlg.apply_to_config()
            for speaker in (self.tts, self.bg_speaker.tts):
                speaker.set_voice(self.config.get("voice", DEFAULT_VOICE))
                speaker.set_rate(self.config.get("speech_rate", 0))
            for note in apply_router_settings(self.config):
                self.append_console("SYSTEM", note, THEME["amber"])
            _prometheus_core.set_obsidian_vault(self.config.get("obsidian_vault", ""))
            self.lbl_route.setText(f"ROUTE: {self.router.provider.upper()} / {self.router.default_model}")
            self.append_console("SYSTEM", "Settings saved.", THEME["mint"])

    def _on_auto_approve_toggled(self, checked: bool):
        self.auto_approve_tools = checked
        self.btn_auto_approve.setText(f"AUTO-APPROVE: {'ON' if checked else 'OFF'}")
        if checked:
            self.append_console("SYSTEM", "Auto-approve enabled — dangerous tools will run without confirmation.", THEME["red"])
        else:
            self.append_console("SYSTEM", "Auto-approve disabled — dangerous tools require confirmation again.", THEME["amber"])

    def _on_mute_toggled(self, checked: bool):
        self.tts.set_muted(checked)
        # setChecked() during __init__ fires this before bg_speaker exists, and MUTE
        # must silence the background "thought" voice too, not just the main one.
        bg = getattr(self, "bg_speaker", None)
        if bg is not None:
            bg.tts.set_muted(checked)
        self.btn_mute.setText("MUTED" if checked else "MUTE")

    # -- star-birth / model preload -----------------------------------------------

    def _on_model_ready(self):
        self.sun_widget.mark_birth_ready()

    def _on_birth_finished(self):
        self.append_console("SYSTEM", "Stellar core online.", THEME["mint"])

    # -- misc state handlers ------------------------------------------------------

    def toggle_adapt_test(self):
        if self.input_field.hasFocus():
            return  # the operator is typing a "t", not asking for the test state
        if self._adapt_test_active:
            self._adapt_test_active = False
            self.handle_state_change("IDLE")
            self.append_console("TEST", "Switched back to GOLDEN SOLAR state.", THEME["amber"])
        else:
            self._adapt_test_active = True
            self.handle_state_change("ADAPTING")
            self.append_console("TEST", "Switched to COBALT BLUE MAHORAGA ADAPTATION state.", THEME["cobalt"])

    def handle_bg_thought(self, text: str):
        self.append_console("THOUGHT", text, THEME["mint"])

    def handle_bg_speaking_state(self, is_speaking: bool):
        if is_speaking:
            self.handle_state_change("SPEAKING")
        else:
            self.handle_state_change("IDLE")

    def update_audio_level(self, level: float):
        self._smoothed_audio += (level - self._smoothed_audio) * 0.5
        self.sun_widget.set_audio_level(self._smoothed_audio)
        self.audio_meter.setValue(int(self._smoothed_audio * 100))

    # -- console rendering ---------------------------------------------------------

    def _render_console(self):
        cap = self.config.get("max_console_entries", 400)
        if len(self._console_entries) > cap:
            overflow = len(self._console_entries) - cap
            self._console_entries = self._console_entries[overflow:]
            if self._streaming_idx is not None:
                self._streaming_idx -= overflow
                if self._streaming_idx < 0:
                    self._streaming_idx = None
        bar = self.console.verticalScrollBar()
        was_at_bottom = bar.value() >= bar.maximum() - 4
        previous = bar.value()
        self.console.setHtml("".join(self._console_entries))
        if was_at_bottom:
            self._scroll_console_to_bottom()
        else:  # the operator scrolled up to read: don't yank the view back down on every update
            bar.setValue(min(previous, bar.maximum()))

    def _scroll_console_to_bottom(self):
        bar = self.console.verticalScrollBar()
        bar.setValue(bar.maximum())

    def clear_console(self):
        self._console_entries = []
        self._code_registry.clear()
        self._streaming_idx = None
        self.console.clear()

    @staticmethod
    def _console_text(text) -> str:
        """Model-, tool- or user-controlled text -> safe, bounded HTML for the console."""
        return _html.escape(cap_text(str(text), MAX_CONSOLE_TOOL_CHARS)).replace("\n", "<br/>")

    def append_console(self, sender: str, text: str, color: str = "#FFB300", html_ok: bool = False):
        """`text` is escaped unless html_ok=True (only for markup built in this file,
        with any dynamic part already escaped). Everything else - operator input,
        exception text, tool output, RAG hits, the thought file - can contain '<'."""
        stamp = time.strftime("%H:%M:%S")
        body = text if html_ok else self._console_text(text)
        html = (
            f'<div style="margin-bottom: 7px;">'
            f'<span style="color: #555568; font-size: 9px;">{stamp}</span> '
            f'<span style="color: {color}; font-weight: bold;">[{_html.escape(str(sender))}]</span> '
            f'<span style="color: {THEME["text"]};">{body}</span>'
            f'</div>'
        )
        self._console_entries.append(html)
        self._streaming_idx = None
        self._render_console()

    def handle_tool_execution(self, tool_name: str, args_json: str, result_json: str):
        stamp = time.strftime("%H:%M:%S")
        tool_html = (
            f'<div style="background: rgba(0, 191, 255, 0.08); border-left: 3px solid {THEME["cobalt"]}; '
            f'padding: 8px 10px; margin: 6px 0; border-radius: 4px;">'
            f'<span style="color: #555568; font-size: 9px;">{stamp}</span> '
            f'<b style="color: {THEME["cobalt"]};">[TOOL DISPATCH] {_html.escape(str(tool_name))}</b><br/>'
            f'<span style="color: #88CCFF; font-size: 10px;">INPUT: {self._console_text(args_json)}</span><br/>'
            f'<span style="color: #AAFFAA; font-size: 10px;">OUTPUT: {self._console_text(result_json)}</span>'
            f'</div>'
        )
        self._console_entries.append(tool_html)
        self._streaming_idx = None
        self._render_console()

    def handle_status(self, text: str, color: str = "#FF9900"):
        self.append_console("SYS", text, color)

    def _on_console_link(self, url):
        href = url.toString()
        if href.startswith(md.COPY_PREFIX):
            block_id = href[len(md.COPY_PREFIX):]
            code = self._code_registry.get(block_id)
            if code is not None:
                QApplication.clipboard().setText(code)
                self.handle_status("Code block copied to clipboard.", THEME["mint"])
        elif href.startswith("http://") or href.startswith("https://"):
            QDesktopServices.openUrl(url)

    def handle_text_delta(self, raw_text: str):
        """Live re-render of the in-progress assistant message — this is
        what makes the console track what's actually being spoken instead
        of dumping the whole response at the end, after speech is already
        underway."""
        prefix = f"live{self._entry_seq}"
        body = md.render_markdown(raw_text, MD_THEME, self._code_registry, id_prefix=prefix)
        stamp = time.strftime("%H:%M:%S")
        entry = (
            f'<div style="margin-bottom: 9px;">'
            f'<span style="color: #555568; font-size: 9px;">{stamp}</span> '
            f'<span style="color: #FFCC00; font-weight: bold;">[PROMETHEUS]</span>'
            f'<div style="margin: 2px 0 0 2px;">{body}</div>'
            f'</div>'
        )
        if self._streaming_idx is None:
            self._entry_seq += 1
            self._console_entries.append(entry)
            self._streaming_idx = len(self._console_entries) - 1
        else:
            self._console_entries[self._streaming_idx] = entry
        self._render_console()

    def handle_partial_text(self, sentence: str):
        """Speech-cleaned sentence, fired as it streams in — speaks it
        immediately instead of waiting for the full response."""
        self._turn_had_speech = True
        self.tts.speak(sentence)

    def handle_response(self, text: str):
        # Final pass with the conscience-checked text (e.g. a closed code
        # fence) into the SAME streaming slot, then release the slot.
        self.handle_text_delta(text)
        self._streaming_idx = None
        self.handle_state_change("SPEAKING")
        # Normally already spoken sentence-by-sentence as it streamed in
        # (see handle_partial_text) — only speak here as a fallback for the
        # rare case nothing was streamed.
        if not self._turn_had_speech:
            self.tts.speak(md.clean_for_speech(text))

    def handle_confirmation_request(self, tool_name: str, args_json: str):
        box = QMessageBox(self)
        box.setWindowTitle("Confirm Tool Execution")
        box.setIcon(QMessageBox.Icon.Warning)
        # Plain text only: the arguments are model-controlled and Qt would otherwise
        # render HTML-looking text, letting a tool call dress up - or hide - what it does.
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(f"Prometheus wants to run a tool with real-world effects:\n\n{tool_name}")
        preview = args_json if len(args_json) < 600 else args_json[:600] + "\n... (truncated - the full text is under Show Details)"
        box.setInformativeText(preview)
        box.setDetailedText(args_json)  # always the WHOLE payload, never just the first 600 characters
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        approved = box.exec() == QMessageBox.StandardButton.Yes
        if self.worker is not None:
            self.worker.provide_confirmation(approved)
        self.append_console(
            "SYSTEM",
            f"Operator {'approved' if approved else 'denied'} {tool_name}.",
            THEME["cyan"] if approved else THEME["red"],
        )

    # -- voice input (toggle-to-talk) ----------------------------------------------

    def toggle_voice_input(self):
        if self.voice_thread.is_recording:
            self.stop_voice_input()
        else:
            self.start_voice_input()

    def start_voice_input(self):
        if not self.voice_thread.start_recording():
            return  # still transcribing the last clip: nothing started, so don't show REC
        self.btn_mic.setText("● REC")
        self.btn_mic.setStyleSheet(self._mic_rec_style)
        self.mic_pulse_anim.start()

    def _reset_mic_ui(self):
        self.btn_mic.setText("● MIC")
        self.btn_mic.setStyleSheet(self._mic_idle_style)
        self.mic_pulse_anim.stop()
        self.mic_glow.setBlurRadius(18)

    def stop_voice_input(self):
        self._reset_mic_ui()
        self.voice_thread.stop_recording()

    def _on_voice_finished(self):
        # The recording thread also ends on a microphone/model error, not only on a
        # normal stop - make sure the button can never stay stuck on REC.
        if not self.voice_thread.is_recording:
            self._reset_mic_ui()

    def handle_voice_status(self, text: str):
        self.append_console("VOICE", text, THEME["cyan"])

    def handle_transcription(self, text: str):
        if text:
            self.input_field.setText(text)
            self.submit_prompt()

    def check_idle_state(self):
        # Only fall back to IDLE when nothing is happening: the old check also reset
        # the ADAPTING (tool running) and test states within 200 ms.
        worker_busy = self.worker is not None and self.worker.isRunning()
        if (not worker_busy and not self._adapt_test_active
                and not self.tts.is_busy and not self.bg_speaker.tts.is_busy
                and self.sun_widget.state in (2, 3)):
            self.handle_state_change("IDLE")

    def handle_state_change(self, state: str):
        self.sun_widget.set_state_str(state)
        self.lbl_mode.setText(state)

        if state == "ADAPTING":
            self.lbl_mode.setStyleSheet(
                f"color: {THEME['cobalt']}; background: rgba(0, 191, 255, 0.15); padding: 3px 10px; "
                "border-radius: 8px; border: 1px solid rgba(0, 191, 255, 0.5);"
            )
        elif state == "SPEAKING":
            self.lbl_mode.setStyleSheet(
                "color: #FF3300; background: rgba(255, 51, 0, 0.15); padding: 3px 10px; "
                "border-radius: 8px; border: 1px solid rgba(255, 51, 0, 0.5);"
            )
        elif state == "THINKING":
            self.lbl_mode.setStyleSheet(
                "color: #FFCC00; background: rgba(255, 204, 0, 0.15); padding: 3px 10px; "
                "border-radius: 8px; border: 1px solid rgba(255, 204, 0, 0.5);"
            )
        else:
            self.lbl_mode.setStyleSheet(
                f"color: {THEME['amber']}; background: rgba(255, 179, 0, 0.08); padding: 3px 10px; "
                "border-radius: 8px; border: 1px solid rgba(255, 179, 0, 0.3);"
            )

    def handle_gui_slash_command(self, cmd: str) -> bool:
        """Lightweight local commands the GUI itself handles — no LLM round
        trip. /council and /forge stay CLI-only (prometheus.py) for now,
        since they drive their own multi-threaded LLM calls better suited
        to a terminal session than a blocking GUI dialog."""
        parts = cmd.strip().split(maxsplit=1)
        slash = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if slash == "/memory":
            self.append_console("MEMORY", get_memory_context(), THEME["cyan"])
            return True
        if slash == "/telemetry":
            pretty = self._console_text(json.dumps(tool_get_system_telemetry(), indent=2, default=str)).replace(" ", "&nbsp;")
            self.append_console("TELEMETRY", pretty, THEME["cyan"], html_ok=True)
            return True
        if slash in ("/providers", "/usage"):
            pretty = self._console_text(json.dumps(tool_get_router_status(), indent=2, default=str)).replace(" ", "&nbsp;")
            self.append_console("PROVIDERS", pretty, THEME["cyan"], html_ok=True)
            return True
        if slash == "/rag":
            if not arg:
                self.append_console("SYSTEM", "Usage: /rag <query>", THEME["amber"])
                return True
            hits = rag_store.search(arg, top_k=3)
            text = "<br/>".join(f"[{score:.2f}] {self._console_text(doc['content'])}" for score, doc in hits) or "No matches."
            self.append_console("RAG", text, THEME["cyan"], html_ok=True)
            return True
        if slash == "/graph":
            view = _prometheus_core.tool_memory_graph_view(arg)
            if view.get("status") != "success":
                self.append_console("GRAPH", view.get("message", "?"), THEME["amber"])
            elif arg:
                lines = [f"{view['entity']} ({view['type']}, importance {view['importance']:.2f})"]
                lines += [f"• {f}" for f in view["facts"]] or ["(no active facts)"]
                lines += [f"{r['source']} —{r['relation']}→ {r['target']}" for r in view["relations"]]
                self.append_console("GRAPH", "\n".join(lines), THEME["cyan"])
            else:
                lines = [json.dumps(view["stats"], default=str), "Most important:"]
                lines += [f"{e['importance']:.2f}  {e['name']} ({e['type']})" for e in view["top_entities"]]
                self.append_console("GRAPH", "\n".join(lines), THEME["cyan"])
            return True
        if slash == "/recall":
            if not arg:
                self.append_console("SYSTEM", "Usage: /recall <query>", THEME["amber"])
                return True
            hits = _prometheus_core.memory_graph.recall(arg, top_k=6, touch=False)
            body = "\n".join(f"[{h['score']:.2f}] {h['text']}" + ("  [unverified]" if h["untrusted"] else "") for h in hits)
            self.append_console("RECALL", body or "Nothing relevant in memory.", THEME["cyan"])
            return True
        if slash == "/obsidian":
            sub_cmd = (arg.split() or ["export"])[0].lower()
            if sub_cmd == "ingest":
                res = _prometheus_core.tool_obsidian_ingest()
            elif sub_cmd == "status":
                try:
                    mirror = _prometheus_core.get_obsidian_mirror()
                except Exception as e:
                    res = {"status": "error", "message": str(e)}
                else:
                    res = ({"status": "error", "message": _prometheus_core._NO_VAULT_HELP} if mirror is None else
                           {"status": "ok", "vault": mirror.vault, "folder": mirror.root,
                            "has_.obsidian": mirror.has_vault_marker, "graph": _prometheus_core.memory_graph.stats()})
            elif sub_cmd in ("export", "sync", "force"):
                res = _prometheus_core.tool_export_obsidian(force=(sub_cmd == "force"))
            else:
                self.append_console("SYSTEM", "Usage: /obsidian [export|force|ingest|status]", THEME["amber"])
                return True
            ok = res.get("status") in ("success", "ok")
            self.append_console("OBSIDIAN", json.dumps(res, indent=2, default=str),
                                THEME["mint"] if ok else THEME["amber"])
            return True
        if slash == "/clear":
            self.clear_console()
            return True
        if slash in ("/newsession", "/new"):
            self.start_new_session()
            return True
        if slash == "/settings":
            self.open_settings()
            return True
        if slash == "/help":
            self.append_console(
                "SYSTEM",
                "/memory &middot; /graph [entity] &middot; /recall &lt;query&gt; &middot; /obsidian [export|status|ingest] &middot; "
                "/telemetry &middot; /providers &middot; /rag &lt;query&gt; &middot; /settings &middot; "
                "/clear &middot; /newsession &middot; /help &mdash; /council and /forge remain CLI-only for now.",
                THEME["amber"],
                html_ok=True,  # static markup written above - nothing dynamic in it
            )
            return True
        return False

    def start_new_session(self):
        if self.worker is not None and self.worker.isRunning():
            self.append_console("SYSTEM", "Finish or stop the current request before starting a new session.", THEME["amber"])
            return
        self.messages = []
        _save_session(self.messages)
        self.clear_console()
        self.append_console("SYSTEM", "New session started.", THEME["mint"])

    def request_stop_generation(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.request_stop()
            self.append_console("SYSTEM", "Stop requested — halting after the current step.", THEME["amber"])

    def submit_prompt(self):
        text = self.input_field.text().strip()
        if not text:
            return

        if text.startswith("/"):
            self.input_field.clear()
            self.append_console("OPERATOR", text, "#FFFFFF")
            if not self.handle_gui_slash_command(text):
                self.append_console("SYSTEM", "Unknown command. Try /help.", THEME["amber"])
            return

        if self.worker is not None and self.worker.isRunning():
            self.append_console("SYSTEM", "Still processing the previous request — please wait or hit stop.", THEME["amber"])
            return

        self._turn_had_speech = False
        self.input_field.clear()
        self.append_console("OPERATOR", text, "#FFFFFF")
        self.messages.append({"role": "user", "content": text})

        self.worker = PrometheusWorker(
            self.router, self.messages, auto_approve=self.auto_approve_tools,
            fallback_models=self.config.get("fallback_models"),  # [] means "no fallbacks", not "use the built-in list"
        )
        self.worker.state_changed.connect(self.handle_state_change)
        self.worker.status_updated.connect(self.handle_status)
        self.worker.tool_executed.connect(self.handle_tool_execution)
        self.worker.text_delta.connect(self.handle_text_delta)
        self.worker.response_received.connect(self.handle_response)
        self.worker.partial_text.connect(self.handle_partial_text)
        self.worker.confirmation_requested.connect(self.handle_confirmation_request)
        self.worker.finished.connect(self._on_worker_finished)
        self.btn_stop.setEnabled(True)
        self.worker.start()

    def _on_worker_finished(self):
        self.btn_stop.setEnabled(False)
        trim_messages(self.messages, MAX_SESSION_MESSAGES)  # bound disk size and per-turn token cost
        _save_session(self.messages)
        used = self.router.last_used_provider or self.router.provider
        self.lbl_route.setText(f"ROUTE: {used.upper()} / {self.router.last_used_model or self.router.default_model}")

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            self.worker.request_stop()
            self.worker.wait(2000)
        _save_session(self.messages)
        try:
            self.config.set("window_geometry", bytes(self.saveGeometry().toBase64()).decode("ascii"))
            self.config.save()
        except Exception:
            pass
        self.voice_thread.stop_recording()
        self.voice_thread.wait(1500)
        self.model_preload_thread.wait(1500)
        self.bg_speaker.stop()
        self.bg_speaker.wait(3000)  # bounded: an unbounded wait hung the close if speech was stuck
        event.accept()


# ==============================================================================
# MAIN ENTRY POINT
# ==============================================================================
if __name__ == "__main__":
    format = QSurfaceFormat()
    format.setVersion(3, 3)
    format.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    QSurfaceFormat.setDefaultFormat(format)

    app = QApplication(sys.argv)
    install_crash_handler(app)
    window = PrometheusMainWindow()
    window.show()
    sys.exit(app.exec())
