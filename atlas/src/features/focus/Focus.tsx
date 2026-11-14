import { Target } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { create } from "zustand";
import { Dialog } from "@/components/ui/dialog";
import { Button, Input, Select } from "@/components/ui/primitives";
import { api, AtlasError } from "@/lib/bridge";
import { useAtlasQuery } from "@/lib/query";
import type { FocusSession } from "@/lib/schemas";

const DURATIONS = [15, 25, 50, 90];

/** Opens the start dialog from anywhere (Home, a task, the command palette). */
export const useFocusUi = create<{ open: boolean; todoId: string | null; start: (todoId?: string | null) => void; close: () => void }>((set) => ({
  open: false,
  todoId: null,
  start: (todoId = null) => set({ open: true, todoId }),
  close: () => set({ open: false }),
}));

export function useFocus() {
  return useAtlasQuery("focus", api.focusStatus, ["focus", "todos"]);
}

/** mm:ss from `now` until `end`. */
export function formatRemaining(end: string, now: number): string {
  const left = Math.max(0, Math.round((Date.parse(end) - now) / 1000));
  return `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
}

/**
 * mm:ss left until `end`, updated every second. The clock is read when the session changes, not
 * kept from when the bar was first mounted (which showed too much time left for the first second).
 */
export function useRemaining(end: string | undefined): string {
  const [clock, setClock] = useState<{ end: string | undefined; now: number }>(() => ({ end, now: Date.now() }));
  useEffect(() => {
    if (!end) return;
    setClock({ end, now: Date.now() });
    const t = setInterval(() => setClock({ end, now: Date.now() }), 1000);
    return () => clearInterval(t);
  }, [end]);
  if (!end) return "";
  // Until the effect above has run for this session, read the clock now rather than show a stale value.
  const now = clock.end === end ? clock.now : Date.now();
  return formatRemaining(end, now);
}

export const focusWhat = (s: FocusSession) => s.todo_title || s.label || "Focus";

const errText = (e: unknown, fallback: string) => (e instanceof AtlasError ? e.message : fallback);

export function stopFocus() {
  void api
    .focusStop()
    .then((s) => s && toast.success("Focus session stopped", { description: "Notifications that waited are in the bell." }))
    .catch((e) => toast.error(errText(e, "The session could not be stopped")));
}

/** A slim bar at the top of the window while a session runs: what, time left, Stop. */
export function FocusBar() {
  const focus = useFocus();
  const s = focus.data?.active ?? null;
  const left = useRemaining(s?.planned_end);
  if (!s) return null;
  return (
    // Centred in a full-width strip, so the bar can use the whole window width (positioned at
    // left: 50% it had only half, and the task title was squeezed to nothing).
    <div className="pointer-events-none fixed inset-x-0 top-3 z-40 flex justify-center px-4">
      <div role="status" aria-label={`Focus session: ${focusWhat(s)}, ${left} left`} data-focus-bar className="pointer-events-auto flex max-w-full items-center gap-3 rounded-full border border-accent/40 bg-bg-2/95 py-1.5 pl-4 pr-1.5 text-sm shadow-2 backdrop-blur">
        <Target className="size-4 shrink-0 text-accent" aria-hidden />
        <span className="max-w-64 shrink-0 truncate font-medium" data-focus-what>
          {focusWhat(s)}
        </span>
        <span className="shrink-0 font-mono tabular-nums text-text-2" data-focus-left>
          {left}
        </span>
        <span className="hidden min-w-0 truncate text-xs text-text-3 md:inline">Notifications wait · approvals still come through</span>
        <Button size="sm" variant="ghost" onClick={stopFocus}>
          Stop
        </Button>
      </div>
    </div>
  );
}

/** Start a session: how long, optionally on one open task, and an optional label. */
export function FocusDialog() {
  const ui = useFocusUi();
  const focus = useFocus();
  const todos = useAtlasQuery("focus-todos", () => api.todos({ view: "open" }), ["todos"]);
  const [minutes, setMinutes] = useState(25);
  const [custom, setCustom] = useState("");
  const [todoId, setTodoId] = useState<string>("");
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const min = focus.data?.min_minutes ?? 5;
  const max = focus.data?.max_minutes ?? 240;

  useEffect(() => {
    if (ui.open) {
      setTodoId(ui.todoId ?? "");
      setCustom("");
      setLabel("");
    }
  }, [ui.open, ui.todoId]);

  const chosen = custom ? Number(custom) : minutes;
  const valid = Number.isInteger(chosen) && chosen >= min && chosen <= max;
  const begin = async () => {
    setBusy(true);
    try {
      const s = await api.focusStart(chosen, todoId || null, label);
      toast.success(`Focusing for ${chosen} minutes`, { description: focusWhat(s) === "Focus" ? undefined : focusWhat(s) });
      ui.close();
    } catch (e) {
      toast.error(errText(e, "The session could not start"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={ui.open}
      onOpenChange={(o) => !o && ui.close()}
      title="Start a focus session"
      description="Reminders, replies and mission updates wait until the session ends, then you see them all at once. Approvals and failures always come through."
      footer={
        <>
          <Button variant="ghost" onClick={ui.close}>
            Cancel
          </Button>
          <Button variant="primary" onClick={() => void begin()} disabled={!valid || busy} loading={busy}>
            Start focusing
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4 text-sm" data-focus-dialog>
        <div>
          <p className="mb-2 text-xs text-text-3">How long</p>
          <div className="flex flex-wrap gap-2">
            {DURATIONS.map((m) => (
              <Button key={m} size="sm" variant={!custom && minutes === m ? "primary" : "secondary"} aria-pressed={!custom && minutes === m} onClick={() => (setMinutes(m), setCustom(""))}>
                {m} min
              </Button>
            ))}
            <Input type="number" inputMode="numeric" min={min} max={max} placeholder="Other" aria-label="Other length in minutes" value={custom} onChange={(e) => setCustom(e.target.value)} className="w-24" />
          </div>
          {custom && !valid && <p className="mt-1 text-xs text-err">Between {min} and {max} minutes.</p>}
        </div>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-text-3">On a task (optional)</span>
          <Select aria-label="Task to focus on" value={todoId} onChange={(e) => setTodoId(e.target.value)}>
            <option value="">No particular task</option>
            {(todos.data ?? [])
              .filter((t) => !t.parent_id)
              .map((t) => (
                <option key={t.id} value={t.id}>
                  {t.title}
                </option>
              ))}
          </Select>
        </label>
        {!todoId && (
          <label className="flex flex-col gap-1">
            <span className="text-xs text-text-3">What you're working on (optional)</span>
            <Input aria-label="Focus label" maxLength={120} value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. Write the quarterly report" />
          </label>
        )}
      </div>
    </Dialog>
  );
}
