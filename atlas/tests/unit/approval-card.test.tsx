import * as Tooltip from "@radix-ui/react-tooltip";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApprovalCard } from "@/components/ApprovalCard";

const decide = vi.fn().mockResolvedValue(null);
vi.mock("@/lib/bridge", () => ({
  isTauri: () => true,
  AtlasError: class extends Error {},
  api: {
    decideApproval: (...a: unknown[]) => decide(...a),
    tools: () =>
      Promise.resolve([{ id: "files.create", name: "Create a file", permission: "local_write", network: false }]),
    taskDetail: () => Promise.resolve({ task: { request: "Write my notes" }, steps: [], approvals: [] }),
  },
}));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn().mockResolvedValue(() => {}) }));
vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { error: vi.fn() }) }));

const approval = {
  id: "ap-42",
  task_id: "t1",
  step_id: "s1",
  tool_id: "files.create",
  action_hash: "abc",
  preview: { action: "Create a new file", target: "Workspace / notes.md", details: "# Notes", consequences: "A new file will be created." },
  status: "pending",
  created_at: new Date().toISOString(),
  decided_at: null,
};

describe("ApprovalCard", () => {
  beforeEach(() => decide.mockClear());

  it("shows exactly what will happen", async () => {
    render(<Tooltip.Provider><ApprovalCard approval={approval} /></Tooltip.Provider>);
    expect(screen.getByText("Create a new file")).toBeInTheDocument();
    expect(screen.getByText("Workspace / notes.md")).toBeInTheDocument();
    expect(screen.getByText("# Notes")).toBeInTheDocument();
    expect(await screen.findByText(/Write my notes/)).toBeInTheDocument();
    expect(await screen.findByText("Local write")).toBeInTheDocument();
  });

  it("sends the decision for this approval only", async () => {
    render(<Tooltip.Provider><ApprovalCard approval={approval} /></Tooltip.Provider>);
    fireEvent.click(screen.getByRole("button", { name: /Decline/ }));
    await waitFor(() => expect(decide).toHaveBeenCalledWith("ap-42", false));
    expect(decide).toHaveBeenCalledTimes(1);
  });
});
