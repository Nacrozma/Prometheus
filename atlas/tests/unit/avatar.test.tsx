import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PrometheusAvatar } from "@/features/siblings/avatar/PrometheusAvatar";
import { ease, FRAGMENT_SHADER, OFFLINE_ENERGY, STATE_ENERGY, stateIndex, VERTEX_SHADER } from "@/features/siblings/avatar/solarShader";

describe("Prometheus solar avatar", () => {
  it("is valid GLSL ES 3.00 with the original uniforms", () => {
    for (const src of [VERTEX_SHADER, FRAGMENT_SHADER]) expect(src.startsWith("#version 300 es\n")).toBe(true);
    expect(FRAGMENT_SHADER).toContain("precision highp float;");
    for (const u of ["u_resolution", "u_time", "u_audio", "u_state", "u_state_mix", "u_energy", "u_birth_scale"]) expect(FRAGMENT_SHADER).toMatch(new RegExp(`uniform \\w+ ${u};`));
    expect(FRAGMENT_SHADER.match(/uniform /g)?.length).toBe(7);
  });

  it("maps states like SolarSunWidget.set_state_str", () => {
    expect([stateIndex("idle"), stateIndex("thinking"), stateIndex("speaking"), stateIndex("adapting"), stateIndex("offline")]).toEqual([0, 1, 2, 3, 0]);
    expect(STATE_ENERGY).toEqual({ idle: 0.55, thinking: 1.08, speaking: 1.6, adapting: 1.5 });
  });

  it("eases toward the target independent of frame rate", () => {
    let a = { energy: STATE_ENERGY.idle, mix: 0 };
    for (let i = 0; i < 120; i++) a = ease(a, "adapting", 1 / 60);
    let b = { energy: STATE_ENERGY.idle, mix: 0 };
    for (let i = 0; i < 60; i++) b = ease(b, "adapting", 1 / 30);
    expect(a.mix).toBeGreaterThan(0.99);
    expect(Math.abs(a.energy - b.energy)).toBeLessThan(0.01);
    expect(Math.abs(a.mix - b.mix)).toBeLessThan(0.01);
    // Offline settles dim; a long stall is clamped (no jump).
    let c = { energy: STATE_ENERGY.speaking, mix: 0 };
    for (let i = 0; i < 300; i++) c = ease(c, "offline", 1 / 60);
    expect(c.energy).toBeCloseTo(OFFLINE_ENERGY, 2);
    const stalled = ease({ energy: 0.55, mix: 0 }, "speaking", 5);
    expect(stalled.energy).toBeLessThan(1.6);
  });

  it("falls back to a static rendering without WebGL2 and never claims to be connected when offline", () => {
    render(<PrometheusAvatar state="offline" size={80} />);
    const img = screen.getByRole("img");
    expect(img.getAttribute("aria-label")).toBe("Prometheus — not connected");
    expect(img.dataset.avatarRender).toBe("static");
  });
});
