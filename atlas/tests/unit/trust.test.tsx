import { TooltipProvider } from "@radix-ui/react-tooltip";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AuditEvent, Memory, TrustOverview } from "@/lib/schemas";

const timeline = vi.fn();
const updateSettings = vi.fn().mockResolvedValue({});
const updateProvider = vi.fn().mockResolvedValue({});
const revokeGrant = vi.fn().mockResolvedValue(undefined);
const confirmMemory = vi.fn().mockResolvedValue({});
const restoreMemory = vi.fn().mockResolvedValue({});
const memories = vi.fn();
const similar = vi.fn().mockResolvedValue([]);
const settings = { permissions: { local_write: "ask", network_tools: "ask", planner: "allow" }, network: { offline_mode: false }, memory: { enabled: true, max_retrieved: 6, atlas_may_propose: true }, vault: { use_in_chat: true, local_only: false, max_passages: 4 }, schedule: { paused: false } };
const overview: TrustOverview = {
  since: "2026-11-08T00:00:00Z",
  categories: [{ category: "providers", events: 3, problems: 1 }],
  left_device_7d: 2,
  providers: [
    { id: "p1", label: "Claude", kind: "anthropic", local: false, enabled: true, is_default: true, requests_30d: 12, failed_30d: 1, input_tokens_30d: 4200, output_tokens_30d: 900, estimated_cost_usd_30d: 0.12, unpriced_requests_30d: 0, last_used_at: new Date().toISOString() },
    { id: "p2", label: "Ollama", kind: "ollama", local: true, enabled: true, is_default: false, requests_30d: 0, failed_30d: 0, input_tokens_30d: 0, output_tokens_30d: 0, estimated_cost_usd_30d: 0, unpriced_requests_30d: 0, last_used_at: null },
  ],
  routing: { default_provider: "Claude", default_model: "claude-x", mode: "single", cross_provider_fallback: false, offline_mode: false },
  permissions: [
    { id: "local_write", name: "Changes on this computer", allows: "…", status: "Asks you each time", open: false, scope: "All conversations", component: "Tools", last_used_at: null, control: { kind: "gate", setting: "permissions.local_write" } },
    { id: "schedule", name: "Background activity", allows: "…", status: "Running", open: true, scope: "This computer", component: "Scheduler", last_used_at: null, control: { kind: "switch", setting: "schedule.paused" } },
    { id: "provider:p1", name: "Model provider: Claude", allows: "…", status: "Enabled", open: true, scope: "Leaves this computer", component: "Providers", last_used_at: null, control: { kind: "provider", provider_id: "p1" } },
    { id: "grant:g1", name: "Folder: Notes", allows: "…", status: "Granted", open: true, scope: "/home/notes", component: "Files", last_used_at: null, control: { kind: "grant", grant_id: "g1" } },
  ],
  background: { running_conversations: 0, pending_approvals: 1, scheduler: { pending: 2, running: 0, missed_7d: 0, next_at: null }, vault: [{ id: "d1", title: "scan", status: "failed" }], missions_active: 0, forge_runs_running: 0, tasks_interrupted_7d: 0 },
  retention: { events_stored: 3, oldest_event: null, max_events: 50000, audit_days: null, conversation_days: null },
};
const ev = (o: Partial<AuditEvent>): AuditEvent => ({ id: 1, ts: new Date().toISOString(), kind: "app.start", level: "info", task_id: null, tool_id: null, detail: {}, category: "system", actor: "atlas", resource: null, project_id: null, provider: null, model: null, left_device: false, approval: null, outcome: "ok", reversible: null, ...o });

vi.mock("@/lib/bridge", () => ({
  AtlasError: class AtlasError extends Error {},
  api: {
    trustOverview: () => Promise.resolve(overview),
    trustTimeline: (f: unknown) => timeline(f),
    trustExport: vi.fn(),
    trustClear: vi.fn(),
    settings: () => Promise.resolve(settings),
    updateSettings: (s: unknown) => updateSettings(s),
    providers: () => Promise.resolve([{ id: "p1", label: "Claude", base_url: "https://x", default_model: "m", enabled: true }]),
    updateProvider: (...a: unknown[]) => updateProvider(...a),
    revokeGrant: (id: string) => revokeGrant(id),
    projects: () => Promise.resolve([]),
    memories: () => memories(),
    searchMemories: () => Promise.resolve(null),
    memorySimilar: (...a: unknown[]) => similar(...a),
    memoryHistory: () => Promise.resolve([{ ts: new Date().toISOString(), action: "edited", actor: "user", old_content: "Old text", new_content: "New text" }]),
    confirmMemory: (id: string) => confirmMemory(id),
    restoreMemory: (id: string) => restoreMemory(id),
    markMemoryOutdated: vi.fn(),
    replaceMemory: vi.fn(),
    updateMemory: vi.fn(),
    deleteMemory: vi.fn(),
    createMemory: vi.fn(),
    exportMemories: vi.fn(),
    deleteAllMemories: vi.fn(),
  },
}));
vi.mock("@/lib/events", () => ({ onChange: () => () => {} }));

const { TrustPage, describe: sentence } = await import("@/features/trust/Trust");
const { MemoryPage } = await import("@/features/memory/Memory");

describe("Trust Center", () => {
  beforeEach(() => {
    timeline.mockReset();
    updateSettings.mockClear();
  });

  it("describes events in plain words from their recorded fields only", () => {
    expect(sentence(ev({ kind: "vault.passages", provider: "Claude", model: "m", left_device: true, detail: { passages: 2, documents: ["glacier-report"] } }))).toBe("2 passages from glacier-report went with a message (Claude · m)");
    expect(sentence(ev({ kind: "provider.request", provider: "Claude", model: "m", detail: { input_tokens: 10, output_tokens: 5 } }))).toBe("A request was answered by Claude · m: 10 tokens in, 5 out");
    expect(sentence(ev({ kind: "memory.created", actor: "assistant" }))).toBe("Atlas saved a memory you approved");
    expect(sentence(ev({ kind: "approval.decided", approval: "declined", resource: "files.create" }))).toBe("Approval declined for files.create");
  });

  it("shows where messages go, labels costs as estimates, and lists what is running", async () => {
    timeline.mockResolvedValue([]);
    render(<TooltipProvider><TrustPage /></TooltipProvider>);
    const claude = await screen.findByText("Claude", { selector: "[data-provider] span" });
    const row = claude.closest("[data-provider]")!;
    expect(row.textContent).toContain("Cloud: leaves this computer");
    expect(row.textContent).toContain("estimated");
    expect(document.querySelector('[data-provider="Ollama"]')?.textContent).toContain("On this computer");
    expect(document.querySelector("[data-left-device-count]")?.textContent).toBe("2");
    expect(screen.getByText(/1 approval waiting for you/)).toBeTruthy();
  });

  it("changes permissions through the validated settings and provider commands", async () => {
    timeline.mockResolvedValue([]);
    render(<TooltipProvider><TrustPage /></TooltipProvider>);
    const gate = (await screen.findByLabelText("Changes on this computer")) as HTMLSelectElement;
    await waitFor(() => expect(gate.value).toBe("ask"));
    fireEvent.change(gate, { target: { value: "allow" } });
    await waitFor(() => expect(updateSettings).toHaveBeenCalled());
    expect(updateSettings.mock.calls[0]![0].permissions.local_write).toBe("allow");
    // "Background activity" is shown as running; turning it off pauses (inverted setting).
    fireEvent.click(screen.getByRole("switch", { name: "Background activity" }));
    await waitFor(() => expect(updateSettings.mock.calls[1]?.[0].schedule.paused).toBe(true));
    fireEvent.click(await screen.findByRole("switch", { name: "Model provider: Claude" }));
    await waitFor(() => expect(updateProvider).toHaveBeenCalledWith("p1", "Claude", "https://x", "m", false));
    fireEvent.click(screen.getByRole("button", { name: "Revoke" }));
    await waitFor(() => expect(revokeGrant).toHaveBeenCalledWith("g1"));
  });

  it("filters and pages the timeline without loading it all", async () => {
    const page1 = Array.from({ length: 40 }, (_, i) => ev({ id: 100 - i, kind: "tool.step", resource: "files.read" }));
    timeline.mockResolvedValueOnce(page1).mockResolvedValue([ev({ id: 10, kind: "app.start" })]);
    render(<TooltipProvider><TrustPage /></TooltipProvider>);
    await screen.findAllByText("Tool files.read ran");
    expect(timeline.mock.calls[0]![0]).toMatchObject({ before_id: null, limit: 40, left_device_only: false });
    fireEvent.click(screen.getByRole("button", { name: "Show older activity" }));
    await waitFor(() => expect(timeline).toHaveBeenCalledWith(expect.objectContaining({ before_id: 61 })));
    fireEvent.click(screen.getByRole("button", { name: "Left this computer" }));
    await waitFor(() => expect(timeline).toHaveBeenLastCalledWith(expect.objectContaining({ left_device_only: true, before_id: null })));
  });
});

describe("Memory", () => {
  const mem = (o: Partial<Memory>): Memory => ({ id: "m1", project_id: null, kind: "fact", content: "Works at the Porto office", source: "user", pinned: false, use_count: 2, last_used_at: null, created_at: new Date().toISOString(), updated_at: new Date().toISOString(), status: "active", confirmed_at: new Date().toISOString(), review_after: null, superseded_by: null, conversation_id: null, ...o });

  it("asks about memories needing review, offers restore for outdated ones, and shows history", async () => {
    memories.mockResolvedValue([mem({ status: "needs_review" }), mem({ id: "m2", content: "Lives in Lisbon", status: "outdated" }), mem({ id: "m3", content: "Prefers tea", kind: "preference", source: "assistant" })]);
    render(<TooltipProvider><MemoryPage /></TooltipProvider>);
    await screen.findByText("Works at the Porto office");
    expect(document.querySelector('[data-memory="Works at the Porto office"]')?.getAttribute("data-memory-status")).toBe("needs_review");
    expect(screen.getByText(/Is it still true\?/)).toBeTruthy();
    expect(screen.getByText("Suggested by Atlas, approved by you")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Still true: Works at the Porto office" }));
    await waitFor(() => expect(confirmMemory).toHaveBeenCalledWith("m1"));
    fireEvent.click(screen.getByRole("button", { name: "Restore memory: Lives in Lisbon" }));
    await waitFor(() => expect(restoreMemory).toHaveBeenCalledWith("m2"));
    fireEvent.click(screen.getAllByRole("button", { name: "· history" })[0]!);
    expect(await screen.findByText(/was: “Old text”/)).toBeTruthy();
    // The filter shows only outdated or replaced memories.
    fireEvent.click(screen.getByRole("button", { name: "Outdated or replaced", pressed: false }));
    await waitFor(() => expect(document.querySelectorAll("[data-memory]").length).toBe(1));
  });

  it("warns before saving something Atlas already remembers", async () => {
    memories.mockResolvedValue([]);
    similar.mockResolvedValue([{ memory: mem({}), relation: "duplicate", overlap: 1 }]);
    render(<TooltipProvider><MemoryPage /></TooltipProvider>);
    fireEvent.click(await screen.findByRole("button", { name: "Add memory" }));
    fireEvent.change(screen.getByLabelText("What should Atlas remember?"), { target: { value: "works at the porto office" } });
    expect(await screen.findByText(/Atlas already remembers this/, {}, { timeout: 2000 })).toBeTruthy();
  });
});
