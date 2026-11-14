import { Bell, CalendarClock, Check, ListTodo, Pencil, Plus, Repeat, Search, Target, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { Badge, Button, EmptyState, ErrorNote, Input, PageHeader, Panel, Segmented, Select, Skeleton, Switch } from "@/components/ui/primitives";
import { api, AtlasError } from "@/lib/bridge";
import { cn } from "@/lib/format";
import { useAtlasQuery } from "@/lib/query";
import type { QuickPreview, Todo, TodoDetail, TodoPatch, TodoView } from "@/lib/schemas";
import { useUi } from "@/state/ui";
import { useFocusUi } from "@/features/focus/Focus";
import { dueLabel, groupByDay, REPEAT_LABEL } from "./dates";

const VIEWS: { value: TodoView; label: string }[] = [
  { value: "today", label: "Today" },
  { value: "week", label: "This week" },
  { value: "upcoming", label: "Later" },
  { value: "someday", label: "No date" },
  { value: "open", label: "All open" },
  { value: "done", label: "Done" },
];
const PRIORITY_TONE = { urgent: "err", high: "warn", normal: "neutral", low: "neutral" } as const;
const fail = (e: unknown, fallback: string) => toast.error(e instanceof AtlasError ? e.message : fallback);

/** One task in a list: tick to complete, deadline and labels, quick actions. */
function TaskRow({ t, today, onOpen, onDelete }: { t: Todo; today: string; onOpen: () => void; onDelete: () => void }) {
  const done = t.status === "done";
  const due = dueLabel(t, today);
  const toggle = () => void api.todoSetStatus(t.id, done ? "open" : "done").catch((e) => fail(e, "The task could not be changed"));
  return (
    <li className="group flex items-start gap-3 rounded-md px-2 py-2 hover:bg-bg-3/60" data-task={t.title} data-status={t.status} data-overdue={String(t.overdue)}>
      <button
        role="checkbox"
        aria-checked={done}
        aria-label={done ? `Reopen ${t.title}` : `Complete ${t.title}`}
        onClick={toggle}
        className={cn("mt-0.5 grid size-5 shrink-0 place-items-center rounded-full border transition-colors", done ? "border-ok bg-ok text-text-inverse" : "border-line-2 hover:border-accent")}
      >
        {done && <Check className="size-3.5" strokeWidth={3} aria-hidden />}
      </button>
      <button onClick={onOpen} className="min-w-0 flex-1 text-left" data-open>
        <span className={cn("block text-sm", done ? "text-text-3 line-through" : "text-text-1")}>{t.title}</span>
        <span className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.6875rem] text-text-3">
          {due && (
            <span className={cn("flex items-center gap-1", t.overdue && "font-medium text-err")}>
              <CalendarClock className="size-3" aria-hidden />
              {due}
              {t.overdue && " · overdue"}
            </span>
          )}
          {t.recurrence !== "none" && (
            <span className="flex items-center gap-1">
              <Repeat className="size-3" aria-hidden />
              {REPEAT_LABEL[t.recurrence]}
            </span>
          )}
          {t.remind_at && !done && (
            <span className="flex items-center gap-1">
              <Bell className="size-3" aria-hidden />
              Reminder
            </span>
          )}
          {t.subtasks_total > 0 && (
            <span>
              {t.subtasks_done} of {t.subtasks_total} steps
            </span>
          )}
          {t.category && <span>#{t.category}</span>}
          {t.source === "atlas" && <span>added by Atlas</span>}
        </span>
      </button>
      {t.priority !== "normal" && !done && <Badge tone={PRIORITY_TONE[t.priority]}>{t.priority}</Badge>}
      <span className="flex shrink-0 items-center gap-1 opacity-0 transition-opacity focus-within:opacity-100 group-hover:opacity-100">
        {!done && (
          <Button size="sm" variant="ghost" onClick={() => void api.todoPostpone(t.id, 1).catch((e) => fail(e, "The task could not be moved"))} aria-label={`+1 day: ${t.title}`}>
            +1 day
          </Button>
        )}
        {!done && (
          <Button size="sm" variant="ghost" icon={<Target className="size-3.5" aria-hidden />} onClick={() => useFocusUi.getState().start(t.id)} aria-label={`Focus on ${t.title}`} />
        )}
        <Button size="sm" variant="ghost" icon={<Pencil className="size-3.5" aria-hidden />} onClick={onOpen} aria-label={`Edit ${t.title}`} />
        <Button size="sm" variant="ghost" icon={<Trash2 className="size-3.5" aria-hidden />} onClick={onDelete} aria-label={`Delete ${t.title}`} />
      </span>
    </li>
  );
}

/** Edit one task: details, deadline, repeat, reminder, steps and its history. */
function TaskDialog({ id, today, onClose }: { id: string; today: string; onClose: () => void }) {
  const detail = useAtlasQuery<TodoDetail>(`todo-${id}`, () => api.todoDetail(id), ["todos"]);
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");
  const [step, setStep] = useState("");
  const [timeOpen, setTimeOpen] = useState(false);
  const t = detail.data?.task;
  useEffect(() => {
    if (t) {
      setTitle(t.title);
      setNotes(t.notes);
    }
  }, [t?.id, t?.updated_at]); // eslint-disable-line react-hooks/exhaustive-deps
  const patch = (p: TodoPatch) => void api.todoUpdate(id, p).catch((e) => fail(e, "The change could not be saved"));
  const addStep = async () => {
    if (!step.trim()) return;
    try {
      await api.todoCreate({ title: step.trim(), parent_id: id });
      setStep("");
    } catch (e) {
      fail(e, "The step could not be added");
    }
  };
  // A reminder at the deadline's time, or 09:00 on the day when it has no time.
  const remindAt = (date: string, time: string | null) => new Date(`${date}T${time ?? "09:00"}:00`).toISOString();

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title="Task" width="max-w-xl" footer={<Button variant="primary" onClick={onClose}>Done</Button>}>
      {!t ? (
        detail.error ? <ErrorNote message={detail.error.message} /> : <Skeleton className="h-40" />
      ) : (
        <div className="flex flex-col gap-4 text-sm" data-task-dialog>
          <label className="flex flex-col gap-1 text-xs text-text-2">
            Title
            <Input value={title} onChange={(e) => setTitle(e.target.value)} onBlur={() => title.trim() && title !== t.title && patch({ title })} aria-label="Task title" />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="flex flex-col gap-1 text-xs text-text-2">
              Due date
              <Input type="date" aria-label="Due date" value={t.due_date ?? ""} onChange={(e) => patch({ due_date: e.target.value || null })} />
            </label>
            {/* An empty time box shows a made-up placeholder time in some web views, so it only appears once asked for. */}
            {t.due_time || timeOpen ? (
              <label className="flex flex-col gap-1 text-xs text-text-2">
                Time (optional)
                <span className="flex items-center gap-2">
                  <Input type="time" aria-label="Due time" value={t.due_time ?? ""} disabled={!t.due_date} onChange={(e) => patch({ due_time: e.target.value || null })} className="flex-1" />
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      setTimeOpen(false);
                      if (t.due_time) patch({ due_time: null });
                    }}
                  >
                    No time
                  </Button>
                </span>
              </label>
            ) : (
              <div className="flex flex-col gap-1 text-xs text-text-2">
                Time (optional)
                <Button size="sm" disabled={!t.due_date} onClick={() => setTimeOpen(true)} data-add-time>
                  {t.due_date ? "Add a time" : "Needs a due date"}
                </Button>
              </div>
            )}
            <label className="flex flex-col gap-1 text-xs text-text-2">
              Priority
              <Select aria-label="Priority" value={t.priority} onChange={(e) => patch({ priority: e.target.value as Todo["priority"] })}>
                {(["low", "normal", "high", "urgent"] as const).map((p) => (
                  <option key={p} value={p}>
                    {p[0]?.toUpperCase() + p.slice(1)}
                  </option>
                ))}
              </Select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-text-2">
              Repeats
              <Select aria-label="Repeats" value={t.recurrence} disabled={!t.due_date || Boolean(t.parent_id)} onChange={(e) => patch({ recurrence: e.target.value as Todo["recurrence"] })}>
                {(Object.keys(REPEAT_LABEL) as Todo["recurrence"][]).map((r) => (
                  <option key={r} value={r}>
                    {REPEAT_LABEL[r]}
                  </option>
                ))}
              </Select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-text-2">
              Category
              <Input aria-label="Category" defaultValue={t.category} key={t.category} placeholder="e.g. work" onBlur={(e) => e.target.value.trim() !== t.category && patch({ category: e.target.value.trim() })} />
            </label>
            <div className="flex items-end justify-between gap-3 pb-1 text-xs text-text-2">
              <span>
                Remind me
                <span className="block text-[0.6875rem] text-text-3">{t.due_date ? (t.due_time ? "At the due time" : "At 09:00 on the day") : "Needs a due date"}</span>
              </span>
              <Switch checked={Boolean(t.remind_at)} label="Remind me" disabled={!t.due_date} onChange={(on) => patch({ remind_at: on && t.due_date ? remindAt(t.due_date, t.due_time) : null })} />
            </div>
          </div>
          <label className="flex flex-col gap-1 text-xs text-text-2">
            Notes
            <textarea
              aria-label="Notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              onBlur={() => notes !== t.notes && patch({ notes })}
              rows={3}
              className="rounded-md border border-line-2 bg-bg-1 px-3 py-2 text-sm text-text-1 outline-none focus-visible:border-accent"
            />
          </label>
          {!t.parent_id && (
            <div className="flex flex-col gap-2">
              <p className="text-xs font-medium text-text-1">Steps</p>
              {detail.data && detail.data.subtasks.length > 0 && (
                <ul className="flex flex-col">
                  {detail.data.subtasks.map((s) => (
                    <TaskRow key={s.id} t={s} today={today} onOpen={() => {}} onDelete={() => void api.todoDelete(s.id).catch((e) => fail(e, "The step could not be deleted"))} />
                  ))}
                </ul>
              )}
              <form
                className="flex items-center gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  void addStep();
                }}
              >
                <Input aria-label="New step" placeholder="Add a step" value={step} onChange={(e) => setStep(e.target.value)} />
                <Button type="submit" size="sm" icon={<Plus className="size-3.5" aria-hidden />} disabled={!step.trim()}>
                  Add
                </Button>
              </form>
            </div>
          )}
          {detail.data && (
            <details className="text-xs text-text-3">
              <summary className="cursor-pointer text-text-2">History ({detail.data.history.length})</summary>
              <ul className="mt-2 flex flex-col gap-1" data-task-history>
                {detail.data.history.map((h, i) => (
                  <li key={i}>
                    {new Date(h.at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })} · {h.kind}
                    {h.detail ? ` · ${h.detail}` : ""}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </Dialog>
  );
}

/** The owner's task list: plain-language entry, day and week views, search. */
export function TasksPage() {
  const [view, setView] = useState<TodoView>("today");
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [line, setLine] = useState("");
  const [preview, setPreview] = useState<QuickPreview | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  // Opened from a reminder or the bell: show that task.
  const focus = useUi((u) => u.focusTodoId);
  useEffect(() => {
    if (focus) {
      setOpenId(focus);
      useUi.setState({ focusTodoId: null });
    }
  }, [focus]);
  const [deleting, setDeleting] = useState<Todo | null>(null);
  const entry = useRef<HTMLInputElement>(null);

  const overview = useAtlasQuery("todo-overview", api.todoOverview, ["todos"]);
  // A search looks across everything unfinished, whatever the view.
  const effectiveView: TodoView = search.trim() && view !== "done" ? "open" : view;
  const list = useAtlasQuery(`todos-${effectiveView}-${search}-${category}`, () => api.todos({ view: effectiveView, search: search.trim() || null, category: category || null }), ["todos"]);
  const today = overview.data?.today ?? new Date().toISOString().slice(0, 10);
  const c = overview.data?.counts;

  // Show how the line will be understood before it is saved.
  useEffect(() => {
    if (!line.trim()) return setPreview(null);
    const timer = setTimeout(() => void api.todoQuickPreview(line).then(setPreview).catch(() => setPreview(null)), 150);
    return () => clearTimeout(timer);
  }, [line]);

  const add = async () => {
    if (!line.trim()) return;
    try {
      const t = await api.todoQuickAdd(line);
      setLine("");
      setPreview(null);
      // Make sure the new task is visible: jump to a view that contains it.
      if (!t.due_date && view !== "open" && view !== "someday") setView("open");
      else if (t.due_date && t.due_date > today && view === "today") setView("week");
      entry.current?.focus();
    } catch (e) {
      fail(e, "The task could not be added");
    }
  };

  const groups = useMemo(() => (list.data && effectiveView !== "done" ? groupByDay(list.data, today) : []), [list.data, effectiveView, today]);
  const empty: Record<TodoView, [string, string]> = {
    today: ["Nothing due today", "Add a task above, or look at the week."],
    week: ["A clear week", "Nothing is due in the next seven days."],
    upcoming: ["Nothing scheduled later", "Tasks due after today appear here."],
    someday: ["No undated tasks", "Tasks without a deadline appear here."],
    open: ["No open tasks", "Add one above. Try “Call the dentist friday 9am !high”."],
    done: ["Nothing completed yet", "Finished tasks are kept here."],
    overdue: ["Nothing overdue", ""],
    all: ["No tasks", ""],
  };

  return (
    <div className="flex h-full flex-col" data-tasks-page>
      <PageHeader
        title="Tasks"
        subtitle={
          c ? (
            <span data-task-counts>
              {c.open} open
              {c.overdue > 0 && <span className="text-err"> · {c.overdue} overdue</span>} · {c.today} for today · {c.done_week} done in the last 7 days
            </span>
          ) : (
            "Your to-dos, deadlines and reminders."
          )
        }
      />
      <div className="min-h-0 flex-1 overflow-y-auto px-8 py-6">
        <div className="mx-auto flex max-w-3xl flex-col gap-5">
          <Panel className="p-4">
            <form
              className="flex items-center gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                void add();
              }}
            >
              <Input ref={entry} aria-label="New task" placeholder="Add a task: “Send the invoice tomorrow 5pm”, “Gym every monday”, “Renew passport !high #admin”" value={line} onChange={(e) => setLine(e.target.value)} className="flex-1" />
              <Button type="submit" variant="primary" icon={<Plus className="size-4" aria-hidden />} disabled={!line.trim()}>
                Add
              </Button>
            </form>
            {preview && line.trim() && (
              <p className="mt-2 flex flex-wrap items-center gap-2 text-xs text-text-3" data-quick-preview aria-live="polite">
                {preview.title ? <span className="text-text-1">{preview.title}</span> : <span className="text-warn">Needs a title besides the date</span>}
                {preview.due_date && <Badge tone="accent">{dueLabel(preview, today)}</Badge>}
                {preview.recurrence && <Badge tone="neutral">{REPEAT_LABEL[preview.recurrence as Todo["recurrence"]] ?? preview.recurrence}</Badge>}
                {preview.priority && preview.priority !== "normal" && <Badge tone={PRIORITY_TONE[preview.priority as Todo["priority"]]}>{preview.priority}</Badge>}
                {preview.category && <Badge tone="neutral">#{preview.category}</Badge>}
                {(preview.remind || preview.due_time) && preview.due_date && <Badge tone="neutral">reminder</Badge>}
              </p>
            )}
          </Panel>

          <div className="flex flex-wrap items-center gap-3">
            <Segmented label="View" value={view} onChange={setView} options={VIEWS} />
            <label className="relative ml-auto">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-text-3" aria-hidden />
              <Input aria-label="Search tasks" placeholder="Search" value={search} onChange={(e) => setSearch(e.target.value)} className="w-44 pl-8" />
            </label>
            {overview.data && overview.data.categories.length > 0 && (
              <Select aria-label="Category filter" value={category} onChange={(e) => setCategory(e.target.value)} className="w-36">
                <option value="">All categories</option>
                {overview.data.categories.map((x) => (
                  <option key={x} value={x}>
                    #{x}
                  </option>
                ))}
              </Select>
            )}
          </div>

          {list.error ? (
            <ErrorNote message={list.error.message} onRetry={list.reload} />
          ) : !list.data ? (
            <Skeleton className="h-32" />
          ) : list.data.length === 0 ? (
            <EmptyState icon={<ListTodo className="size-6" aria-hidden />} title={search.trim() ? "No tasks match" : empty[view][0]} body={search.trim() ? "Try a different word." : empty[view][1]} />
          ) : effectiveView === "done" ? (
            <Panel className="px-3 py-2">
              <ul>
                {list.data.map((t) => (
                  <TaskRow key={t.id} t={t} today={today} onOpen={() => setOpenId(t.id)} onDelete={() => setDeleting(t)} />
                ))}
              </ul>
            </Panel>
          ) : (
            groups.map((g) => (
              <section key={g.key} aria-label={g.label} data-task-group={g.label}>
                <h2 className={cn("mb-1 px-2 text-[0.6875rem] font-semibold uppercase tracking-[0.12em]", g.tone === "err" ? "text-err" : g.tone === "accent" ? "text-accent" : "text-text-3")}>
                  {g.label} · {g.items.length}
                </h2>
                <Panel className="px-3 py-2">
                  <ul>
                    {g.items.map((t) => (
                      <TaskRow key={t.id} t={t} today={today} onOpen={() => setOpenId(t.id)} onDelete={() => setDeleting(t)} />
                    ))}
                  </ul>
                </Panel>
              </section>
            ))
          )}
        </div>
      </div>

      {openId && <TaskDialog id={openId} today={today} onClose={() => setOpenId(null)} />}
      <ConfirmDialog
        open={deleting != null}
        onOpenChange={(o) => !o && setDeleting(null)}
        title="Delete this task?"
        body={
          <>
            “{deleting?.title}” will be removed{deleting && deleting.subtasks_total > 0 ? `, with its ${deleting.subtasks_total} step${deleting.subtasks_total === 1 ? "" : "s"}` : ""}. This cannot be undone. To keep a record, complete it instead.
          </>
        }
        confirmLabel="Delete"
        danger
        onConfirm={async () => {
          if (!deleting) return;
          try {
            await api.todoDelete(deleting.id);
          } catch (e) {
            fail(e, "The task could not be deleted");
          }
          setDeleting(null);
        }}
      />
    </div>
  );
}
