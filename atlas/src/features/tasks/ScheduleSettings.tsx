import { PauseCircle } from "lucide-react";
import type { ReactNode } from "react";
import { Badge, Button, EmptyState, Input, Panel, Select, Switch } from "@/components/ui/primitives";
import { api } from "@/lib/bridge";
import { useAtlasQuery } from "@/lib/query";
import type { Job, Settings } from "@/lib/schemas";
import { useUi } from "@/state/ui";

function Row({ title, desc, children }: { title: string; desc?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-4 border-b border-line-1 py-4 last:border-0">
      <div className="min-w-0 flex-1 basis-72">
        <p className="text-sm font-medium text-text-1">{title}</p>
        {desc && <p className="mt-0.5 text-xs text-text-3">{desc}</p>}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

const STATUS: Record<Job["status"], { label: string; tone: "accent" | "ok" | "warn" | "err" | "neutral" }> = {
  pending: { label: "Scheduled", tone: "accent" },
  running: { label: "Running", tone: "accent" },
  done: { label: "Delivered", tone: "ok" },
  missed: { label: "Missed", tone: "warn" },
  cancelled: { label: "Cancelled", tone: "neutral" },
  failed: { label: "Failed", tone: "err" },
};
const KIND: Record<string, string> = { reminder: "Reminder", deadline: "Due today", briefing: "Daily briefing" };
const when = (iso: string) => new Date(iso).toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

/** Settings → Reminders & schedule: the global pause, notices, and what Atlas has scheduled. */
export function ScheduleSettingsSection({ s, save }: { s: Settings; save: (n: Settings) => Promise<void> }) {
  const sc = s.schedule;
  const set = (patch: Partial<Settings["schedule"]>) => save({ ...s, schedule: { ...sc, ...patch } });
  const b = s.briefing;
  const setB = (patch: Partial<Settings["briefing"]>) => save({ ...s, briefing: { ...b, ...patch } });
  const jobs = useAtlasQuery("schedule-jobs", () => api.scheduleJobs(60), ["todos", "settings", "notifications"]);
  const d = jobs.data;
  return (
    <div className="mt-6 flex flex-col gap-6" data-schedule-settings>
      <Panel className="px-5">
        <Row
          title="Pause everything Atlas does on its own"
          desc="Reminders, “due today” notices and the briefing wait while paused. Anything that falls due more than the grace period ago is reported as missed when you resume, never delivered as a sudden burst."
        >
          <Switch checked={sc.paused} label="Pause proactive activity" onChange={(paused) => void set({ paused })} />
        </Row>
        <Row title="“Due today” notices" desc="For open tasks with a date but no reminder of their own.">
          <div className="flex items-center gap-3">
            <Select aria-label="Notice time" value={String(sc.deadline_hour)} disabled={!sc.deadline_notices} onChange={(e) => void set({ deadline_hour: Number(e.target.value) })} className="w-28">
              {Array.from({ length: 24 }, (_, h) => (
                <option key={h} value={h}>
                  {String(h).padStart(2, "0")}:00
                </option>
              ))}
            </Select>
            <Switch checked={sc.deadline_notices} label="Due today notices" onChange={(deadline_notices) => void set({ deadline_notices })} />
          </div>
        </Row>
        <Row title="Grace period" desc="How late a reminder may still be delivered after Atlas was closed or paused.">
          <Select aria-label="Grace period" value={String(sc.missed_grace_minutes)} onChange={(e) => void set({ missed_grace_minutes: Number(e.target.value) })} className="w-36">
            {[
              [15, "15 minutes"],
              [60, "1 hour"],
              [240, "4 hours"],
              [720, "12 hours"],
              [1440, "1 day"],
            ].map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </Select>
        </Row>
        <Row title="Where reminders appear" desc="Always in Atlas's notification list. System notifications follow Settings → Desktop.">
          <Button size="sm" onClick={() => useUi.getState().openSettings("desktop")}>
            Notification settings
          </Button>
        </Row>
      </Panel>

      <Panel className="px-5" data-briefing-settings>
        <Row title="Daily briefing" desc="A short summary of today's tasks, overdue items, reminders, approvals and missions, as a notification each day. Home always shows today's briefing, whether or not this is on.">
          <div className="flex items-center gap-3">
            <Input
              type="time"
              aria-label="Briefing time"
              value={b.time}
              disabled={!b.enabled}
              onChange={(e) => e.target.value && void setB({ time: e.target.value })}
              className="w-28"
            />
            <Switch checked={b.enabled} label="Daily briefing" onChange={(enabled) => void setB({ enabled })} />
          </div>
        </Row>
        <Row title="Include" desc="Today's tasks and reminders are always included. Appointments are not, because no calendar is connected.">
          <div className="flex flex-col items-end gap-2 text-xs text-text-2">
            {(
              [
                ["include_overdue", "Overdue tasks"],
                ["include_upcoming", "This week's deadlines"],
                ["include_missions", "Active missions"],
                ["include_recent", "What I finished this week"],
              ] as const
            ).map(([key, label]) => (
              <label key={key} className="flex items-center gap-3">
                {label}
                <Switch checked={b[key]} label={label} onChange={(v) => void setB({ [key]: v })} />
              </label>
            ))}
          </div>
        </Row>
      </Panel>

      <Panel className="px-5 py-4" data-schedule-jobs>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <p className="text-sm font-medium text-text-1">Scheduled and recent</p>
          {d && (
            <span className="text-xs text-text-3">
              {d.summary.pending} scheduled · {d.summary.done} delivered · {d.summary.missed} missed{d.summary.failed ? ` · ${d.summary.failed} failed` : ""}
            </span>
          )}
          {sc.paused && (
            <Badge tone="warn" className="ml-auto">
              <PauseCircle className="mr-1 inline size-3" aria-hidden />
              Paused
            </Badge>
          )}
        </div>
        {!d ? (
          <p className="text-xs text-text-3">Loading…</p>
        ) : d.jobs.length === 0 ? (
          <EmptyState title="Nothing scheduled" body="Give a task a reminder or a date, and it appears here." />
        ) : (
          <ul className="flex flex-col divide-y divide-line-1 text-xs">
            {d.jobs.map((j) => (
              <li key={j.id} className="flex flex-wrap items-center gap-3 py-2" data-job={j.kind} data-job-status={j.status}>
                <Badge tone={STATUS[j.status].tone}>{STATUS[j.status].label}</Badge>
                <span className="min-w-0 flex-1 truncate text-text-1">
                  {KIND[j.kind] ?? j.kind}
                  {j.label ? ` · ${j.label}` : " · (deleted task)"}
                </span>
                <span className="text-text-3">{when(j.status === "pending" ? j.run_at : (j.finished_at ?? j.run_at))}</span>
                {j.result && j.status !== "pending" && <span className="basis-full pl-1 text-[0.6875rem] text-text-3">{j.result}</span>}
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}
