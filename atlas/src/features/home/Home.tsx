import { PrometheusAvatar } from "@/features/siblings/avatar/PrometheusAvatar";
import { Activity, ArrowRight, Bell, Brain, CalendarClock, Check, History, ListTodo, MessageSquarePlus, PauseCircle, Plug, ShieldAlert, SlidersHorizontal, Sparkles, Target, Volume2, Wrench, X } from "lucide-react";
import { useState, type ReactNode } from "react";
import { toast } from "sonner";
import { newConversation } from "@/app/CommandPalette";
import { Emblem } from "@/components/Emblem";
import { focusWhat, stopFocus, useFocus, useFocusUi } from "@/features/focus/Focus";
import { Dialog } from "@/components/ui/dialog";
import { Badge, Button, ErrorNote, Panel, Skeleton, StatusPill, Switch } from "@/components/ui/primitives";
import { STATE_LABEL } from "@/features/siblings/Siblings";
import { providerStatus } from "@/features/integrations/providerUi";
import { dueLabel } from "@/features/tasks/dates";
import { api, AtlasError } from "@/lib/bridge";
import { cn, relativeTime } from "@/lib/format";
import { useAtlasQuery } from "@/lib/query";
import type { MissionState, Recap, Settings, Todo } from "@/lib/schemas";
import { useUi } from "@/state/ui";
import { useVoice } from "@/state/voice";

function greeting(): string {
  const h = new Date().getHours();
  return h < 5 ? "Working late" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

function Stat({ icon: Icon, label, value, detail, onClick }: { icon: typeof Brain; label: string; value: string; detail: ReactNode; onClick: () => void }) {
  return (
    <button onClick={onClick} className="group flex flex-col gap-2 rounded-lg border border-line-1 bg-bg-2/80 p-4 text-left shadow-1 transition-colors hover:border-line-3">
      <span className="flex items-center gap-2 text-xs text-text-3">
        <Icon className="size-4 text-accent" aria-hidden /> {label}
        <ArrowRight className="ml-auto size-3.5 opacity-0 transition-opacity group-hover:opacity-100" aria-hidden />
      </span>
      <span className="font-display text-lg font-semibold text-text-1">{value}</span>
      <span className="text-xs">{detail}</span>
    </button>
  );
}

function Card({ title, icon: Icon, action, children, ...rest }: { title: string; icon: typeof Brain; action?: ReactNode; children: ReactNode } & React.HTMLAttributes<HTMLElement>) {
  return (
    <Panel className="p-5" {...rest}>
      <div className="mb-3 flex items-center gap-2">
        <Icon className="size-4 text-accent" aria-hidden />
        <h2 className="font-display text-md font-semibold">{title}</h2>
        {action && <span className="ml-auto">{action}</span>}
      </div>
      {children}
    </Panel>
  );
}

/** A task line with a tick to complete it. */
function TodoLine({ t, today }: { t: Todo; today: string }) {
  const openTodo = useUi((u) => u.openTodo);
  const due = dueLabel(t, today);
  return (
    <li className="flex items-center gap-3 py-2" data-cc-task={t.title}>
      <button
        role="checkbox"
        aria-checked={false}
        aria-label={`Complete ${t.title}`}
        onClick={() => void api.todoSetStatus(t.id, "done").then(() => toast.success(`Done: ${t.title}`)).catch((e) => toast.error(e instanceof AtlasError ? e.message : "The task could not be completed"))}
        className="grid size-5 shrink-0 place-items-center rounded-full border border-line-2 hover:border-accent"
      />
      <button onClick={() => openTodo(t.id)} className="min-w-0 flex-1 truncate text-left text-sm hover:text-accent-strong">
        {t.title}
      </button>
      {t.priority === "urgent" || t.priority === "high" ? <Badge tone={t.priority === "urgent" ? "err" : "warn"}>{t.priority}</Badge> : null}
      {due && <span className={cn("shrink-0 text-xs", t.overdue ? "text-err" : "text-text-3")}>{t.overdue ? `${due} · overdue` : due}</span>}
    </li>
  );
}

const NOTICE_KIND: Record<string, string> = { approval: "Approval", reply: "Reply", mission: "Mission", error: "Problem", reminder: "Reminder", deadline: "Due today", briefing: "Briefing" };

/** "While you were away": what Atlas recorded since it was last open. Nothing here resumes by itself. */
function RecapCard({ r }: { r: Recap }) {
  const ui = useUi();
  const away = new Date(r.since);
  const facts = [
    r.reminders_delivered ? `${r.reminders_delivered} reminder${r.reminders_delivered === 1 ? "" : "s"} delivered` : "",
    r.reminders_missed ? `${r.reminders_missed} missed` : "",
    r.missions_updated ? `${r.missions_updated} mission${r.missions_updated === 1 ? "" : "s"} updated by Prometheus` : "",
    r.approvals_pending ? `${r.approvals_pending} waiting for your approval` : "",
  ].filter(Boolean);
  return (
    <Panel className="mt-6 p-5" data-recap>
      <div className="flex items-start gap-3">
        <History className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
        <div className="min-w-0 flex-1">
          <h2 className="font-display text-md font-semibold">While you were away</h2>
          <p className="text-xs text-text-3">Since {away.toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" })} ({relativeTime(r.since)})</p>
          {r.empty ? (
            <p className="mt-2 text-sm text-text-2">All quiet: nothing happened while Atlas was closed.</p>
          ) : (
            <>
              {facts.length > 0 && <p className="mt-2 text-sm text-text-2">{facts.join(" · ")}.</p>}
              {r.notices.length > 0 && (
                <ul className="mt-2 flex flex-col gap-1 text-sm">
                  {r.notices.map(([k, t], i) => (
                    <li key={i} className="flex items-center gap-2">
                      <span className="w-20 shrink-0 text-xs text-text-3">{NOTICE_KIND[k] ?? k}</span>
                      <span className="truncate" data-recap-notice>
                        {t}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              {r.tasks_done.length > 0 && <p className="mt-2 text-sm text-text-2">Finished: {r.tasks_done.join("; ")}.</p>}
              {r.interrupted.length > 0 && (
                <div className="mt-3 rounded-md border border-line-2 bg-bg-3/60 p-3" data-recap-interrupted>
                  <p className="text-xs text-text-2">Interrupted when Atlas closed. Nothing was resumed; open one to pick it up yourself.</p>
                  <ul className="mt-1 flex flex-col gap-1 text-sm">
                    {r.interrupted.map(([id, req, conv]) => (
                      <li key={id} className="flex items-center gap-2">
                        <span className="min-w-0 flex-1 truncate" data-recap-request>
                          {req}
                        </span>
                        <Button size="sm" variant="ghost" onClick={() => (conv ? ui.openConversation(conv) : ui.openTask(id))}>
                          Open
                        </Button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </div>
        <Button size="sm" variant="ghost" icon={<X className="size-3.5" aria-hidden />} aria-label="Dismiss the recap" onClick={() => void api.recapDismiss().catch(() => toast.error("Could not dismiss"))}>
          Dismiss
        </Button>
      </div>
    </Panel>
  );
}

const HOME_PARTS: [keyof Settings["home"], string][] = [
  ["show_briefing", "Today's briefing"],
  ["show_missions", "Active missions"],
  ["show_conversations", "Recent conversations"],
  ["show_accomplished", "Recently finished"],
  ["show_status", "System status (model, tools, memory, activity)"],
];

/** Home, as the Command Center: today's priorities and what needs attention, from real data only. */
export function HomePage() {
  const ui = useUi();
  const [customize, setCustomize] = useState(false);
  const settings = useAtlasQuery("settings", api.settings, ["settings"]);
  const cc = useAtlasQuery("command-center", api.commandCenter, ["todos", "approvals", "missions", "conversations", "notifications", "settings"]);
  const providers = useAtlasQuery("providers", api.providers, ["providers"]);
  const tools = useAtlasQuery("tools", api.tools, ["registry", "settings"]);
  const memories = useAtlasQuery("memories", () => api.memories("all"), ["memory"]);
  const runs = useAtlasQuery("recent-tasks", () => api.tasks(null, 6), ["tasks"]);
  const siblings = useAtlasQuery("siblings", api.siblings, ["siblings"]);
  const voice = useVoice();
  const recap = useAtlasQuery("recap", api.recap, ["notifications", "todos", "approvals"]);
  const focus = useFocus();
  const startFocus = useFocusUi((f) => f.start);
  const active = focus.data?.active ?? null;
  const sibling = siblings.data?.find((s) => s.status === "paired");
  const s = settings.data;
  const home = s?.home;
  const name = s?.companion.preferred_name.trim();
  const def = providers.data?.find((p) => p.id === s?.default_provider_id) ?? providers.data?.[0];
  const ready = (tools.data ?? []).filter((t) => t.enabled && t.availability.state === "available").length;
  const d = cc.data;
  const b = d?.briefing;
  const pending = b?.approvals_pending ?? 0;
  const priorities = b ? [...b.overdue, ...b.today] : [];
  const canSpeak = Boolean(voice.settings?.enabled && voice.status?.tts_ready);

  const saveHome = (patch: Partial<Settings["home"]>) => {
    if (s) void api.updateSettings({ ...s, home: { ...s.home, ...patch } }).catch((e) => toast.error(e instanceof AtlasError ? e.message : "Could not save"));
  };

  return (
    <div className="h-full overflow-y-auto" data-command-center>
      <div className="mx-auto max-w-6xl px-8 py-10">
        <div className="flex flex-wrap items-center gap-6">
          <Emblem size={64} glow />
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-accent">ATLAS Co-Pilot · Command Center</p>
            <h1 className="mt-1 font-display text-2xl font-semibold">
              {greeting()}
              {name ? `, ${name}` : ""}.
            </h1>
            <p className="mt-1 text-sm text-text-2">{b ? `${b.weekday}, ${new Date(`${b.date}T00:00:00`).toLocaleDateString([], { day: "numeric", month: "long" })}` : "What would you like to work on?"}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" size="lg" icon={<MessageSquarePlus className="size-4" aria-hidden />} onClick={() => newConversation()}>
              New conversation
            </Button>
            <Button size="lg" icon={<ListTodo className="size-4" aria-hidden />} onClick={() => ui.navigate("tasks")}>
              Tasks
            </Button>
            {active ? (
              <Button size="lg" icon={<Target className="size-4" aria-hidden />} onClick={stopFocus} aria-label={`Stop focus session: ${focusWhat(active)}`}>
                Stop focus
              </Button>
            ) : (
              <Button size="lg" icon={<Target className="size-4" aria-hidden />} onClick={() => startFocus()}>
                Focus
              </Button>
            )}
            <Button size="lg" variant="ghost" icon={<SlidersHorizontal className="size-4" aria-hidden />} onClick={() => setCustomize(true)} aria-label="Customize Home">
              Customize
            </Button>
          </div>
        </div>

        {d?.paused && (
          <button onClick={() => ui.openSettings("schedule")} className="mt-6 flex w-full items-center gap-3 rounded-lg border border-line-2 bg-bg-2 px-4 py-3 text-left text-sm" data-paused-banner>
            <PauseCircle className="size-5 text-warn" aria-hidden />
            <span className="font-medium">Proactive activity is paused: reminders and the briefing are on hold.</span>
            <span className="ml-auto text-xs text-text-3">Manage</span>
          </button>
        )}
        {pending > 0 && (
          <button onClick={() => ui.navigate("mission")} className="mt-4 flex w-full items-center gap-3 rounded-lg border border-[color:var(--warn)]/35 bg-warn-soft px-4 py-3 text-left text-sm">
            <ShieldAlert className="size-5 text-warn" aria-hidden />
            <span className="font-medium">{pending === 1 ? "1 action is waiting for your approval" : `${pending} actions are waiting for your approval`}</span>
            <ArrowRight className="ml-auto size-4" aria-hidden />
          </button>
        )}
        {sibling && (
          <button onClick={() => ui.navigate("siblings")} className="mt-4 inline-flex items-center gap-2 rounded-full border border-line-2 bg-bg-2/70 px-3 py-1.5 text-xs text-text-2 hover:border-line-3 hover:text-text-1" aria-label={`Sibling: ${sibling.name}, ${sibling.connected ? "connected" : "not connected"}`}>
            <PrometheusAvatar state={sibling.connected ? "idle" : "offline"} size={16} birth={false} />
            <span>{sibling.name}</span>
            <span className={sibling.connected ? "text-ok" : "text-text-3"}>· {sibling.connected ? "connected" : "not connected"}</span>
          </button>
        )}

        {recap.data && <RecapCard r={recap.data} />}

        {cc.error && <div className="mt-6"><ErrorNote message={cc.error.message} onRetry={cc.reload} /></div>}

        {home?.show_briefing !== false && (
          <Panel className="mt-6 p-5" data-briefing>
            <div className="flex flex-wrap items-start gap-3">
              <Sparkles className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
              <div className="min-w-0 flex-1">
                <h2 className="font-display text-md font-semibold">Today</h2>
                {d ? <p className="mt-1 text-sm leading-relaxed text-text-2" data-briefing-text>{d.briefing_text}</p> : <Skeleton className="mt-2 h-10" />}
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {canSpeak && d && (
                  <Button size="sm" icon={<Volume2 className="size-3.5" aria-hidden />} onClick={() => voice.speakText(d.briefing_text)}>
                    Read aloud
                  </Button>
                )}
                <Button size="sm" variant="ghost" onClick={() => ui.openSettings("schedule")}>
                  {s?.briefing.enabled ? `Daily at ${s.briefing.time}` : "Daily briefing: off"}
                </Button>
              </div>
            </div>
          </Panel>
        )}

        <div className="mt-6 grid gap-6 lg:grid-cols-2">
          <Card title="Today's priorities" icon={ListTodo} action={<Button size="sm" variant="ghost" onClick={() => ui.navigate("tasks")}>All tasks</Button>} data-priorities>
            {!b ? (
              <Skeleton className="h-16" />
            ) : priorities.length ? (
              <ul className="divide-y divide-[color:var(--line-1)]">
                {priorities.slice(0, 8).map((t) => (
                  <TodoLine key={t.id} t={t} today={b.date} />
                ))}
              </ul>
            ) : (
              <p className="text-sm text-text-3">Nothing due today{b.counts.open ? ` · ${b.counts.open} open in total` : ""}.</p>
            )}
            {b && priorities.length > 8 && <p className="mt-2 text-xs text-text-3">and {priorities.length - 8} more</p>}
          </Card>
          <Card title="Coming up" icon={CalendarClock} data-coming-up>
            {!b ? (
              <Skeleton className="h-16" />
            ) : b.upcoming.length || b.reminders_today.length ? (
              <>
                {b.reminders_today.length > 0 && (
                  <ul className="mb-2 flex flex-col gap-1 text-sm">
                    {b.reminders_today.map(([h, title]) => (
                      <li key={h + title} className="flex items-center gap-2">
                        <Bell className="size-3.5 text-accent" aria-hidden /> <span className="text-text-3">{h}</span> {title}
                      </li>
                    ))}
                  </ul>
                )}
                <ul className="divide-y divide-[color:var(--line-1)]">
                  {b.upcoming.slice(0, 6).map((t) => (
                    <TodoLine key={t.id} t={t} today={b.date} />
                  ))}
                </ul>
              </>
            ) : (
              <p className="text-sm text-text-3">No deadlines or reminders in the next 7 days.</p>
            )}
            {b && b.notes.length > 0 && <p className="mt-3 text-[0.6875rem] text-text-3">{b.notes.join(" ")}</p>}
          </Card>

          {home?.show_missions !== false && b && b.missions.length > 0 && (
            <Card title="Active missions" icon={Activity}>
              <ul className="divide-y divide-[color:var(--line-1)]">
                {b.missions.map((m) => (
                  <li key={m.id}>
                    <button onClick={() => ui.navigate("siblings")} className="flex w-full items-center gap-3 py-2.5 text-left text-sm hover:text-accent-strong">
                      <span className="truncate">{m.title}</span>
                      <span className="ml-auto shrink-0 text-xs text-text-3">{STATE_LABEL[m.state as MissionState] ?? m.state}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </Card>
          )}
          {home?.show_conversations !== false && (
            <Card title="Recent conversations" icon={MessageSquarePlus}>
              {!b ? (
                <Skeleton className="h-16" />
              ) : b.recent_conversations.length ? (
                <ul className="divide-y divide-[color:var(--line-1)]">
                  {b.recent_conversations.map((c) => (
                    <li key={c.id}>
                      <button onClick={() => ui.openConversation(c.id)} className="flex w-full items-center gap-3 py-2.5 text-left text-sm hover:text-accent-strong">
                        <span className="truncate">{c.title}</span>
                        <span className="ml-auto shrink-0 text-xs text-text-3">{relativeTime(c.updated_at)}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-text-3">No conversations yet. Start one — Atlas is ready.</p>
              )}
            </Card>
          )}
          {home?.show_accomplished !== false && b && b.accomplished.length > 0 && (
            <Card title="Recently finished" icon={Check} data-accomplished>
              <ul className="flex flex-col gap-1 text-sm text-text-2">
                {b.accomplished.slice(0, 6).map((t) => (
                  <li key={t.id} className="flex items-center gap-2">
                    <Check className="size-3.5 text-ok" aria-hidden /> <span className="truncate">{t.title}</span>
                    <span className="ml-auto shrink-0 text-xs text-text-3">{relativeTime(t.completed_at)}</span>
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-text-3">{b.counts.done_week} finished in the last 7 days.</p>
            </Card>
          )}
        </div>

        {home?.show_status !== false && (
          <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4" data-status>
            <Stat
              icon={Plug}
              label="AI model"
              value={def ? (def.default_model ?? def.label) : "Not connected"}
              detail={def ? <StatusPill tone={providerStatus[def.status].tone} label={`${def.label} · ${providerStatus[def.status].label}`} /> : <StatusPill tone="warn" label="Add a provider to begin" />}
              onClick={() => ui.navigate("integrations")}
            />
            <Stat icon={Wrench} label="Tools" value={`${ready} ready`} detail={<span className="text-text-3">of {tools.data?.length ?? "…"} registered</span>} onClick={() => ui.navigate("map")} />
            <Stat icon={Brain} label="Memory" value={`${memories.data?.length ?? "…"} saved`} detail={<span className="text-text-3">{s?.memory.enabled === false ? "Memory is off" : "Only what you approve"}</span>} onClick={() => ui.navigate("memory")} />
            <Stat icon={Activity} label="Activity" value={`${runs.data?.length ?? 0} recent runs`} detail={<span className="text-text-3">{pending ? `${pending} awaiting approval` : "Nothing waiting"}</span>} onClick={() => ui.navigate("mission")} />
          </div>
        )}
      </div>

      <Dialog open={customize} onOpenChange={setCustomize} title="Customize Home" description="Choose what the Command Center shows. Today's priorities and what's coming up are always shown." footer={<Button variant="primary" onClick={() => setCustomize(false)}>Done</Button>}>
        <div className="flex flex-col gap-3 text-sm" data-customize-home>
          {HOME_PARTS.map(([key, label]) => (
            <div key={key} className="flex items-center justify-between gap-4">
              <span>{label}</span>
              <Switch checked={home?.[key] ?? true} label={label} onChange={(v) => saveHome({ [key]: v })} />
            </div>
          ))}
        </div>
      </Dialog>
    </div>
  );
}
