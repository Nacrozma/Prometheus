/**
 * Prometheus's solar core, ported from `SolarSunWidget` in Prometheus's gui_orb.py
 * (FRAGMENT_SHADER, GLSL 330 core) to WebGL2 (GLSL ES 3.00). The shading code is unchanged; only
 * the version line and precision qualifiers differ, because GLSL ES requires them.
 *
 * States match the original: 0 IDLE, 1 THINKING, 2 SPEAKING, 3 ADAPTING (gold → cobalt).
 */

export const VERTEX_SHADER = `#version 300 es
in vec2 aPos;
void main() {
    gl_Position = vec4(aPos, 0.0, 1.0);
}
`;

export const FRAGMENT_SHADER = `#version 300 es
precision highp float;
precision highp int;
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

float sunspots(vec2 uv, float t) {
    vec2 spotUV = uv * 4.5 + vec2(t * 0.03, t * 0.01);
    float n = fbm(spotUV);
    float spot = smoothstep(0.68, 0.78, n);
    float penumbra = smoothstep(0.62, 0.82, n);
    return (1.0 - spot * 0.85) * (1.0 - penumbra * 0.35);
}

float solarProminence(vec2 uv, float angle, float r, float R, float t) {
    float arc = sin(angle * 6.0 + t * 0.8) * 0.5 + 0.5;
    arc *= pow(sin(angle * 3.0 - t * 0.4) * 0.5 + 0.5, 2.0);
    float height = R + 0.01 + arc * 0.08 * (1.0 + u_audio * 0.6);
    float dist = abs(r - height);
    return exp(-dist * 55.0) * arc;
}

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

    vec3 gold_deepCore   = vec3(0.55, 0.04, 0.00);
    vec3 gold_mainSurf   = vec3(1.00, 0.32, 0.01);
    vec3 gold_crestColor = vec3(1.00, 0.60, 0.05);
    vec3 gold_highIncand = vec3(1.00, 0.88, 0.35);
    vec3 gold_innerCor   = vec3(1.00, 0.50, 0.05);
    vec3 gold_softCor    = vec3(0.85, 0.22, 0.01);

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

    float spikeHorizontal = exp(-abs(uv.y) * 45.0) * exp(-abs(uv.x) * 4.0);
    float spikeVertical   = exp(-abs(uv.x) * 45.0) * exp(-abs(uv.y) * 4.0);
    vec3 flareSpikes = highIncand * (spikeHorizontal + spikeVertical) * 0.18 * (luminosity - 0.3);
    col += max(vec3(0.0), flareSpikes);

    vec2 vigUV = gl_FragCoord.xy / u_resolution.xy;
    vigUV *= 1.0 - vigUV.yx;
    float vig = pow(vigUV.x * vigUV.y * 18.0, 0.25);
    col *= mix(0.50, 1.0, clamp(vig, 0.0, 1.0));

    col = ACESFilm(col * 1.05);
    col = pow(col, vec3(1.0 / 1.15));

    FragColor = vec4(col, 1.0);
}
`;

export type SolarState = "idle" | "thinking" | "speaking" | "adapting" | "offline";

/** Same values as SolarSunWidget.STATE_ENERGY (idle, thinking, speaking, adapting). */
export const STATE_ENERGY: Record<Exclude<SolarState, "offline">, number> = { idle: 0.55, thinking: 1.08, speaking: 1.6, adapting: 1.5 };
/** Offline is Atlas's addition: a dim, still star, so a disconnected sibling never looks active. */
export const OFFLINE_ENERGY = 0.22;

export function stateIndex(s: SolarState): number {
  return s === "thinking" ? 1 : s === "speaking" ? 2 : s === "adapting" ? 3 : 0;
}

export interface Easing {
  energy: number;
  mix: number;
}

/**
 * One animation step, the same easing as SolarSunWidget.advance_frame (0.06 for energy, 0.08 for
 * the cobalt mix per 16 ms frame), made frame-rate independent so slow frames don't slow it down.
 */
export function ease(cur: Easing, state: SolarState, dtSeconds: number): Easing {
  const frames = Math.max(0, Math.min(0.1, dtSeconds)) / 0.016;
  const targetEnergy = state === "offline" ? OFFLINE_ENERGY : STATE_ENERGY[state];
  const targetMix = state === "adapting" ? 1 : 0;
  const k = (rate: number) => 1 - Math.pow(1 - rate, frames);
  return { energy: cur.energy + (targetEnergy - cur.energy) * k(0.06), mix: cur.mix + (targetMix - cur.mix) * k(0.08) };
}
