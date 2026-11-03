import { Activity, ArrowRight, Brain, MessageSquarePlus, Orbit, Plug, ShieldAlert, Wrench } from "lucide-react";
import { newConversation } from "@/app/CommandPalette";
import { Emblem } from "@/components/Emblem";
import { Button, Panel, Skeleton, StatusPill } from "@/components/ui/primitives";
import { providerStatus } from "@/features/integrations/providerUi";
import { api } from "@/lib/bridge";
import { relativeTime } from "@/lib/format";
import { useAtlasQuery } from "@/lib/query";
import { useUi } from "@/state/ui";
import { TaskStatusPill } from "../shared";

function greeting(): string {
  const h = new Date().getHours();
  return h < 5 ? "Working late" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

function Stat({ icon: Icon, label, value, detail, onClick }: { icon: typeof Brain; label: string; value: string; detail: React.ReactNode; onClick: () => void }) {
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

export function HomePage() {
  const ui = useUi();
  const settings = useAtlasQuery("settings", api.settings, ["settings"]);
  const providers = useAtlasQuery("providers", api.providers, ["providers"]);
  const tools = useAtlasQuery("tools", api.tools, ["registry", "settings"]);
  const memories = useAtlasQuery("memories", () => api.memories("all"), ["memory"]);
  const approvals = useAtlasQuery("approvals", api.pendingApprovals, ["approvals"]);
  const convs = useAtlasQuery("recent-convs", () => api.conversations({ limit: 6 }), ["conversations"]);
  const tasks = useAtlasQuery("recent-tasks", () => api.tasks(null, 6), ["tasks"]);

  const name = settings.data?.companion.preferred_name.trim();
  const def = providers.data?.find((p) => p.id === settings.data?.default_provider_id) ?? providers.data?.[0];
  const ready = (tools.data ?? []).filter((t) => t.enabled && t.availability.state === "available").length;
  const pending = approvals.data?.length ?? 0;

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl px-8 py-10">
        <div className="flex flex-wrap items-center gap-6">
          <Emblem size={64} glow />
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-accent">ATLAS Co-Pilot</p>
            <h1 className="mt-1 font-display text-2xl font-semibold">
              {greeting()}
              {name ? `, ${name}` : ""}.
            </h1>
            <p className="mt-1 text-sm text-text-2">What would you like to work on?</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" size="lg" icon={<MessageSquarePlus className="size-4" aria-hidden />} onClick={() => newConversation()}>
              New conversation
            </Button>
            <Button size="lg" icon={<Orbit className="size-4" aria-hidden />} onClick={() => ui.navigate("map")}>
              Atlas Map
            </Button>
          </div>
        </div>

        {pending > 0 && (
          <button onClick={() => ui.navigate("mission")} className="mt-8 flex w-full items-center gap-3 rounded-lg border border-[color:var(--warn)]/35 bg-warn-soft px-4 py-3 text-left text-sm">
            <ShieldAlert className="size-5 text-warn" aria-hidden />
            <span className="font-medium">{pending === 1 ? "1 action is waiting for your approval" : `${pending} actions are waiting for your approval`}</span>
            <ArrowRight className="ml-auto size-4" aria-hidden />
          </button>
        )}

        <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Stat
            icon={Plug}
            label="AI model"
            value={def ? (def.default_model ?? def.label) : "Not connected"}
            detail={def ? <StatusPill tone={providerStatus[def.status].tone} label={`${def.label} · ${providerStatus[def.status].label}`} /> : <StatusPill tone="warn" label="Add a provider to begin" />}
            onClick={() => ui.navigate("integrations")}
          />
          <Stat icon={Wrench} label="Tools" value={`${ready} ready`} detail={<span className="text-text-3">of {tools.data?.length ?? "…"} registered</span>} onClick={() => ui.navigate("map")} />
          <Stat
            icon={Brain}
            label="Memory"
            value={`${memories.data?.length ?? "…"} saved`}
            detail={<span className="text-text-3">{settings.data?.memory.enabled === false ? "Memory is off" : "Only what you approve"}</span>}
            onClick={() => ui.navigate("memory")}
          />
          <Stat icon={Activity} label="Tasks" value={`${tasks.data?.length ?? 0} recent`} detail={<span className="text-text-3">{pending ? `${pending} awaiting approval` : "Nothing waiting"}</span>} onClick={() => ui.navigate("mission")} />
        </div>

        <div className="mt-8 grid gap-6 lg:grid-cols-2">
          <Panel className="p-5">
            <h2 className="font-display text-md font-semibold">Recent conversations</h2>
            {convs.loading && !convs.data ? (
              <div className="mt-4 space-y-2"><Skeleton className="h-10" /><Skeleton className="h-10" /></div>
            ) : convs.data?.length ? (
              <ul className="mt-3 divide-y divide-[color:var(--line-1)]">
                {convs.data.map((c) => (
                  <li key={c.id}>
                    <button onClick={() => ui.openConversation(c.id)} className="flex w-full items-center gap-3 py-2.5 text-left text-sm hover:text-accent-strong">
                      <span className="truncate">{c.title}</span>
                      <span className="ml-auto shrink-0 text-xs text-text-3">{relativeTime(c.updated_at)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-3 text-sm text-text-3">No conversations yet. Start one — Atlas is ready.</p>
            )}
          </Panel>
          <Panel className="p-5">
            <h2 className="font-display text-md font-semibold">Recent tasks</h2>
            {tasks.data?.length ? (
              <ul className="mt-3 divide-y divide-[color:var(--line-1)]">
                {tasks.data.map((t) => (
                  <li key={t.id}>
                    <button onClick={() => ui.openTask(t.id)} className="flex w-full items-center gap-3 py-2.5 text-left text-sm hover:text-accent-strong">
                      <span className="truncate">{t.request}</span>
                      <span className="ml-auto shrink-0"><TaskStatusPill status={t.status} /></span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-3 text-sm text-text-3">Tasks appear here when Atlas uses tools on your behalf.</p>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}
