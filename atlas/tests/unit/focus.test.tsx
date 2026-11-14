import { TooltipProvider } from "@radix-ui/react-tooltip";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { FocusSession } from "@/lib/schemas";

const status = vi.fn();
const start = vi.fn();
const stop = vi.fn().mockResolvedValue(null);
vi.mock("@/lib/bridge", () => ({
  AtlasError: class AtlasError extends Error {},
  api: {
    focusStatus: () => status(),
    focusStart: (m: number, t: string | null, l: string) => start(m, t, l),
    focusStop: () => stop(),
    todos: () => Promise.resolve([{ id: "t1", parent_id: null, title: "Write the report" }]),
  },
}));
vi.mock("@/lib/events", () => ({ onChange: () => () => {} }));

const { FocusBar, FocusDialog, useFocusUi, useRemaining } = await import("@/features/focus/Focus");
const { renderHook } = await import("@testing-library/react");

const session = (o: Partial<FocusSession> = {}): FocusSession => ({
  id: "f1", started_at: new Date().toISOString(), planned_end: new Date(Date.now() + 25 * 60_000).toISOString(), ended_at: null, todo_id: null, todo_title: null, label: "", outcome: "", ...o,
});

describe("Focus Mode", () => {
  beforeEach(() => {
    status.mockReset();
    start.mockReset();
    stop.mockClear();
  });

  it("shows nothing when no session runs", async () => {
    status.mockResolvedValue({ active: null, history: [], min_minutes: 5, max_minutes: 240 });
    const { container } = render(<FocusBar />);
    await waitFor(() => expect(status).toHaveBeenCalled());
    expect(container.querySelector("[data-focus-bar]")).toBeNull();
  });

  it("shows what is being focused on, the time left, and stops", async () => {
    status.mockResolvedValue({ active: session({ todo_title: "Write the report" }), history: [], min_minutes: 5, max_minutes: 240 });
    render(<TooltipProvider><FocusBar /></TooltipProvider>);
    const bar = await screen.findByRole("status");
    expect(bar.textContent).toContain("Write the report");
    expect(bar.querySelector("[data-focus-left]")?.textContent).toMatch(/^2[45]:\d\d$/);
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    await waitFor(() => expect(stop).toHaveBeenCalled());
  });

  it("shows the right time left as soon as a session starts, however long ago the bar was mounted", () => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(new Date("2026-11-14T09:00:00Z"));
      const { result, rerender } = renderHook(({ end }: { end?: string }) => useRemaining(end), { initialProps: {} as { end?: string } });
      expect(result.current).toBe("");
      // Ten minutes later a 40-minute session starts: the first value shown is 40:00, not 50:00.
      vi.setSystemTime(new Date("2026-11-14T09:10:00Z"));
      rerender({ end: "2026-11-14T09:50:00.000Z" });
      expect(result.current).toBe("40:00");
    } finally {
      vi.useRealTimers();
    }
  });

  it("starts a session of the chosen length, on a task, and refuses lengths out of range", async () => {
    status.mockResolvedValue({ active: null, history: [], min_minutes: 5, max_minutes: 240 });
    start.mockResolvedValue(session({ todo_id: "t1", todo_title: "Write the report" }));
    render(<TooltipProvider><FocusDialog /></TooltipProvider>);
    useFocusUi.getState().start("t1");
    await screen.findByText("Start a focus session");
    fireEvent.click(screen.getByRole("button", { name: "50 min" }));
    const other = screen.getByLabelText("Other length in minutes");
    fireEvent.change(other, { target: { value: "3" } });
    expect(screen.getByText("Between 5 and 240 minutes.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Start focusing" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(other, { target: { value: "" } });
    await waitFor(() => expect((screen.getByLabelText("Task to focus on") as HTMLSelectElement).value).toBe("t1"));
    fireEvent.click(screen.getByRole("button", { name: "Start focusing" }));
    await waitFor(() => expect(start).toHaveBeenCalledWith(50, "t1", ""));
  });
});
