/**
 * ORBIT (Atlas) — pure logic used by the page, unit-tested:
 *  - `TurnTaker` ends your spoken turn from the real microphone level (no audio is kept here);
 *  - `parseCommand` recognises direct plan edits and control words, which run locally without a model;
 *  - `partialPlan` / `stripPlanBlocks` show a plan progressively while Atlas's reply streams.
 * The core re-checks every edit (atlas_core::orbit); nothing here changes a session by itself.
 */
import type { OrbitPlan } from "@/lib/schemas";

export type TurnEvent = "speech" | "end" | "idle" | null;

export class TurnTaker {
  floor = 0.02;
  speaking = false;
  private t0: number | null = null;
  private lastT: number | null = null;
  private speechStart: number | null = null;
  private lastLoud: number | null = null;
  private loudRun = 0;
  private idleSent = false;
  constructor(
    public silence = 1.2,
    public minSpeech = 0.35,
    public idleTimeout = 30,
    public sensitivity = 0.5,
  ) {}

  threshold(): number {
    return Math.min(0.6, this.floor + (0.1 - 0.07 * Math.max(0, Math.min(1, this.sensitivity))));
  }

  reset(t: number): void {
    this.t0 = t;
    this.lastT = t;
    this.speechStart = null;
    this.lastLoud = null;
    this.loudRun = 0;
    this.speaking = false;
    this.idleSent = false;
  }

  /** One level sample (0..1) at time t (seconds). */
  feed(level: number, t: number): TurnEvent {
    if (this.t0 === null) this.reset(t);
    const dt = Math.max(0, t - (this.lastT ?? t));
    this.lastT = t;
    const lv = Math.min(level, 0.5);
    // the noise floor drops quickly to quiet moments and rises slowly to steady background sound
    this.floor = lv < this.floor ? 0.7 * this.floor + 0.3 * lv : this.floor + (lv - this.floor) * 0.03;
    const loud = level >= this.threshold();
    if (loud) {
      this.loudRun += dt;
      this.lastLoud = t;
      if (!this.speaking && this.loudRun >= 0.12) {
        this.speaking = true;
        this.speechStart = t - this.loudRun;
        return "speech";
      }
    } else this.loudRun = 0;
    if (this.speaking && this.lastLoud !== null && t - this.lastLoud >= this.silence) {
      const spoken = this.lastLoud - (this.speechStart ?? this.lastLoud);
      this.speaking = false;
      if (spoken >= this.minSpeech) return "end";
      this.speechStart = null;
      return null;
    }
    if (
      !this.speaking &&
      this.speechStart === null &&
      this.t0 !== null &&
      t - this.t0 >= this.idleTimeout &&
      !this.idleSent
    ) {
      this.idleSent = true;
      return "idle";
    }
    return null;
  }
}

export function findTask(plan: OrbitPlan, ref: string) {
  const l = ref
    .trim()
    .toLowerCase()
    .replace(/^["'“”]+|["'“”.]+$/g, "");
  if (!l) return undefined;
  const exact = plan.tasks.find((t) => t.id === ref || t.title.toLowerCase() === l);
  if (exact) return exact;
  const hits = plan.tasks.filter((t) => t.title.toLowerCase().includes(l));
  return hits.length === 1 ? hits[0] : undefined;
}

function matchPhase(plan: OrbitPlan, name: string): string | undefined {
  const n = name.trim().toLowerCase();
  return (
    plan.phases.find((p) => p.toLowerCase() === n) ??
    (plan.phases.filter((p) => n && p.toLowerCase().includes(n)).length === 1
      ? plan.phases.find((p) => p.toLowerCase().includes(n))
      : undefined)
  );
}

export type Command =
  { control: "stop_speaking" | "pause" | "resume" | "cancel" } | { undo: true } | { edit: Record<string, string> };

const CONTROL: Record<string, "stop_speaking" | "pause" | "resume" | "cancel"> = {
  stop: "stop_speaking",
  wait: "stop_speaking",
  "hold on": "stop_speaking",
  pause: "pause",
  "pause the workflow": "pause",
  resume: "resume",
  continue: "resume",
  "cancel the workflow": "cancel",
};

/** A direct edit or control word in what was said or typed; null means "send it to Atlas". */
export function parseCommand(text: string, plan: OrbitPlan | null): Command | null {
  const t = text
    .trim()
    .replace(/[.!?]+$/, "")
    .replace(/\s+/g, " ");
  const low = t.toLowerCase();
  if (CONTROL[low]) return { control: CONTROL[low] };
  if (!plan) return null;
  let m: RegExpMatchArray | null;
  const g = (i: number) => m?.[i] ?? "";
  if (
    (m = t.match(
      /^(?:please\s+)?move (?:the )?(?:phase )?(.+?) (?:phase )?before (?:the )?(?:phase )?(.+?)(?: phase)?$/i,
    ))
  ) {
    const a = matchPhase(plan, g(1));
    const b = matchPhase(plan, g(2));
    if (a && b && a !== b) return { edit: { op: "move_phase_before", phase: a, other: b } };
    if (findTask(plan, g(1)) && findTask(plan, g(2))) return { edit: { op: "move_before", task: g(1), other: g(2) } };
    return null;
  }
  if (
    (m = t.match(
      /^(?:please\s+)?(?:add|create) (?:a )?task (?:called |named )?(.+?)(?: (?:to|in|under) (?:the )?(.+?)(?: phase)?)?$/i,
    ))
  )
    return { edit: { op: "add_task", title: g(1), phase: g(2) } };
  if ((m = t.match(/^(?:please\s+)?(?:remove|delete|drop) (?:the )?task (.+)$/i)))
    return { edit: { op: "remove_task", task: g(1) } };
  if ((m = t.match(/^(?:please\s+)?rename (?:the )?task (.+?) to (.+)$/i)))
    return { edit: { op: "rename_task", task: g(1), title: g(2) } };
  if ((m = t.match(/^(?:please\s+)?make (.+?) (high|normal|low) priority$/i)))
    return findTask(plan, g(1)) ? { edit: { op: "set_priority", task: g(1), priority: g(2).toLowerCase() } } : null;
  if ((m = t.match(/^(.+?) (?:must|should) (?:come )?after (.+)$/i)))
    return findTask(plan, g(1)) && findTask(plan, g(2)) ? { edit: { op: "add_dep", before: g(2), after: g(1) } } : null;
  if (/^(?:please\s+)?undo(?: that)?$/i.test(t)) return { undo: true };
  return null;
}

export function partialPlan(text: string): { title: string; brief: string; ideas: string[]; phases: string[]; tasks: string[] } {
  const i = text.lastIndexOf("```orbit-plan");
  if (i < 0) return { title: "", brief: "", ideas: [], phases: [], tasks: [] };
  const body = text.slice(i);
  const ph = body.match(/"phases"\s*:\s*\[([^\]]*)\]/);
  const phases = ph ? [...(ph[1] ?? "").matchAll(/"([^"]{1,80})"/g)].map((x) => x[1] ?? "") : [];
  const tasks = [...body.matchAll(/"title"\s*:\s*"([^"]{1,160})"\s*,\s*"phase"/g)].map((x) => x[1] ?? "");
  const id = body.match(/"ideas"\s*:\s*\[([^\]]*)\]/);
  const ideas = id ? [...(id[1] ?? "").matchAll(/"([^"]{1,300})"/g)].map((x) => x[1] ?? "") : [];
  const title = body.match(/^```orbit-plan\s*\{\s*"title"\s*:\s*"([^"]{1,120})"/)?.[1] ?? "";
  const brief = (body.match(/"brief"\s*:\s*"((?:[^"\\]|\\.){1,1200})"/)?.[1] ?? "").replace(/\\"/g, '"');
  return { title, brief, ideas: ideas.slice(0, 20), phases: phases.slice(0, 20), tasks: tasks.slice(0, 80) };
}

export function stripPlanBlocks(text: string): string {
  const t = text.replace(/```orbit-plan[\s\S]*?```/g, "");
  const j = t.indexOf("```orbit-plan");
  return (j >= 0 ? t.slice(0, j) : t).trim();
}

/** Positions of tasks on their phase orbits (phases are concentric rings; the top of each is its label). */
export function layout(plan: OrbitPlan, size: { w: number; h: number }) {
  const base = Math.min(size.w, size.h);
  const n = Math.max(1, plan.phases.length);
  const inner = base * 0.24;
  const outer = base * 0.46;
  const radius = (i: number) => (n > 1 ? inner + ((outer - inner) * i) / (n - 1) : (inner + outer) / 2);
  const pos: Record<string, { x: number; y: number; ring: number }> = {};
  plan.phases.forEach((ph, i) => {
    const items = plan.tasks.filter((t) => t.phase === ph);
    const off = -Math.PI / 2 + 0.5 + i * 0.6;
    items.forEach((t, k) => {
      const a = off + (k * Math.PI * 2) / Math.max(1, items.length);
      pos[t.id] = { x: size.w / 2 + Math.cos(a) * radius(i), y: size.h / 2 + Math.sin(a) * radius(i), ring: i };
    });
  });
  return { pos, radius };
}
