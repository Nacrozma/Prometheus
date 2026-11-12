import { TooltipProvider } from "@radix-ui/react-tooltip";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Todo } from "@/lib/schemas";

const todos = vi.fn();
const quickAdd = vi.fn();
const quickPreview = vi.fn();
const setStatus = vi.fn().mockResolvedValue({});
const postpone = vi.fn().mockResolvedValue({});
const del = vi.fn().mockResolvedValue(1);
vi.mock("@/lib/bridge", () => ({
  AtlasError: class AtlasError extends Error {},
  api: {
    todos: (f: unknown) => todos(f),
    todoOverview: () => Promise.resolve({ counts: { open: 3, overdue: 1, today: 2, week: 3, done_today: 0, done_week: 4 }, categories: ["health"], today: "2026-11-12" }),
    todoQuickAdd: (l: string) => quickAdd(l),
    todoQuickPreview: (l: string) => quickPreview(l),
    todoSetStatus: (id: string, s: string) => setStatus(id, s),
    todoPostpone: (id: string, d: number) => postpone(id, d),
    todoDelete: (id: string) => del(id),
  },
}));
vi.mock("@/lib/events", () => ({ onChange: () => () => {} }));

const { addDays, dayLabel, daysFrom, dueLabel, groupByDay } = await import("@/features/tasks/dates");
const { TasksPage } = await import("@/features/tasks/Tasks");

const task = (o: Partial<Todo>): Todo => ({
  id: o.title ?? "t", parent_id: null, project_id: null, title: "Task", notes: "", status: "open", priority: "normal", category: "", due_date: null, due_time: null, remind_at: null,
  recurrence: "none", recur_interval: 1, source: "user", conversation_id: null, postponed_count: 0, created_at: "", updated_at: "", completed_at: null, overdue: false, subtasks_total: 0, subtasks_done: 0, ...o,
});

describe("task dates", () => {
  const today = "2026-11-12"; // a Thursday
  it("names days the way people do", () => {
    expect(daysFrom(today, "2026-11-19")).toBe(7);
    expect(addDays("2026-12-31", 1)).toBe("2027-01-01");
    expect(dayLabel(today, today)).toBe("Today");
    expect(dayLabel("2026-11-13", today)).toBe("Tomorrow");
    expect(dayLabel("2026-11-11", today)).toBe("Yesterday");
    expect(dayLabel("2026-11-16", today)).toBe("Monday");
    expect(dayLabel("2026-11-20", today)).toBe("Fri 20 Nov");
    expect(dayLabel("2027-01-04", today)).toBe("Mon 4 Jan 2027");
    expect(dueLabel({ due_date: "2026-11-13", due_time: "17:00" }, today)).toBe("Tomorrow 17:00");
    expect(dueLabel({ due_date: null, due_time: null }, today)).toBeNull();
  });

  it("groups a list into Overdue, each day, then No date", () => {
    const g = groupByDay(
      [task({ title: "c", due_date: "2026-11-14" }), task({ title: "none" }), task({ title: "late", due_date: "2026-11-01" }), task({ title: "a", due_date: today }), task({ title: "late2", due_date: "2026-11-10" })],
      today,
    );
    expect(g.map((x) => [x.label, x.items.length, x.tone])).toEqual([["Overdue", 2, "err"], ["Today", 1, "accent"], ["Saturday", 1, "neutral"], ["No date", 1, "neutral"]]);
  });
});

describe("Tasks page", () => {
  beforeEach(() => {
    todos.mockReset();
    quickAdd.mockReset();
    quickPreview.mockReset();
    setStatus.mockClear();
    postpone.mockClear();
    del.mockClear();
  });
  const show = () => render(<TooltipProvider><TasksPage /></TooltipProvider>);

  it("lists tasks by day, marks overdue ones, and completes, postpones and deletes with confirmation", async () => {
    todos.mockResolvedValue([
      task({ title: "Pay rent", due_date: "2026-11-10", overdue: true, priority: "urgent" }),
      task({ title: "Call the dentist", due_date: "2026-11-12", due_time: "17:00", remind_at: "x", category: "health", subtasks_total: 2, subtasks_done: 1 }),
    ]);
    show();
    expect(await screen.findByText("Pay rent")).toBeTruthy();
    expect(screen.getByRole("region", { name: "Overdue" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Today" })).toBeTruthy();
    expect(screen.getByText(/1 overdue/)).toBeTruthy();
    expect(screen.getByText("1 of 2 steps")).toBeTruthy();
    expect(screen.getByText("urgent")).toBeTruthy();

    fireEvent.click(screen.getByRole("checkbox", { name: "Complete Call the dentist" }));
    expect(setStatus).toHaveBeenCalledWith("Call the dentist", "done");
    fireEvent.click(screen.getByRole("button", { name: "Move Pay rent to the next day" }));
    expect(postpone).toHaveBeenCalledWith("Pay rent", 1);

    // Deleting asks first, and Cancel deletes nothing.
    fireEvent.click(screen.getByRole("button", { name: "Delete Pay rent" }));
    expect(await screen.findByRole("heading", { name: "Delete this task?" })).toBeTruthy();
    expect(del).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(del).toHaveBeenCalledWith("Pay rent"));
  });

  it("shows how a line will be understood, adds it, and says when a title is missing", async () => {
    todos.mockResolvedValue([]);
    quickPreview.mockResolvedValue({ title: "Send the invoice", due_date: "2026-11-13", due_time: "17:00", priority: "high", category: "work", recurrence: null, remind: false });
    quickAdd.mockResolvedValue(task({ title: "Send the invoice", due_date: "2026-11-13" }));
    show();
    expect(await screen.findByText("Nothing due today")).toBeTruthy();
    const box = screen.getByRole("textbox", { name: "New task" });
    fireEvent.change(box, { target: { value: "Send the invoice tomorrow 5pm !high #work" } });
    expect(await screen.findByText("Tomorrow 17:00")).toBeTruthy();
    expect(screen.getByText("#work")).toBeTruthy();
    expect(screen.getByText("reminder")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(quickAdd).toHaveBeenCalledWith("Send the invoice tomorrow 5pm !high #work"));
    await waitFor(() => expect((box as HTMLInputElement).value).toBe(""));
    // The new task is due tomorrow, so the view moves to the week to keep it visible.
    await waitFor(() => expect(todos).toHaveBeenLastCalledWith(expect.objectContaining({ view: "week" })));

    quickPreview.mockResolvedValue({ title: "", due_date: "2026-11-13", due_time: null, priority: null, category: null, recurrence: null, remind: false });
    fireEvent.change(box, { target: { value: "tomorrow" } });
    expect(await screen.findByText("Needs a title besides the date")).toBeTruthy();
  });

  it("searches across all open tasks and explains an empty result", async () => {
    todos.mockResolvedValue([]);
    show();
    await screen.findByText("Nothing due today");
    fireEvent.change(screen.getByRole("textbox", { name: "Search tasks" }), { target: { value: "passport" } });
    await waitFor(() => expect(todos).toHaveBeenLastCalledWith({ view: "open", search: "passport", category: null }));
    expect(await screen.findByText("No tasks match")).toBeTruthy();
  });
});
