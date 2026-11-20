import { describe, expect, it } from "vitest";
import type { OrbitPlan, OrbitSession } from "@/lib/schemas";
import { partialPlan } from "@/features/orbit/orbitLogic";
import {
  ENVIRONMENTS,
  FrameMonitor,
  bezier,
  budget,
  captionText,
  curveCtrl,
  geodesic,
  rimPoint,
  rotate,
  torus,
  torusPoint,
  clampRect,
  connections,
  coreState,
  defaultRect,
  events,
  motion,
  panelContent,
  panelRects,
  readFx,
  readLayout,
  stageEnvironment,
  stages,
  withRect,
} from "@/features/orbit/orbitUniverse";

const plan: OrbitPlan = {
  title: "Site",
  objective: "Ship",
  outcome: "",
  brief: "A small site.",
  ideas: ["Static", "Blog"],
  phases: ["A", "B"],
  tasks: [
    { id: "a1", title: "Write", phase: "A", detail: "", priority: "normal", estimate: "", status: "proposed", operation: "atlas" },
    { id: "b1", title: "Ship", phase: "B", detail: "", priority: "normal", estimate: "", status: "proposed", operation: "manual" },
  ],
  deps: [{ from: "a1", to: "b1" }],
  assumptions: ["Static hosting"],
  questions: ["Domain?"],
  risks: ["Late"],
};

function session(over: Partial<OrbitSession> = {}): OrbitSession {
  return {
    id: "s1", title: "Site", created_at: "", updated_at: "", conversation_id: "c", autonomy: "approval_first", allowed: [],
    versions: [{ version: 1, plan, author: "atlas", why: "Proposed", at: "" }], active_version: 1, approved_version: 0, workflow: null,
    events: [], archived: false, reviewed: false, completed: false, layout: undefined, ...over,
  };
}

const node = (id: string, status: string) => ({ id, title: id, detail: "", phase: "A", operation: "atlas", deps: [], status, conversation_id: null, output: "", error: "", history: [] });

describe("ORBIT universe stages", () => {
  it("starts at overview and follows real progress", () => {
    expect(stages(null).map((s) => s.state)).toEqual(["current", "open", "open", "open", "open", "open", "open"]);
    expect(stages(session()).find((s) => s.state === "current")?.key).toBe("plan");
    const wf = { id: "w", plan_version: 1, autonomy: "approval_first", allowed: [], paused: false, state: "completed", nodes: [node("a1", "completed")], created_at: "" };
    const s = session({ approved_version: 1, workflow: wf });
    expect(stages(s).find((x) => x.state === "current")?.key).toBe("review");
    expect(stages({ ...s, reviewed: true, completed: true }).every((x) => x.state === "done")).toBe(true);
    expect(stageEnvironment("build")).toEqual(["operations", "operations"]);
  });
});

describe("ORBIT universe panels and connections", () => {
  it("shows only real data, or says what fills a panel", () => {
    for (const env of Object.values(ENVIRONMENTS)) for (const p of env.panels) if (p !== "activity") expect(panelContent(null, p).empty).not.toBe("");
    expect(panelContent(session(), "ideas").items.map((i) => i.text)).toEqual(["Static", "Blog"]);
    expect(panelContent(session(), "structure").items[0]?.text).toBe("Write → Ship");
    expect(panelContent(session(), "files", [{ id: "g1", path: "/home/me/notes.md", label: "notes.md", created_at: "" }]).items[0]?.text).toBe("notes.md");
  });
  it("draws lines only for real relationships", () => {
    expect(connections(null, "command")).toEqual([]);
    const c = connections(session(), "command");
    expect(c).toContainEqual({ from: "core", to: "brief", kind: "context" });
    expect(c.find((e) => e.to === "files")).toBeUndefined();
    expect(c).toContainEqual({ from: "ideas", to: "brief", kind: "informs" });
  });
});

describe("ORBIT universe layout", () => {
  it("clamps, stores per environment and survives bad data", () => {
    const l = withRect({}, "command", "brief", { x: 5, y: -2, w: 0.01, h: 9 });
    const r = panelRects(l, "command").brief;
    expect(r.x).toBeLessThanOrEqual(0.94);
    expect(r.w).toBeGreaterThanOrEqual(0.14);
    expect(panelRects(l, "design").brief).toEqual(clampRect(defaultRect("design", "brief")));
    expect(readLayout([1, 2])).toEqual({});
    expect(clampRect({ x: Number.NaN, w: Infinity as number }).w).toBeLessThanOrEqual(0.9);
  });
});

describe("ORBIT universe motion", () => {
  it("maps real states to visuals with priorities, and never invents activity", () => {
    expect(motion("nonsense")).toEqual(motion("idle"));
    expect(motion("listening").inflow).toBeGreaterThan(0);
    expect(motion("speaking").inflow).toBeLessThan(0);
    expect(coreState({ voice: "listening", turnRunning: true, planning: false, waiting: true, running: false, failed: false, completed: false })).toBe("approval");
    expect(coreState({ voice: "idle", turnRunning: true, planning: true, waiting: false, running: false, failed: false, completed: false })).toBe("planning");
    expect(coreState({ voice: "idle", turnRunning: false, planning: false, waiting: false, running: false, failed: false, completed: false })).toBe("idle");
  });
  it("settings change real budgets; reduced motion stops animation", () => {
    const subtle = budget(readFx(JSON.stringify({ intensity: "subtle", particles: "low" })), false);
    const full = budget(readFx(null), false);
    expect(subtle.particles).toBeLessThan(full.particles);
    expect(subtle.rings).toBeLessThan(full.rings);
    expect(budget(readFx(null), true).animate).toBe(false);
    expect(readFx("{not json").intensity).toBe("spectacular");
    expect(readFx(JSON.stringify({ volume: 7 })).volume).toBe(1);
  });
  it("effects come from real changes only", () => {
    const empty = session({ versions: [], active_version: 0 });
    expect(events(null, session())).toEqual([]);
    expect(events(empty, session())).toEqual(["project.created"]);
    expect(events(session(), session({ approved_version: 1 }))).toEqual(["plan.approved"]);
    expect(events(session(), { ...session(), id: "other" })).toEqual([]);
  });
  it("frame monitor lowers quality when frames are slow", () => {
    const m = new FrameMonitor(5);
    for (let i = 0; i < 10; i++) m.add(60);
    expect(m.quality).toBe(0.5);
  });
  it("streams brief and ideas progressively", () => {
    const p = partialPlan('```orbit-plan {"title": "Site", "brief": "A \\"small\\" site.", "ideas": ["Static", "Blog"], "phases": ["A"');
    expect([p.title, p.brief, p.ideas]).toEqual(["Site", 'A "small" site.', ["Static", "Blog"]]);
  });
});

describe("ORBIT core geometry and curved connections", () => {
  it("builds a geodesic shell and a bounded particle torus", () => {
    const { verts, edges } = geodesic(1);
    expect([verts.length, edges.length]).toEqual([42, 120]);
    for (const v of verts) expect(Math.abs(Math.hypot(...v) - 1)).toBeLessThan(1e-9);
    expect(torus(50)).toHaveLength(50);
    expect(torus(10)).toEqual(torus(10));
    const full = budget(readFx(null), false);
    expect(budget(readFx(JSON.stringify({ particles: "low" })), false).torus).toBeLessThan(full.torus);
    expect(budget(readFx(null), false, 0.25).torus).toBeLessThan(full.torus);
  });
  it("projects a tilted ring: the near side is toward the viewer", () => {
    const [, , zNear] = rotate(torusPoint(Math.PI / 2, 0, 0, 2, 0.4), 0, 0.37);
    const [, , zFar] = rotate(torusPoint(-Math.PI / 2, 0, 0, 2, 0.4), 0, 0.37);
    expect(zNear).toBeGreaterThan(0);
    expect(zFar).toBeLessThan(0);
  });
  it("curves bow away from the core and pulses stay on the curve", () => {
    const c = curveCtrl({ x: 0, y: 0 }, { x: 10, y: 0 }, { x: 5, y: 5 });
    expect(c.y).toBeLessThan(0);
    expect(bezier({ x: 0, y: 0 }, c, { x: 10, y: 0 }, 0)).toEqual({ x: 0, y: 0 });
    expect(bezier({ x: 0, y: 0 }, c, { x: 10, y: 0 }, 1)).toEqual({ x: 10, y: 0 });
    const r = rimPoint({ x: 0, y: 0 }, { x: 100, y: 0 }, 50, 20);
    expect(r).toEqual({ x: 50, y: 0 });
  });
  it("captions show one clean line of real text", () => {
    expect(captionText("Atlas", "**Here** is ```orbit-plan {}``` the plan")).toBe("Atlas: Here is the plan");
    expect(captionText("Atlas", "x".repeat(400)).length).toBeLessThanOrEqual(188);
    expect(captionText("You", "   ")).toBe("");
  });
});
