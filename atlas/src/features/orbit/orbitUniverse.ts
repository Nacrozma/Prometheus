/**
 * ORBIT's spatial workspace for ATLAS — pure logic, unit-tested (Atlas's own implementation).
 *
 * Stages, environments, panels and connections are derived from the real session the core returns; nothing
 * is invented. A panel without real data says what would fill it; a line exists only for a real relationship.
 * The motion engine maps real states (voice phase, turn, workflow) to the electric-blue core's parameters, and
 * effects start only from real changes between two session snapshots.
 */
import type { Grant, OrbitPlan, OrbitSession } from "@/lib/schemas";

export const STAGES = [
  ["overview", "Overview"],
  ["ideas", "Ideas"],
  ["plan", "Plan"],
  ["design", "Design"],
  ["build", "Build"],
  ["review", "Review"],
  ["complete", "Complete"],
] as const;
export type StageKey = (typeof STAGES)[number][0];
export type StageState = { key: StageKey; name: string; state: "done" | "current" | "open"; why: string };

export type EnvKey = "command" | "design" | "operations" | "intelligence";
export const ENVIRONMENTS: Record<EnvKey, { name: string; purpose: string; panels: PanelKey[]; constellation: boolean }> = {
  command: { name: "Command", purpose: "Conversation, project overview, files, ideas and live activity", panels: ["brief", "ideas", "files", "plan", "next", "activity"], constellation: false },
  design: { name: "Design", purpose: "Phases, tasks and how they depend on each other", panels: ["brief", "plan", "structure"], constellation: true },
  operations: { name: "Operations", purpose: "Steps, progress, approvals, errors and recovery", panels: ["operations", "approvals", "next", "files"], constellation: true },
  intelligence: { name: "Intelligence", purpose: "Research results, ideas, open questions, assumptions and risks", panels: ["research", "ideas", "questions", "risks"], constellation: false },
};

export type PanelKey = "brief" | "ideas" | "files" | "plan" | "next" | "activity" | "structure" | "operations" | "approvals" | "research" | "questions" | "risks";
export const PANELS: Record<PanelKey, [string, string]> = {
  brief: ["Project brief", "Tell Atlas what you want to achieve; the brief appears with its first plan."],
  ideas: ["Ideas", "Ideas Atlas proposes for the project appear here."],
  files: ["Files", "Files you have shared with Atlas appear here. Share one with +."],
  plan: ["Project plan", "The plan forms here as Atlas proposes it."],
  next: ["Next steps", "What to do next appears once there is a plan."],
  activity: ["Live activity", "What happened in this session appears here."],
  structure: ["Structure", "Phases and dependencies appear once there is a plan."],
  operations: ["Operations", "Build the workflow from an approved plan to see its steps."],
  approvals: ["Approvals", "Nothing is waiting for you."],
  research: ["Research", "Results of research steps appear here."],
  questions: ["Open questions", "Questions Atlas still needs answered appear here."],
  risks: ["Assumptions and risks", "Assumptions and risks in the plan appear here."],
};

export type Item = { text: string; sub: string; state: string; ref: string };
export type Content = { id: PanelKey; title: string; items: Item[]; empty: string };

export function activePlan(s: OrbitSession | null): OrbitPlan | null {
  return s && s.active_version ? (s.versions[s.active_version - 1]?.plan ?? null) : null;
}

export function stages(s: OrbitSession | null): StageState[] {
  const plan = activePlan(s);
  const wf = s?.workflow ?? null;
  const nodes = wf?.nodes ?? [];
  const approved = !!s && s.approved_version > 0 && s.approved_version === s.active_version;
  const done = nodes.filter((n) => n.status === "completed").length;
  const facts: Record<StageKey, [boolean, string]> = {
    overview: [!!plan, plan ? "the project has a plan" : "talk about what you want to achieve"],
    ideas: [!!plan && (plan.ideas.length > 0 || !!plan.brief), plan ? `${plan.ideas.length} ideas, brief ${plan.brief ? "written" : "not written"}` : "no ideas yet"],
    plan: [approved && !!plan?.tasks.length, `version ${s?.active_version ?? 0} ${approved ? "approved" : "not approved yet"}`],
    design: [!!wf && wf.plan_version === s?.approved_version, wf ? "workflow built from the approved plan" : "build the workflow to decide how each step is done"],
    build: [wf?.state === "completed", nodes.length ? `${done}/${nodes.length} steps done` : "no steps yet"],
    review: [!!s?.reviewed, s?.reviewed ? "you reviewed the results" : "review the results, then mark them reviewed"],
    complete: [!!s?.completed, s?.completed ? "you marked the project complete" : "mark complete after review"],
  };
  let found = false;
  return STAGES.map(([key, name]) => {
    const [ok, why] = facts[key];
    const state = ok ? "done" : found ? "open" : "current";
    if (!ok) found = true;
    return { key, name, state, why } as StageState;
  });
}

export function stageEnvironment(stage: StageKey): [EnvKey, PanelKey] {
  const map: Record<StageKey, [EnvKey, PanelKey]> = {
    overview: ["command", "brief"],
    ideas: ["intelligence", "ideas"],
    plan: ["design", "plan"],
    design: ["design", "structure"],
    build: ["operations", "operations"],
    review: ["operations", "operations"],
    complete: ["command", "brief"],
  };
  return map[stage];
}

export function panelContent(s: OrbitSession | null, pid: PanelKey, grants: Grant[] = []): Content {
  const plan = activePlan(s);
  const nodes = s?.workflow?.nodes ?? [];
  const [title, hint] = PANELS[pid];
  let items: Item[] = [];
  const it = (text: string, sub = "", state = "", ref = ""): Item => ({ text, sub, state, ref });
  if (pid === "brief" && plan) {
    items = [it(plan.title, "", "title")];
    for (const [label, v] of [["Objective", plan.objective], ["Brief", plan.brief], ["Outcome", plan.outcome]] as const) if (v) items.push(it(v, label));
  } else if (pid === "ideas") items = (plan?.ideas ?? []).map((x) => it(x, "idea"));
  else if (pid === "files") items = grants.map((g) => it(g.label || g.path, g.path, "file", g.id));
  else if (pid === "plan" && plan) {
    const status = Object.fromEntries(nodes.map((n) => [n.id, n.status]));
    items = plan.phases.map((ph) => {
      const ts = plan.tasks.filter((t) => t.phase === ph);
      const d = ts.filter((t) => status[t.id] === "completed").length;
      return it(ph, `${ts.length} tasks${nodes.length ? `, ${d} done` : ""}`, ts.length && d === ts.length ? "done" : "");
    });
  } else if (pid === "next") {
    items.push(...nodes.filter((n) => n.status === "awaiting_approval").map((n) => it(n.title, "waiting for your approval", "awaiting_approval", n.id)));
    items.push(...nodes.filter((n) => n.status === "failed" || n.status === "blocked").map((n) => it(n.title, n.status === "failed" ? "failed — retry or change the plan" : "blocked", n.status, n.id)));
    items.push(...nodes.filter((n) => n.status === "ready").slice(0, 4).map((n) => it(n.title, "ready to start", "ready", n.id)));
    if (plan && !nodes.length) items.push(it(s && s.approved_version === s.active_version && s.approved_version ? "Build the workflow" : "Review and approve the plan", `version ${s?.active_version}`));
    items.push(...(plan?.questions ?? []).slice(0, 3).map((q) => it(q, "open question", "question")));
    if (s?.workflow?.state === "completed" && !s.reviewed) items.unshift(it("Review the results", "every step is done"));
  } else if (pid === "activity") items = [...(s?.events ?? [])].slice(-12).reverse().map((e) => it(e.kind.replace(/\./g, " "), `${new Date(e.at).toLocaleTimeString()} ${e.detail}`));
  else if (pid === "structure" && plan) {
    const by = Object.fromEntries(plan.tasks.map((t) => [t.id, t.title]));
    items = plan.deps.map((d) => it(`${by[d.from] ?? "?"} → ${by[d.to] ?? "?"}`, "must finish first", "", d.to));
    items.push(...plan.phases.map((ph, i) => it(ph, `phase ${i + 1}`)));
  } else if (pid === "operations") items = nodes.map((n) => it(n.title, n.operation, n.status, n.id));
  else if (pid === "approvals") items = nodes.filter((n) => n.status === "awaiting_approval").map((n) => it(n.title, n.history.at(-1)?.event ?? "", "awaiting_approval", n.id));
  else if (pid === "research") items = nodes.filter((n) => n.output && (n.operation === "research" || n.status === "completed")).map((n) => it(n.title, n.output.slice(0, 600), n.status, n.id));
  else if (pid === "questions") items = (plan?.questions ?? []).map((q) => it(q, "", "question"));
  else if (pid === "risks") items = [...(plan?.assumptions ?? []).map((a) => it(a, "assumption")), ...(plan?.risks ?? []).map((r) => it(r, "risk", "risk"))];
  return { id: pid, title, items, empty: items.length ? "" : hint };
}

export type Edge = { from: "core" | PanelKey; to: PanelKey; kind: string };

export function connections(s: OrbitSession | null, env: EnvKey, grants: Grant[] = []): Edge[] {
  const panels = ENVIRONMENTS[env].panels;
  const filled = new Set(panels.filter((p) => panelContent(s, p, grants).items.length));
  const out: Edge[] = panels.filter((p) => filled.has(p)).map((p) => ({ from: "core", to: p, kind: "context" }));
  const plan = activePlan(s);
  if (filled.has("plan") && filled.has("next") && s?.workflow) out.push({ from: "plan", to: "next", kind: "drives" });
  if (filled.has("ideas") && filled.has("brief") && plan?.ideas.length) out.push({ from: "ideas", to: "brief", kind: "informs" });
  if (filled.has("approvals") && filled.has("operations")) out.push({ from: "approvals", to: "operations", kind: "waits on" });
  return out;
}

// ------------------------------------------------------------------ layout (fractions of the stage)

export type Rect = { x: number; y: number; w: number; h: number; collapsed?: boolean; hidden?: boolean };
export type Layout = { env?: EnvKey; panels?: Partial<Record<EnvKey, Partial<Record<PanelKey, Rect>>>> };
const SLOTS: [number, number][] = [
  [0.16, 0.22],
  [0.84, 0.22],
  [0.16, 0.76],
  [0.84, 0.76],
  [0.5, 0.82],
  [0.5, 0.17],
];
export const PANEL_W = 0.26;
export const PANEL_H = 0.28;

export function defaultRect(env: EnvKey, pid: PanelKey): Rect {
  const i = Math.max(0, ENVIRONMENTS[env].panels.indexOf(pid));
  const [cx, cy] = SLOTS[i % SLOTS.length] ?? [0.5, 0.5];
  return { x: cx - PANEL_W / 2, y: cy - PANEL_H / 2, w: PANEL_W, h: PANEL_H, collapsed: false, hidden: false };
}

const num = (v: unknown, d: number) => (typeof v === "number" && Number.isFinite(v) ? v : d);

export function clampRect(r: Partial<Rect>): Rect {
  const w = Math.min(0.9, Math.max(0.14, num(r.w, PANEL_W)));
  const h = Math.min(0.9, Math.max(0.12, num(r.h, PANEL_H)));
  return { x: Math.min(0.94, Math.max(-w + 0.06, num(r.x, 0))), y: Math.min(0.95, Math.max(0, num(r.y, 0))), w, h, collapsed: !!r.collapsed, hidden: !!r.hidden };
}

export function readLayout(raw: unknown): Layout {
  return raw && typeof raw === "object" && !Array.isArray(raw) ? (raw as Layout) : {};
}

export function panelRects(layout: Layout, env: EnvKey): Record<PanelKey, Rect> {
  const stored = layout.panels?.[env] ?? {};
  return Object.fromEntries(ENVIRONMENTS[env].panels.map((p) => [p, clampRect({ ...defaultRect(env, p), ...(stored[p] ?? {}) })])) as Record<PanelKey, Rect>;
}

export function withRect(layout: Layout, env: EnvKey, pid: PanelKey, change: Partial<Rect>): Layout {
  const cur = panelRects(layout, env)[pid];
  return { ...layout, panels: { ...layout.panels, [env]: { ...(layout.panels?.[env] ?? {}), [pid]: clampRect({ ...cur, ...change }) } } };
}

// ------------------------------------------------------------------ motion (electric-blue core)

export type Motion = { ringSpeed: number; tilt: number; flow: number; inflow: number; arcs: number; shield: number; pulse: number; tone: [number, number, number]; glow: number; label: string };
const BLUE: [number, number, number] = [60, 207, 230];
const BASE: Motion = { ringSpeed: 1.2, tilt: 18, flow: 0.25, inflow: 0, arcs: 0, shield: 0.1, pulse: 0.18, tone: BLUE, glow: 0.45, label: "Ready" };
export const MOTION: Record<string, Partial<Motion>> = {
  idle: {},
  listening: { ringSpeed: 1.6, flow: 0.5, inflow: 1, shield: 0.16, pulse: 0, glow: 0.55, label: "Listening · microphone on" },
  thinking: { ringSpeed: 3.4, tilt: 34, flow: 0.9, arcs: 0.4, shield: 0.18, pulse: 0.9, glow: 0.7, label: "Thinking" },
  planning: { ringSpeed: 2.6, tilt: 28, flow: 0.7, arcs: 0.2, pulse: 0.6, glow: 0.68, label: "Planning" },
  researching: { ringSpeed: 2.8, tilt: 40, flow: 0.8, arcs: 0.3, pulse: 0.5, tone: [125, 243, 255], glow: 0.62, label: "Researching" },
  running: { ringSpeed: 3.2, tilt: 22, flow: 0.9, arcs: 0.6, shield: 0.2, pulse: 0.6, tone: [90, 170, 255], glow: 0.75, label: "Running the workflow" },
  speaking: { ringSpeed: 2, flow: 0.6, inflow: -1, shield: 0.2, pulse: 0, glow: 0.75, label: "Speaking" },
  approval: { ringSpeed: 0.3, tilt: 8, flow: 0.08, shield: 0.32, pulse: 0.35, tone: [255, 200, 120], glow: 0.6, label: "Waiting for your approval" },
  paused: { ringSpeed: 0.2, tilt: 8, flow: 0.05, shield: 0.24, pulse: 0.15, tone: [180, 200, 230], glow: 0.4, label: "Paused" },
  success: { ringSpeed: 1.6, flow: 0.4, inflow: -0.4, shield: 0.18, pulse: 0.3, glow: 0.85, label: "Done" },
  offline: { ringSpeed: 0.15, tilt: 6, flow: 0.04, shield: 0.04, pulse: 0, tone: [110, 120, 140], glow: 0.15, label: "Offline" },
  error: { ringSpeed: 0.4, tilt: 10, flow: 0.1, shield: 0.12, pulse: 0.25, tone: [240, 110, 110], glow: 0.35, label: "Something went wrong" },
};

export function motion(state: string): Motion {
  return { ...BASE, ...(MOTION[state] ?? {}) };
}

/** The core's state from real signals, in priority order: an approval waits, voice, a turn, the workflow. */
export function coreState(p: { voice: string; turnRunning: boolean; planning: boolean; waiting: boolean; running: boolean; failed: boolean; completed: boolean; offline?: boolean }): string {
  if (p.offline) return "offline";
  if (p.waiting) return "approval";
  if (p.voice === "listening") return "listening";
  if (p.voice === "speaking") return "speaking";
  if (p.voice === "error") return "error";
  if (p.turnRunning) return p.planning ? "planning" : "thinking";
  if (p.running) return "running";
  if (p.failed) return "error";
  if (p.completed) return "success";
  return "idle";
}

export type Fx = { intensity: "subtle" | "balanced" | "spectacular"; particles: "low" | "medium" | "high"; depth: "standard" | "immersive"; camera: "off" | "gentle" | "dynamic"; cinematic: boolean; energy: boolean; sound: boolean; volume: number };
export const FX_DEFAULT: Fx = { intensity: "spectacular", particles: "high", depth: "immersive", camera: "gentle", cinematic: true, energy: true, sound: false, volume: 0.5 };
const INTENSITY = { subtle: 0.45, balanced: 0.75, spectacular: 1 };
const DENSITY = { low: 40, medium: 90, high: 160 };
const TORUS = { low: 260, medium: 520, high: 900 };

export function readFx(raw: string | null): Fx {
  try {
    const v = JSON.parse(raw ?? "{}") as Partial<Fx>;
    const pick = <K extends keyof Fx>(k: K, ok: readonly unknown[]): Fx[K] => (ok.includes(v[k]) ? (v[k] as Fx[K]) : FX_DEFAULT[k]);
    return {
      intensity: pick("intensity", ["subtle", "balanced", "spectacular"]),
      particles: pick("particles", ["low", "medium", "high"]),
      depth: pick("depth", ["standard", "immersive"]),
      camera: pick("camera", ["off", "gentle", "dynamic"]),
      cinematic: typeof v.cinematic === "boolean" ? v.cinematic : true,
      energy: typeof v.energy === "boolean" ? v.energy : true,
      sound: typeof v.sound === "boolean" ? v.sound : false,
      volume: typeof v.volume === "number" ? Math.min(1, Math.max(0, v.volume)) : 0.5,
    };
  } catch {
    return { ...FX_DEFAULT };
  }
}

export function budget(fx: Fx, reduced: boolean, quality = 1) {
  const scale = INTENSITY[fx.intensity];
  return {
    scale,
    particles: reduced ? Math.min(24, DENSITY[fx.particles] / 4) : Math.max(12, Math.round(DENSITY[fx.particles] * scale * Math.max(0.25, Math.min(1, quality)))),
    rings: fx.intensity === "subtle" ? 1 : fx.intensity === "balanced" ? 2 : 3,
    // the core's particle torus: dense enough to read as a luminous ring, bounded for weak GPUs
    torus: reduced ? TORUS[fx.particles] / 2 : Math.max(80, Math.round(TORUS[fx.particles] * (0.6 + 0.4 * scale) * Math.max(0.25, Math.min(1, quality)))),
    animate: !reduced,
  };
}

/** Real changes between two session snapshots → effect names (opening a session is not an event). */
export function events(prev: OrbitSession | null, next: OrbitSession | null): string[] {
  if (!prev || !next || prev.id !== next.id) return [];
  const out: string[] = [];
  const done = (s: OrbitSession) => (s.workflow?.nodes ?? []).filter((n) => n.status === "completed").length;
  const waiting = (s: OrbitSession) => (s.workflow?.nodes ?? []).filter((n) => n.status === "awaiting_approval").length;
  if (next.versions.length > prev.versions.length) out.push(prev.versions.length === 0 ? "project.created" : "plan.updated");
  if (next.approved_version && next.approved_version !== prev.approved_version) out.push("plan.approved");
  if (done(next) > done(prev)) out.push("step.completed");
  if (next.workflow?.state === "completed" && prev.workflow?.state !== "completed") out.push("workflow.completed");
  if (waiting(next) > waiting(prev)) out.push("approval.requested");
  if (next.completed && !prev.completed) out.push("workflow.completed");
  return out;
}

export class FrameMonitor {
  quality = 1;
  private samples: number[] = [];
  constructor(
    private window = 45,
    private slow = 34,
    private fast = 20,
  ) {}
  add(ms: number): number {
    this.samples.push(Math.max(0, ms));
    if (this.samples.length >= this.window) {
      const avg = this.samples.reduce((a, b) => a + b, 0) / this.samples.length;
      this.samples = [];
      if (avg > this.slow) this.quality = Math.max(0.25, this.quality - 0.25);
      else if (avg < this.fast && this.quality < 1) this.quality = Math.min(1, this.quality + 0.125);
    }
    return this.quality;
  }
}

// ---------------------------------------------------------------- core geometry and curved connections

export type V3 = [number, number, number];
export type Pt = { x: number; y: number };

/** `n` particles on a torus as [u around the ring, v around the tube, radial jitter, size]; deterministic. */
export function torus(n: number, seed = 11): [number, number, number, number][] {
  let x = seed >>> 0;
  const rnd = () => ((x = (Math.imul(x, 1664525) + 1013904223) >>> 0) / 4294967296);
  const out: [number, number, number, number][] = [];
  for (let i = 0; i < Math.max(0, n); i++) {
    const g = (rnd() + rnd() + rnd() - 1.5) * 0.24; // roughly normal, sd ≈ 0.12
    out.push([rnd() * Math.PI * 2, rnd() * Math.PI * 2, g, 0.6 + rnd() * 1.2]);
  }
  return out;
}

export function torusPoint(u: number, v: number, jitter: number, major: number, minor: number): V3 {
  const r = minor * (1 + jitter);
  return [(major + r * Math.cos(v)) * Math.cos(u), r * Math.sin(v), (major + r * Math.cos(v)) * Math.sin(u)];
}

/** Turn about the vertical axis by `yaw`, then tilt toward the viewer by `pitch`; +z faces the viewer. */
export function rotate([x0, y0, z0]: V3, yaw: number, pitch: number): V3 {
  const x = x0 * Math.cos(yaw) + z0 * Math.sin(yaw);
  const z1 = -x0 * Math.sin(yaw) + z0 * Math.cos(yaw);
  return [x, y0 * Math.cos(pitch) - z1 * Math.sin(pitch), y0 * Math.sin(pitch) + z1 * Math.cos(pitch)];
}

/** A geodesic sphere: an icosahedron split `frequency` times, on the unit sphere (frequency 1: 42 vertices, 120 edges). */
export function geodesic(frequency = 1): { verts: V3[]; edges: [number, number][] } {
  const t = (1 + Math.sqrt(5)) / 2;
  const unit = (v: V3): V3 => {
    const n = Math.hypot(v[0], v[1], v[2]);
    return [v[0] / n, v[1] / n, v[2] / n];
  };
  const verts: V3[] = ([[-1, t, 0], [1, t, 0], [-1, -t, 0], [1, -t, 0], [0, -1, t], [0, 1, t], [0, -1, -t], [0, 1, -t], [t, 0, -1], [t, 0, 1], [-t, 0, -1], [-t, 0, 1]] as V3[]).map(unit);
  let faces: [number, number, number][] = [[0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11], [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8],
    [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9], [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1]];
  for (let f = 0; f < frequency; f++) {
    const cache = new Map<string, number>();
    const mid = (a: number, b: number) => {
      const k = a < b ? `${a},${b}` : `${b},${a}`;
      if (!cache.has(k)) {
        const va = verts[a]!;
        const vb = verts[b]!;
        verts.push(unit([(va[0] + vb[0]) / 2, (va[1] + vb[1]) / 2, (va[2] + vb[2]) / 2]));
        cache.set(k, verts.length - 1);
      }
      return cache.get(k)!;
    };
    faces = faces.flatMap(([a, b, c]) => {
      const ab = mid(a, b);
      const bc = mid(b, c);
      const ca = mid(c, a);
      return [[a, ab, ca], [b, bc, ab], [c, ca, bc], [ab, bc, ca]] as [number, number, number][];
    });
  }
  const set = new Set<string>();
  const edges: [number, number][] = [];
  for (const [a, b, c] of faces)
    for (const [i, j] of [[a, b], [b, c], [c, a]] as [number, number][]) {
      const k = i < j ? `${i},${j}` : `${j},${i}`;
      if (!set.has(k)) {
        set.add(k);
        edges.push(i < j ? [i, j] : [j, i]);
      }
    }
  return { verts, edges };
}

/** Control point of the quadratic curve a→b: the midpoint pushed sideways by `bend` × length, away from the core. */
export function curveCtrl(a: Pt, b: Pt, centre: Pt, bend = 0.22): Pt {
  const mx = (a.x + b.x) / 2;
  const my = (a.y + b.y) / 2;
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const len = Math.hypot(dx, dy);
  if (len < 1e-6) return { x: mx, y: my };
  let nx = -dy / len;
  let ny = dx / len;
  if ((mx - centre.x) * nx + (my - centre.y) * ny < 0) {
    nx = -nx;
    ny = -ny;
  }
  return { x: mx + nx * len * bend, y: my + ny * len * bend };
}

export function bezier(a: Pt, c: Pt, b: Pt, t: number): Pt {
  const u = 1 - t;
  return { x: u * u * a.x + 2 * u * t * c.x + t * t * b.x, y: u * u * a.y + 2 * u * t * c.y + t * t * b.y };
}

/** Where a line from the core toward `to` meets the torus's rim (an ellipse with radii ra, rb). */
export function rimPoint(centre: Pt, to: Pt, ra: number, rb: number): Pt {
  const dx = to.x - centre.x;
  const dy = to.y - centre.y;
  const k = 1 / Math.max(1e-6, Math.sqrt((dx / ra) ** 2 + (dy / rb) ** 2));
  return { x: centre.x + dx * k, y: centre.y + dy * k };
}

/** One readable caption line from a real transcript line: markdown and plan blocks removed; long text shows its end. */
export function captionText(who: string, text: string, limit = 180): string {
  let t = (text || "").replace(/```[\s\S]*?(```|$)/g, " ").replace(/[*_#>`]+/g, "").replace(/\s+/g, " ").trim();
  if (!t) return "";
  if (t.length > limit) t = "…" + t.slice(-(limit - 1)).trimStart();
  return who ? `${who}: ${t}` : t;
}
