import { describe, expect, it } from "vitest";
import { empty, reduce } from "@/state/turns";
import type { TurnEvent } from "@/lib/schemas";

const approval = {
  id: "ap1",
  task_id: "t1",
  step_id: "s1",
  tool_id: "files.create",
  action_hash: "h",
  preview: { action: "Create", target: "a.md", details: "", consequences: "" },
  status: "pending",
  created_at: "",
  decided_at: null,
};

describe("turn reducer", () => {
  it("streams text, tracks tools through approval, and resets on finish", () => {
    const events: TurnEvent[] = [
      { type: "text_delta", text: "Hel" },
      { type: "text_delta", text: "lo" },
      { type: "tool_call_started", call_id: "c1", name: "files_create" },
      { type: "tool", event: { type: "step_started", step_id: "s1", tool_id: "files.create", task_id: "t1" } },
      { type: "tool", event: { type: "approval_required", approval } },
    ];
    let s = { ...empty(), running: true };
    for (const e of events) s = reduce(s, e);
    expect(s.text).toBe("Hello");
    expect(s.taskId).toBe("t1");
    expect(s.tools).toHaveLength(1);
    expect(s.tools[0]).toMatchObject({ toolId: "files.create", status: "awaiting_approval" });
    s = reduce(s, { type: "tool", event: { type: "step_finished", step_id: "s1", tool_id: "files.create", status: "succeeded", task_id: "t1" } });
    expect(s.tools[0]).toMatchObject({ status: "succeeded", approval: undefined });
    s = reduce(s, { type: "finished", outcome: "completed", error: null, usage: { input_tokens: 1, output_tokens: 2 }, estimated_cost_usd: null, task_id: "t1" });
    expect(s.running).toBe(false);
    expect(s.text).toBe("");
    expect(s.outcome).toBe("completed");
  });

  it("discards partial text on step_reset (retry)", () => {
    let s = reduce(empty(), { type: "text_delta", text: "partial" });
    s = reduce(s, { type: "step_reset", reason: "retrying" });
    expect(s.text).toBe("");
  });
});
