import { TooltipProvider } from "@radix-ui/react-tooltip";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { describe as describeEvent } from "@/features/trust/Trust";
import { contextWords, SpecialistsPage, stepState } from "@/features/specialists/Specialists";
import type { AuditEvent, MissionStep, SpecialistsOverview } from "@/lib/schemas";

const start = vi.fn().mockResolvedValue({});
const cancel = vi.fn().mockResolvedValue(true);
const toggle = vi.fn().mockResolvedValue(undefined);

const def = (id: string, name: string, extra: Partial<SpecialistsOverview["specialists"][0]["specialist"]> = {}) => ({
  id, name, summary: `${name} summary`, domain: "research", version: 1, tools: [], memories: 0, vault_passages: 0, tasks: false, projects: false, forge: null, tier_hint: "standard", max_steps: 4, timeout_secs: 120, max_output_tokens: 1200, needs: "an objective", role: "r", ...extra,
});
const step = (o: Partial<MissionStep>): MissionStep => ({ id: "s1", seq: 0, specialist_id: "researcher", specialist_version: 1, status: "completed", task_id: null, provider: "Ollama", model: "llama", local: true, input_tokens: 100, output_tokens: 50, estimated_cost_usd: 0, context_manifest: {}, result: null, error: null, started_at: null, finished_at: null, awaiting_approval: false, ...o });
const overview: SpecialistsOverview = {
  enabled: true,
  specialists: [
    { specialist: def("researcher", "Researcher", { tools: ["web.search"] }), enabled: true, tools: [{ id: "web.search", registered: true, enabled: true, permission: "read_only", network: true }] },
    { specialist: def("writer", "Writer", { memories: 2 }), enabled: true, tools: [] },
    { specialist: def("engineer", "Engineer", { forge: "builder" }), enabled: false, tools: [] },
  ],
  workflows: [{ id: "research_report", name: "Research, then write", steps: ["researcher", "writer"] }],
  missions: [
    {
      id: "m1", title: "Compare heat pumps", objective: "Compare heat pumps", workflow: ["researcher", "writer"], origin: "atlas", status: "running", conversation_id: null, project_id: null, forge_project_id: null, error: null, created_at: new Date().toISOString(), updated_at: new Date().toISOString(), finished_at: null,
      steps: [
        step({ result: { summary: "Three models compared", findings: ["Model A is quietest"], evidence: [{ source: "vault: specs.pdf", detail: "" }], recommendations: [], uncertainties: [], warnings: ["Prices change often"], disagreements: [], proposed_actions: [] } }),
        step({ id: "s2", seq: 1, specialist_id: "writer", status: "running", awaiting_approval: true, provider: null }),
      ],
    },
  ],
};

vi.mock("@/lib/bridge", () => ({
  AtlasError: class AtlasError extends Error {},
  api: {
    specialistsOverview: () => Promise.resolve(overview),
    settings: () => Promise.resolve({ specialists: { enabled: true } }),
    updateSettings: vi.fn(),
    projects: () => Promise.resolve([]),
    forgeProjects: () => Promise.resolve([]),
    startSpecialistMission: (...a: unknown[]) => start(...a),
    cancelSpecialistMission: (id: string) => cancel(id),
    setSpecialistEnabled: (...a: unknown[]) => toggle(...a),
  },
}));
vi.mock("@/lib/events", () => ({ onChange: () => () => {} }));

const ui = () => render(<TooltipProvider><SpecialistsPage /></TooltipProvider>);
const ev = (o: Partial<AuditEvent>): AuditEvent => ({ id: 1, ts: new Date().toISOString(), kind: "app.start", level: "info", task_id: null, tool_id: null, detail: {}, category: "specialists", actor: "atlas", resource: null, project_id: null, provider: null, model: null, left_device: false, approval: null, outcome: "ok", reversible: null, ...o });

describe("Specialists", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows progress only from what the core reports", () => {
    expect(stepState(step({ status: "running", awaiting_approval: true }))).toBe("Awaiting your approval");
    expect(stepState(step({ status: "running" }))).toBe("Running");
    expect(stepState(step({ status: "invalid_output" }))).toBe("Returned an invalid result");
    expect(contextWords({ memories: ["a", "b"], vault_withheld: 2, forge_project: "p" })).toEqual(["2 relevant memories", "document passages withheld (local-only)", "a Forge project"]);
    expect(contextWords(null)).toEqual([]);
  });

  it("lists the team, missions and results, and starts and cancels missions", async () => {
    ui();
    expect(await screen.findByText("Compare heat pumps")).toBeInTheDocument();
    expect(screen.getByText("Three models compared")).toBeInTheDocument();
    expect(screen.getByText("Awaiting your approval")).toBeInTheDocument();
    expect(screen.getByText(/Prices change often/)).toBeInTheDocument();
    expect(screen.getByText(/web\.search \(internet\)/)).toBeInTheDocument();
    expect(screen.getByText(/started by Atlas/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Cancel/ }));
    await waitFor(() => expect(cancel).toHaveBeenCalledWith("m1"));

    const go = screen.getByRole("button", { name: /Start mission/ });
    expect(go).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Objective"), { target: { value: "Summarise the heat pump options" } });
    fireEvent.click(go);
    await waitFor(() => expect(start).toHaveBeenCalledWith("Summarise the heat pump options", ["researcher", "writer"], null, null));
  });

  it("will not start a team with a switched-off specialist", async () => {
    ui();
    fireEvent.change(await screen.findByLabelText("Who works on it"), { target: { value: "engineer" } });
    fireEvent.change(screen.getByLabelText("Objective"), { target: { value: "Fix the failing test" } });
    expect(screen.getByRole("button", { name: /Start mission/ })).toBeDisabled();
    expect(screen.getByText(/Switched off: engineer/)).toBeInTheDocument();
  });

  it("describes specialist activity in the Trust Center", () => {
    expect(describeEvent(ev({ kind: "specialist.mission_started", actor: "user", detail: { specialists: ["researcher", "writer"] } }))).toBe("You started a specialist mission (Researcher → Writer)");
    expect(describeEvent(ev({ kind: "specialist.completed", detail: { specialist: "researcher", findings: 2, warnings: 1 } }))).toBe("Researcher completed: 2 findings, 1 warning");
    expect(describeEvent(ev({ kind: "specialist.failed", detail: { specialist: "writer", reason: "timed out" } }))).toBe("Writer did not finish: timed out");
  });
});
