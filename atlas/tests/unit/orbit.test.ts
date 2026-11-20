import { describe, expect, it } from "vitest";
import { TurnTaker, findTask, layout, parseCommand, partialPlan, stripPlanBlocks } from "@/features/orbit/orbitLogic";
import { OrbitResultSchema } from "@/lib/schemas";
import type { OrbitPlan } from "@/lib/schemas";

const plan: OrbitPlan = {
  title: "Launch",
  objective: "",
  outcome: "",
  brief: "",
  ideas: [],
  phases: ["Research", "Build", "Release"],
  tasks: [
    {
      id: "r1",
      title: "Survey hosting",
      phase: "Research",
      detail: "",
      priority: "normal",
      estimate: "",
      status: "proposed",
      operation: "atlas",
    },
    {
      id: "b1",
      title: "Write pages",
      phase: "Build",
      detail: "",
      priority: "high",
      estimate: "",
      status: "proposed",
      operation: "atlas",
    },
    {
      id: "b2",
      title: "Write tests",
      phase: "Build",
      detail: "",
      priority: "normal",
      estimate: "",
      status: "proposed",
      operation: "atlas",
    },
    {
      id: "x1",
      title: "Publish",
      phase: "Release",
      detail: "",
      priority: "normal",
      estimate: "",
      status: "proposed",
      operation: "manual",
    },
  ],
  deps: [{ from: "r1", to: "b1" }],
  assumptions: [],
  questions: [],
  risks: [],
};

function run(tt: TurnTaker, seq: [number, number][], dt = 0.04) {
  let t = 0;
  const out: string[] = [];
  for (const [level, secs] of seq)
    for (let i = 0; i < Math.round(secs / dt); i++) {
      const e = tt.feed(level, t);
      if (e) out.push(e);
      t += dt;
    }
  return out;
}

describe("ORBIT turn-taking", () => {
  it("ends the turn after speech and a pause", () =>
    expect(
      run(new TurnTaker(1.0), [
        [0.01, 1],
        [0.4, 1.5],
        [0.01, 1.5],
      ]),
    ).toEqual(["speech", "end"]));
  it("ignores a cough and keeps one turn across short pauses", () => {
    expect(
      run(new TurnTaker(1.0), [
        [0.01, 0.5],
        [0.5, 0.2],
        [0.01, 1.5],
      ]),
    ).not.toContain("end");
    expect(
      run(new TurnTaker(1.0), [
        [0.4, 1],
        [0.01, 0.6],
        [0.4, 1],
        [0.01, 1.2],
      ]).filter((e) => e === "end"),
    ).toHaveLength(1);
  });
  it("closes the microphone after a long silence, once", () =>
    expect(run(new TurnTaker(1.2, 0.35, 3), [[0, 4]])).toEqual(["idle"]));
});

describe("ORBIT commands", () => {
  it("recognises edits and control words, and sends questions to Atlas", () => {
    expect(parseCommand("Move Release before Build.", plan)).toEqual({
      edit: { op: "move_phase_before", phase: "Release", other: "Build" },
    });
    expect(parseCommand("add task Check links to Release", plan)).toEqual({
      edit: { op: "add_task", title: "Check links", phase: "Release" },
    });
    expect(parseCommand("Publish must come after Survey hosting", plan)).toEqual({
      edit: { op: "add_dep", before: "Survey hosting", after: "Publish" },
    });
    expect(parseCommand("Add an idea: a dark theme", plan)).toEqual({ edit: { op: "add_idea", idea: "a dark theme" } });
    expect(parseCommand("remove idea dark theme", plan)).toEqual({ edit: { op: "remove_idea", idea: "dark theme" } });
    expect(parseCommand("undo", plan)).toEqual({ undo: true });
    expect(parseCommand("Stop", null)).toEqual({ control: "stop_speaking" });
    expect(parseCommand("What does hosting cost?", plan)).toBeNull();
    expect(parseCommand("make it faster high priority", plan)).toBeNull();
  });
  it("never guesses between several tasks", () => {
    expect(findTask(plan, "write")).toBeUndefined();
    expect(findTask(plan, "write tests")?.id).toBe("b2");
  });
});

describe("ORBIT streaming and layout", () => {
  it("shows arrived tasks while the plan streams and hides plan blocks from the transcript", () => {
    expect(
      partialPlan(
        'ok ```orbit-plan {"phases":["A","B"],"tasks":[{"id":"1","title":"First","phase":"A"},{"id":"2","title":"Sec',
      ),
    ).toMatchObject({ phases: ["A", "B"], tasks: ["First"] });
    expect(stripPlanBlocks('Here.\n```orbit-plan {"title":"x"}```\nOK?')).toBe("Here.\n\nOK?");
    expect(stripPlanBlocks('Talking ```orbit-plan {"pha')).toBe("Talking");
  });
  it("places every task on its phase's orbit", () => {
    const { pos, radius } = layout(plan, { w: 800, h: 600 });
    for (const t of plan.tasks) {
      const p = pos[t.id]!;
      const ring = plan.phases.indexOf(t.phase);
      expect(Math.abs(Math.hypot(p.x - 400, p.y - 300) - radius(ring))).toBeLessThan(0.01);
    }
  });
  it("validates the core's session contract", () => {
    const session = {
      id: "s",
      title: "t",
      created_at: "",
      updated_at: "",
      conversation_id: null,
      autonomy: "approval_first",
      allowed: [],
      versions: [{ version: 1, plan, author: "atlas", why: "Proposed", at: "" }],
      active_version: 1,
      approved_version: 0,
      workflow: null,
      events: [],
      archived: false,
    };
    expect(OrbitResultSchema.safeParse({ session, message: "" }).success).toBe(true);
    expect(OrbitResultSchema.safeParse({ session: { ...session, versions: "x" }, message: "" }).success).toBe(false);
  });
});
