import { describe, expect, it } from "vitest";
import { canRegenerate, conversationToMarkdown, lastQuestionUnanswered } from "@/features/companion/conversation";
import type { Message } from "@/lib/schemas";

let seq = 0;
const msg = (role: Message["role"], content: string, parts: Message["parts"] = null): Message => ({
  id: `m${++seq}`,
  conversation_id: "c",
  seq,
  role,
  content,
  parts,
  provider_id: null,
  model: null,
  status: "complete",
  task_id: null,
  usage: null,
  created_at: "2026-11-08T10:00:00Z",
});

describe("regenerate rule (mirrors the core)", () => {
  it("allows replacing a text reply", () => {
    expect(canRegenerate([msg("user", "hi"), msg("assistant", "hello")])).toBe(true);
  });
  it("allows trying again after a failed request", () => {
    const m = [msg("user", "hi"), msg("notice", "provider unavailable")];
    expect(canRegenerate(m)).toBe(true);
    expect(lastQuestionUnanswered(m)).toBe(true);
  });
  it("refuses when the reply used tools, so no action can repeat", () => {
    const call = msg("assistant", "", [{ type: "tool_call", id: "c1", name: "files_create", input: {} }]);
    expect(canRegenerate([msg("user", "write it"), call, msg("tool", "done"), msg("assistant", "Done.")])).toBe(false);
  });
  it("needs a question to answer", () => {
    expect(canRegenerate([])).toBe(false);
    expect(lastQuestionUnanswered([msg("user", "a"), msg("assistant", "b")])).toBe(false);
  });
});

describe("copy conversation", () => {
  it("writes readable Markdown and summarises tools instead of dumping them", () => {
    const md = conversationToMarkdown("Trip plan", [
      msg("user", "Plan a day in Lisbon"),
      msg("assistant", "Here is a plan.", [{ type: "tool_call", id: "c1", name: "web_search", input: {} }]),
      msg("tool", '{"raw":"tool output"}'),
      msg("notice", "Stopped by you."),
    ]);
    expect(md).toBe("# Trip plan\n\n## You\n\nPlan a day in Lisbon\n\n## Atlas\n\nHere is a plan.\n\n_Used: web.search_\n\n> Stopped by you.\n");
    expect(md).not.toContain("tool output");
  });
});
