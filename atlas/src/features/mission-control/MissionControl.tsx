import { ChevronRight, MessageSquareText, Octagon, RotateCcw, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { emergencyStop } from "@/app/Rail";
import { ApprovalCard } from "@/components/ApprovalCard";
import { Badge, Button, EmptyState, ErrorNote, PageHeader, Panel, Segmented, Skeleton, StatusPill } from "@/components/ui/primitives";
import { api, AtlasError } from "@/lib/bridge";
import { cn, permissionLabel, relativeTime } from "@/lib/format";
import { useAtlasQuery } from "@/lib/query";
import type { Step, TaskDetail } from "@/lib/schemas";
import { useUi } from "@/state/ui";
import { duration, TaskStatusPill } from "../shared";

type Filter = "all" | "active" | "awaiting_approval" | "completed" | "failed" | "cancelled" | "interrupted";
const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "active", label: "Running" },
  { value: "awaiting_approval", label: "Waiting" },
  { value: "completed", label: "Completed" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
  { value: "interrupted", label: "Interrupted" },
];

const stepTone = (s: string) =>
  s === "succeeded" ? "ok" : s === "running" || s === "pending" ? "accent" : s === "awaiting_approval" ? "warn" : s === "rejected" || s === "cancelled" ? "neutral" : "err";

function StepItem({ step, onRetry }: { step: Step; onRetry?: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="relative pl-7">
      <span aria-hidden className="absolute left-2 top-0 h-full w-px bg-line-2" />
      <span aria-hidden className={cn("absolute left-[3px] top-3 size-2.5 rounded-full border-2 border-bg-2", step.status === "succeeded" ? "bg-ok" : step.status === "failed" || step.status === "denied" ? "bg-err" : step.status === "awaiting_approval" ? "bg-warn" : "bg-text-3")} />
      <div className="rounded-md border border-line-1 bg-bg-1/60">
        <button onClick={() => setOpen((v) => !v)} aria-expanded={open} className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-left text-sm">
          <ChevronRight className={cn("size-3.5 text-text-3 transition-transform", open && "rotate-90")} aria-hidden />
          <span className="font-mono text-text-1">{step.tool_id}</span>
          <Badge>{permissionLabel[step.permission] ?? step.permission}</Badge>
          <StatusPill tone={stepTone(step.status)} label={step.status.replace(/_/g, " ")} />
          <span className="ml-auto text-xs text-text-3">{step.duration_ms != null ? `${step.duration_ms} ms` : duration(step.started_at, step.finished_at)}</span>
        </button>
        {open && (
          <div className="space-y-2 border-t border-line-1 px-3 py-2.5 text-xs">
            <div>
              <p className="mb-1 text-text-3">Arguments (secrets redacted)</p>
              <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-sm bg-[color:var(--code-bg)] p-2 font-mono text-text-2">{JSON.stringify(step.input, null, 2)}</pre>
            </div>
            {step.output != null && (
              <div>
                <p className="mb-1 text-text-3">Output</p>
                <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-sm bg-[color:var(--code-bg)] p-2 font-mono text-text-2">{JSON.stringify(step.output, null, 2)}</pre>
              </div>
            )}
            {step.error && <p className="rounded-sm bg-err-soft px-2 py-1.5 text-err">{step.error}</p>}
            {step.approval_id && <p className="text-text-3">Approval: <span className="font-mono">{step.approval_id}</span></p>}
            {onRetry && (
              <Button size="sm" icon={<RotateCcw className="size-3.5" aria-hidden />} onClick={onRetry}>
                Retry this read-only step
              </Button>
            )}
          </div>
        )}
      </div>
    </li>
  );
}

function Detail({ id }: { id: string }) {
  const d = useAtlasQuery<TaskDetail>(`task:${id}`, () => api.taskDetail(id), ["tasks", "approvals"]);
  const tools = useAtlasQuery("tools", api.tools, ["registry"]);
  const openConversation = useUi((s) => s.openConversation);
  if (d.error) return <ErrorNote message={d.error.message} onRetry={d.reload} />;
  if (!d.data) return <Skeleton className="h-64" />;
  const { task, steps, approvals } = d.data;
  const v = task.verification as Record<string, unknown> | null;
  const active = ["created", "planning", "awaiting_approval", "ready", "running", "verifying"].includes(task.status);
  const retryable = (s: Step) => {
    const t = tools.data?.find((x) => x.id === s.tool_id);
    return !active && (s.status === "failed" || s.status === "cancelled") && t?.permission === "read_only" && !t.network;
  };
  const run = async (fn: () => Promise<unknown>, ok: string) => {
    try {
      await fn();
      toast.success(ok);
    } catch (e) {
      toast.error(e instanceof AtlasError ? e.message : String(e));
    }
  };
  return (
    <div className="space-y-5 anim-fade">
      <div>
        <div className="flex flex-wrap items-center gap-3">
          <TaskStatusPill status={task.status} />
          <span className="text-xs text-text-3">Started {relativeTime(task.created_at)} · {duration(task.created_at, task.finished_at)}</span>
        </div>
        <h2 className="mt-2 font-display text-lg font-semibold">{task.request}</h2>
        <div className="mt-3 flex flex-wrap gap-2">
          {task.conversation_id && (
            <Button size="sm" icon={<MessageSquareText className="size-3.5" aria-hidden />} onClick={() => openConversation(task.conversation_id)}>
              Open conversation
            </Button>
          )}
          {active && <Button size="sm" variant="danger" icon={<XCircle className="size-3.5" aria-hidden />} onClick={() => run(() => api.cancelTask(task.id), "Cancellation requested")}>Cancel task</Button>}
          {task.status === "interrupted" && <Button size="sm" onClick={() => run(() => api.dismissTask(task.id), "Dismissed")}>Dismiss</Button>}
        </div>
      </div>
      {task.status === "interrupted" && (
        <p className="rounded-md border border-[color:var(--warn)]/30 bg-warn-soft px-3 py-2 text-sm">
          Atlas was closed while this task was running. Nothing is resumed automatically — review the steps below, then ask Atlas again if needed.
        </p>
      )}
      {approvals.filter((a) => a.status === "pending").map((a) => <ApprovalCard key={a.id} approval={a} compact />)}
      {task.error && <ErrorNote title="Task error" message={task.error} />}
      {v && (
        <Panel className="grid grid-cols-2 gap-3 p-4 text-sm sm:grid-cols-4">
          {[
            ["Steps", v.steps],
            ["Succeeded", v.succeeded],
            ["Declined by you", v.rejected_by_user],
            ["Failed / denied", v.failed_or_denied],
          ].map(([k, val]) => (
            <div key={String(k)}>
              <p className="text-xs text-text-3">{String(k)}</p>
              <p className="font-display text-lg font-semibold">{String(val ?? "—")}</p>
            </div>
          ))}
          {v.partial === true && <p className="col-span-full text-xs text-warn">Partial success: some steps did not complete.</p>}
        </Panel>
      )}
      {task.summary && (
        <div>
          <p className="mb-1 text-xs text-text-3">Final response (excerpt)</p>
          <p className="whitespace-pre-wrap rounded-md border border-line-1 bg-bg-1/60 p-3 text-sm text-text-2">{task.summary}</p>
        </div>
      )}
      <div>
        <h3 className="mb-2 text-sm font-semibold">Execution timeline</h3>
        {steps.length ? (
          <ol className="space-y-2">
            {steps.map((s) => (
              <StepItem key={s.id} step={s} onRetry={retryable(s) ? () => run(() => api.retryStep(s.id), "Step re-run") : undefined} />
            ))}
          </ol>
        ) : (
          <p className="text-sm text-text-3">No tool steps recorded.</p>
        )}
      </div>
    </div>
  );
}

export function MissionControlPage() {
  const [filter, setFilter] = useState<Filter>("all");
  const focus = useUi((s) => s.focusTaskId);
  const [selected, setSelected] = useState<string | null>(focus);
  const tasks = useAtlasQuery(`tasks:${filter}`, () => api.tasks(filter === "all" || filter === "active" ? null : filter, 300), ["tasks"]);
  const list = (tasks.data ?? []).filter((t) => (filter === "active" ? ["created", "planning", "ready", "running", "verifying", "awaiting_approval"].includes(t.status) : true));
  useEffect(() => {
    if (focus) setSelected(focus);
  }, [focus]);
  useEffect(() => {
    if (!selected && list[0]) setSelected(list[0].id);
  }, [list, selected]);

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        eyebrow="Execution"
        title="Mission Control"
        subtitle="Every task Atlas has run with tools: what it planned, what it asked, what actually happened."
        actions={<Button variant="danger" icon={<Octagon className="size-4" aria-hidden />} onClick={emergencyStop}>Emergency stop</Button>}
      />
      <div className="flex min-h-0 flex-1">
        <aside className="flex w-[22rem] shrink-0 flex-col border-r border-line-1">
          <div className="overflow-x-auto border-b border-line-1 p-3">
            <Segmented label="Filter tasks" value={filter} onChange={setFilter} options={FILTERS} />
          </div>
          <div className="flex-1 overflow-y-auto p-2">
            {tasks.loading && !tasks.data ? (
              <div className="space-y-2 p-1">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-14" />)}</div>
            ) : list.length === 0 ? (
              <p className="px-3 py-10 text-center text-sm text-text-3">No tasks here.</p>
            ) : (
              <ul className="space-y-0.5">
                {list.map((t) => (
                  <li key={t.id}>
                    <button
                      onClick={() => setSelected(t.id)}
                      aria-current={selected === t.id ? "true" : undefined}
                      className={cn("flex w-full flex-col gap-1 rounded-md px-3 py-2.5 text-left", selected === t.id ? "bg-bg-4" : "hover:bg-bg-3")}
                    >
                      <span className="line-clamp-2 text-sm text-text-1">{t.request}</span>
                      <span className="flex items-center gap-2 text-xs text-text-3">
                        <TaskStatusPill status={t.status} />
                        <span className="ml-auto">{t.step_count} steps · {relativeTime(t.created_at)}</span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </aside>
        <section className="min-w-0 flex-1 overflow-y-auto px-8 py-6" aria-label="Task details">
          {selected ? <Detail key={selected} id={selected} /> : <EmptyState title="No task selected" body="Tasks appear when Atlas uses tools during a conversation." />}
        </section>
      </div>
    </div>
  );
}
