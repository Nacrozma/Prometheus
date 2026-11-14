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

/** mm:ss left until `end`, updated every second. */
function useRemaining(end: string | undefined): string {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!end) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [end]);
  if (!end) return "";
  const left = Math.max(0, Math.round((Date.parse(end) - now) / 1000));
  return `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
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
    <div role="status" aria-label={`Focus session: ${focusWhat(s)}, ${left} left`} data-focus-bar className="fixed left-1/2 top-3 z-40 flex -translate-x-1/2 items-center gap-3 rounded-full border border-accent/40 bg-bg-2/95 py-1.5 pl-4 pr-1.5 text-sm shadow-2 backdrop-blur">
      <Target className="size-4 text-accent" aria-hidden />
      <span className="max-w-64 truncate font-medium">{focusWhat(s)}</span>
      <span className="font-mono tabular-nums text-text-2" data-focus-left>
        {left}
      </span>
      <span className="hidden text-xs text-text-3 sm:inline">Notifications wait · approvals still come through</span>
      <Button size="sm" variant="ghost" onClick={stopFocus}>
        Stop
      </Button>
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
