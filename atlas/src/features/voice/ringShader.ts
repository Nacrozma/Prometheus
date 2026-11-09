/**
 * The Atlas voice ring: an original circular waveform in electric blue, cyan and ice, drawn by a
 * fragment shader. The ring's radius at each angle comes from a 64-band spectrum texture filled
 * every frame from a Web Audio analyser (real playback or microphone audio), mirrored left/right so
 * the shape is continuous. Three thin strands, a soft glow and faint sparkles give it depth.
 * State values: 0 idle, 1 listening, 2 processing, 3 speaking, 4 paused, 5 interrupted, 6 error,
 * 7 offline.
 */
export const RING_VERTEX = `#version 300 es
in vec2 a_pos;
void main() { gl_Position = vec4(a_pos, 0.0, 1.0); }
`;

export const RING_FRAGMENT = `#version 300 es
precision highp float;
uniform vec2 u_res;
uniform float u_time;
uniform float u_level;
uniform float u_fade;
uniform int u_state;
uniform sampler2D u_bands;
out vec4 o;
const float PI = 3.14159265;

float band(float a) { return texture(u_bands, vec2(clamp(a, 0.0, 1.0), 0.5)).r; }
float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }

void main() {
  vec2 p = (gl_FragCoord.xy - 0.5 * u_res) / (0.5 * min(u_res.x, u_res.y));
  float r = length(p);
  float th = atan(p.y, p.x);
  float u = abs(th) / PI;
  float t = u_time;
  float R = 0.6;
  float wave = 0.0;
  float bright = 0.5;
  if (u_state == 3) {
    wave = band(u * 0.9) * 0.24 + band(1.0 - u) * 0.05;
    bright = 0.72 + u_level * 1.8;
  } else if (u_state == 1) {
    wave = band(u) * 0.12;
    bright = 0.68 + u_level * 1.4;
  } else if (u_state == 2) {
    wave = 0.012 * sin(th * 6.0 - t * 2.0);
    bright = 0.58;
  } else if (u_state == 0) {
    wave = 0.009 * sin(th * 5.0 + t * 0.8) + 0.006 * sin(th * 3.0 - t * 0.6);
    bright = 0.42 + 0.08 * sin(t * 1.2);
  } else if (u_state == 4) {
    bright = 0.34;
  } else if (u_state == 5) {
    wave = 0.03 * u_fade * sin(th * 8.0);
    bright = 0.35 + 0.4 * u_fade;
  } else if (u_state == 6) {
    wave = 0.006 * sin(th * 4.0 + t);
    bright = 0.5;
  } else {
    bright = 0.2;
  }
  float Rw = R + wave;
  float d1 = abs(r - Rw);
  float d2 = abs(r - (Rw + 0.018 * sin(th * 7.0 + t * 1.7)));
  float d3 = abs(r - (Rw - 0.015 * sin(th * 5.0 - t * 1.3)));
  float core = exp(-d1 * d1 / 0.00018) + 0.55 * exp(-d2 * d2 / 0.00012) + 0.45 * exp(-d3 * d3 / 0.0001);
  float glow = exp(-d1 * 9.0) * 0.55;
  if (u_state == 2) {
    float a = mod(th - t * 2.4, 2.0 * PI);
    float arc = exp(-pow(min(a, 2.0 * PI - a), 2.0) * 6.0) * (0.8 + 0.2 * sin(t * 6.0));
    core += arc * 1.2 * exp(-d1 * d1 / 0.0004);
    glow += arc * 0.6 * exp(-d1 * 6.0);
  }
  if (u_state == 1) {
    for (int i = 0; i < 2; i++) {
      float ph = fract(t * 0.7 + float(i) * 0.5);
      float rr = Rw * (1.0 - 0.55 * ph);
      core += exp(-pow(r - rr, 2.0) / 0.0005) * (1.0 - ph) * (0.25 + u_level * 2.5);
    }
  }
  if (u_state == 3) {
    float cell = floor(th * 36.0);
    float spark = step(0.985, hash(vec2(cell, floor(t * 3.0)))) * exp(-abs(r - Rw - 0.07 - u_level * 0.2) * 40.0);
    core += spark * (0.4 + u_level);
  }
  vec3 electric = vec3(0.12, 0.56, 1.0);
  vec3 cyan = vec3(0.24, 0.81, 0.9);
  vec3 ice = vec3(0.81, 0.96, 1.0);
  vec3 sapphire = vec3(0.06, 0.32, 0.73);
  vec3 col = mix(electric, cyan, 0.5 + 0.5 * sin(th * 2.0 + t * 0.5)) * core + ice * pow(min(core, 1.5), 3.0) * 0.5 + sapphire * glow;
  col *= bright;
  if (u_state == 6) col = mix(col, vec3(1.0, 0.62, 0.25) * (core * 0.8 + glow * 0.3) * 0.7, 0.55);
  if (u_state == 7) col = vec3(dot(col, vec3(0.3333)));
  float alpha = clamp(max(max(col.r, col.g), col.b), 0.0, 1.0);
  o = vec4(min(col, vec3(1.0)), alpha);
}
`;

export const STATE_INDEX = { idle: 0, listening: 1, transcribing: 2, processing: 2, speaking: 3, paused: 4, interrupted: 5, error: 6, offline: 7 } as const;

export const BANDS = 64;

/**
 * Fold an analyser's byte spectrum into `out` (64 bands, 0..1), emphasising speech frequencies,
 * with fast attack and slower release so movement follows the voice without flicker.
 */
export function computeBands(freq: Uint8Array, out: Float32Array, attack = 0.55, release = 0.14): void {
  const usable = Math.max(BANDS, Math.floor(freq.length * 0.6));
  for (let i = 0; i < BANDS; i++) {
    // Roughly logarithmic: more bands for low and middle frequencies, where speech lives.
    const a = Math.floor(usable * Math.pow(i / BANDS, 1.6));
    const b = Math.max(a + 1, Math.floor(usable * Math.pow((i + 1) / BANDS, 1.6)));
    let sum = 0;
    for (let j = a; j < b && j < freq.length; j++) sum += freq[j] ?? 0;
    const target = sum / (b - a) / 255;
    const prev = out[i] ?? 0;
    out[i] = prev + (target - prev) * (target > prev ? attack : release);
  }
}
