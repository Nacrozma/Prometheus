import { StatusPill, type Tone } from "@/components/ui/primitives";
import type { TaskStatus } from "@/lib/schemas";

export const taskTone: Record<TaskStatus, Tone> = {
  created: "neutral",
  planning: "info",
  awaiting_approval: "warn",
  ready: "info",
  running: "accent",
  verifying: "info",
  completed: "ok",
  failed: "err",
  cancelled: "neutral",
  interrupted: "warn",
  recoverable: "warn",
};

export const taskLabel: Record<TaskStatus, string> = {
  created: "Created",
  planning: "Planning",
  awaiting_approval: "Waiting for approval",
  ready: "Ready",
  running: "Running",
  verifying: "Verifying",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
  interrupted: "Interrupted",
  recoverable: "Recoverable",
};

export function TaskStatusPill({ status }: { status: TaskStatus }) {
  return <StatusPill tone={taskTone[status]} label={taskLabel[status]} pulse={status === "running" || status === "awaiting_approval"} />;
}

export function duration(start: string, end: string | null): string {
  const ms = (end ? Date.parse(end) : Date.now()) - Date.parse(start);
  if (!Number.isFinite(ms) || ms < 0) return "—";
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.floor(ms / 60_000)} min ${Math.round((ms % 60_000) / 1000)} s`;
}
