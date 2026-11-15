import { Activity, ArrowRight, Cloud, Cpu, Download, Eraser, Loader2, Search, ShieldCheck, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Badge, Button, EmptyState, Input, PageHeader, Panel, Select, Skeleton, Switch } from "@/components/ui/primitives";
import { api, AtlasError } from "@/lib/bridge";
import { cn, formatTokens, formatUsd, relativeTime } from "@/lib/format";
import { useAtlasQuery } from "@/lib/query";
import type { AuditEvent, Settings, TrustFilter, TrustPermission } from "@/lib/schemas";
import { useUi, type Route } from "@/state/ui";

const errText = (e: unknown, fallback: string) => (e instanceof AtlasError ? e.message : fallback);

export const CATEGORY_LABEL: Record<string, string> = {
  providers: "Models and providers",
  knowledge: "Knowledge Vault",
  memory: "Memory",
  tools: "Tools and files",
  forge: "Atlas Forge",
  approvals: "Approvals",
  sibling: "Prometheus (sibling)",
  background: "Background work",
  voice: "Voice",
  settings: "Settings and permissions",
  trust: "Trust Center",
  system: "Atlas",
};

const n = (v: unknown) => (typeof v === "number" ? v : 0);
const s = (v: unknown) => (typeof v === "string" ? v : "");

/** One plain sentence for an event, from its recorded fields only. */
export function describe(e: AuditEvent): string {
  const d = (e.detail ?? {}) as Record<string, unknown>;
  const who = e.provider ? ` (${e.provider}${e.model ? ` · ${e.model}` : ""})` : "";
  switch (e.kind) {
    case "provider.request":
      return `A request was ${e.outcome === "ok" ? "answered" : "attempted"} by ${e.provider ?? "a model"}${e.model ? ` · ${e.model}` : ""}${d.input_tokens != null ? `: ${n(d.input_tokens)} tokens in, ${n(d.output_tokens)} out` : ""}`;
    case "vault.passages": {
      const docs = Array.isArray(d.documents) ? (d.documents as string[]) : [];
      return `${n(d.passages)} passage${n(d.passages) === 1 ? "" : "s"} from ${docs.length ? docs.join(", ") : "your documents"} went with a message${who}`;
    }
    case "vault.passages_withheld":
      return `${n(d.passages)} relevant passage${n(d.passages) === 1 ? " was" : "s were"} held back (local-only)${who}`;
    case "vault.import":
      return `A ${s(d.kind).toUpperCase() || "document"} was imported into the Knowledge Vault`;
    case "vault.indexed":
      return `A document was indexed: ${n(d.passages)} passage${n(d.passages) === 1 ? "" : "s"}${d.pages ? `, ${n(d.pages)} page${n(d.pages) === 1 ? "" : "s"}` : ""}`;
    case "vault.failed":
      return "A document could not be indexed";
    case "vault.reindex":
      return "A document was queued for re-indexing";
    case "vault.move":
      return "A document was moved to another library";
    case "vault.remove":
      return "A document was removed from the Knowledge Vault (the original file was kept)";
    case "memory.used":
      return `${n(d.count)} memor${n(d.count) === 1 ? "y" : "ies"} went with a message${who}`;
    case "memory.created":
      return e.actor === "assistant" ? "Atlas saved a memory you approved" : "You added a memory";
    case "memory.corrected":
      return "You corrected a memory";
    case "memory.updated":
      return "You changed a memory's settings";
    case "memory.confirmed":
      return "You confirmed a memory is still true";
    case "memory.outdated":
      return "You marked a memory outdated";
    case "memory.restored":
      return "You restored a memory";
    case "memory.replaced":
      return "You replaced a memory with a newer version";
    case "memory.deleted":
      return "You deleted a memory";
    case "memory.deleted_all":
      return `You deleted all memories (${n(d.count)})`;
    case "approval.requested":
      return `Atlas asked for approval: ${s(d.action) || e.resource || "an action"}`;
    case "approval.decided":
      return `Approval ${e.approval === "approved" ? "given" : e.approval}${e.resource ? ` for ${e.resource}` : ""}`;
    case "approval.consumed":
      return "An approved action ran";
    case "tool.step":
      return `Tool ${e.resource ?? e.tool_id ?? ""} ${e.outcome === "ok" ? "ran" : e.outcome === "denied" ? "was refused" : e.outcome === "cancelled" ? "was stopped" : "failed"}`;
    case "trust.history_cleared":
      return `You cleared ${n(d.removed)} activity records`;
    case "trust.exported":
      return "You exported the activity record";
    case "settings.updated":
      return "Settings were changed";
    case "scheduler.ran":
      return "Scheduled reminders or notices ran";
    case "app.start":
      return "Atlas started";
    default:
      return e.kind.replace(/[._]/g, " ").replace(/^\w/, (c) => c.toUpperCase());
  }
}

function setPath(obj: Settings, path: string, value: unknown): Settings {
  const copy = structuredClone(obj) as Record<string, unknown>;
  const parts = path.split(".");
  let cur = copy;
  for (const p of parts.slice(0, -1)) cur = cur[p] as Record<string, unknown>;
  cur[parts[parts.length - 1] as string] = value;
  return copy as Settings;
}

function getPath(obj: Settings, path: string): unknown {
  return path.split(".").reduce<unknown>((o, p) => (o as Record<string, unknown> | undefined)?.[p], obj);
}

function PermissionControl({ p }: { p: TrustPermission }) {
  const settings = useAtlasQuery("settings", api.settings, ["settings"]);
  const providers = useAtlasQuery("providers", api.providers, ["providers"]);
  const navigate = useUi((u) => u.navigate);
  const save = async (path: string, value: unknown) => {
    if (!settings.data) return;
    try {
      await api.updateSettings(setPath(settings.data, path, value));
      toast.success("Saved. Atlas applies it to the very next action.");
    } catch (e) {
      toast.error(errText(e, "The change could not be saved"));
    }
  };
  const c = p.control;
  if (c.kind === "gate" && c.setting && settings.data) {
    return (
      <Select aria-label={p.name} value={String(getPath(settings.data, c.setting))} onChange={(e) => save(c.setting!, e.target.value)} className="w-44">
        <option value="ask">Ask each time</option>
        <option value="allow">Allow</option>
      </Select>
    );
  }
  if (c.kind === "switch" && c.setting && settings.data) {
    const inverted = c.setting === "schedule.paused";
    const raw = Boolean(getPath(settings.data, c.setting));
    return <Switch checked={inverted ? !raw : raw} label={p.name} onChange={(v) => save(c.setting!, inverted ? !v : v)} />;
  }
  if (c.kind === "provider" && c.provider_id) {
    const pr = providers.data?.find((x) => x.id === c.provider_id);
    if (!pr) return null;
    return (
      <Switch
        checked={pr.enabled}
        label={p.name}
        onChange={async (v) => {
          try {
            await api.updateProvider(pr.id, pr.label, pr.base_url, pr.default_model, v);
            toast.success(v ? "Provider enabled" : "Provider disabled: nothing more is sent to it");
          } catch (e) {
            toast.error(errText(e, "The provider could not be changed"));
          }
        }}
      />
    );
  }
  if (c.kind === "grant" && c.grant_id) {
    return (
      <Button
        size="sm"
        variant="danger"
        onClick={async () => {
          try {
            await api.revokeGrant(c.grant_id!);
            toast.success("Access revoked");
          } catch (e) {
            toast.error(errText(e, "Could not revoke"));
          }
        }}
      >
        Revoke
      </Button>
    );
  }
  if (c.kind === "page" && c.route) {
    return (
      <Button size="sm" variant="ghost" icon={<ArrowRight className="size-3.5" aria-hidden />} onClick={() => navigate(c.route as Route)}>
        Manage
      </Button>
    );
  }
  return null;
}

function EventRow({ e }: { e: AuditEvent }) {
  const [open, setOpen] = useState(false);
  const problem = e.outcome !== "ok";
  return (
    <li className="rounded-lg border border-line-1 bg-bg-2/70 px-4 py-2.5" data-event={e.kind} data-left-device={e.left_device ? "true" : "false"}>
      <button type="button" className="flex w-full items-start gap-3 text-left" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <span className={cn("mt-1.5 size-2 shrink-0 rounded-full", problem ? "bg-warn" : e.left_device ? "bg-accent" : "bg-text-3")} aria-hidden />
        <span className="min-w-0 flex-1">
          <span className="block text-sm text-text-1">{describe(e)}</span>
          <span className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-text-3">
            <span title={e.ts}>{relativeTime(e.ts)}</span>
            <span>{CATEGORY_LABEL[e.category] ?? e.category}</span>
            <span>{e.actor === "user" ? "by you" : e.actor === "assistant" ? "by the model, through a tool" : e.actor === "sibling" ? "by Prometheus" : "by Atlas"}</span>
            {e.left_device ? <span className="text-accent">left this computer</span> : e.provider ? <span>stayed on this computer</span> : null}
            {e.approval && e.approval !== "not_needed" && <span>approval: {e.approval}</span>}
            {problem && <span className="text-warn">{e.outcome}</span>}
            {e.reversible === false && <span>cannot be undone</span>}
          </span>
        </span>
      </button>
      {open && (
        <dl className="mt-2 grid grid-cols-[8rem_1fr] gap-x-3 gap-y-1 border-t border-line-1 pt-2 text-xs" data-event-details>
          <dt className="text-text-3">Event</dt>
          <dd className="font-mono text-text-2">{e.kind}</dd>
          {e.provider && (
            <>
              <dt className="text-text-3">Provider · model</dt>
              <dd className="text-text-2">
                {e.provider}
                {e.model ? ` · ${e.model}` : ""}
              </dd>
            </>
          )}
          {e.resource && (
            <>
              <dt className="text-text-3">Resource</dt>
              <dd className="break-all font-mono text-text-2">{e.resource}</dd>
            </>
          )}
          {Object.entries((e.detail ?? {}) as Record<string, unknown>).map(([k, v]) => (
            <Detail key={k} k={k} v={v} />
          ))}
          <dt className="text-text-3">Recorded</dt>
          <dd className="text-text-2">{new Date(e.ts).toLocaleString()}</dd>
        </dl>
      )}
    </li>
  );
}

function Detail({ k, v }: { k: string; v: unknown }) {
  if (v === null || v === undefined || v === "") return null;
  const label = k.replace(/_/g, " ");
  const value = Array.isArray(v) ? v.join(", ") : typeof v === "object" ? JSON.stringify(v) : String(v);
  return (
    <>
      <dt className="text-text-3">{label}</dt>
      <dd className="break-words text-text-2">{k === "estimated_cost_usd" && typeof v === "number" ? `${formatUsd(v)} (estimate)` : value}</dd>
    </>
  );
}

function Timeline() {
  const [category, setCategory] = useState("");
  const [q, setQ] = useState("");
  const [leftOnly, setLeftOnly] = useState(false);
  const [problems, setProblems] = useState(false);
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [more, setMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const filter = (before: number | null): TrustFilter => ({ category: category || null, search: q.trim() || null, left_device_only: leftOnly, outcome: problems ? "problems" : null, before_id: before, limit: 40 });
  useEffect(() => {
    let live = true;
    const t = setTimeout(() => {
      api.trustTimeline(filter(null)).then(
        (r) => {
          if (!live) return;
          setEvents(r);
          setMore(r.length === 40);
        },
        () => live && setEvents([]),
      );
    }, 200);
    return () => {
      live = false;
      clearTimeout(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [category, q, leftOnly, problems]);
  const loadMore = async () => {
    if (!events?.length) return;
    setLoading(true);
    try {
      const r = await api.trustTimeline(filter(events[events.length - 1]!.id));
      setEvents([...events, ...r]);
      setMore(r.length === 40);
    } finally {
      setLoading(false);
    }
  };
  return (
    <section aria-label="Activity" className="space-y-3" data-trust-timeline>
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-56 flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-text-3" aria-hidden />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by event, provider, model or item" className="pl-8" aria-label="Search activity" />
        </div>
        <Select aria-label="Activity type" value={category} onChange={(e) => setCategory(e.target.value)} className="w-56">
          <option value="">Everything</option>
          {Object.entries(CATEGORY_LABEL).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </Select>
        <Button size="sm" variant={leftOnly ? "primary" : "ghost"} aria-pressed={leftOnly} onClick={() => setLeftOnly(!leftOnly)} icon={<Cloud className="size-3.5" aria-hidden />}>
          Left this computer
        </Button>
        <Button size="sm" variant={problems ? "primary" : "ghost"} aria-pressed={problems} onClick={() => setProblems(!problems)} icon={<TriangleAlert className="size-3.5" aria-hidden />}>
          Problems
        </Button>
      </div>
      {!events ? (
        <Skeleton className="h-32" />
      ) : events.length ? (
        <>
          <ol className="space-y-1.5">
            {events.map((e) => (
              <EventRow key={e.id} e={e} />
            ))}
          </ol>
          {more && (
            <Button variant="ghost" onClick={loadMore} loading={loading} className="w-full">
              Show older activity
            </Button>
          )}
        </>
      ) : (
        <p className="py-8 text-center text-sm text-text-3">No recorded activity matches.</p>
      )}
    </section>
  );
}

export function TrustPage() {
  const o = useAtlasQuery("trust-overview", api.trustOverview, ["settings", "providers", "vault", "memory", "approvals", "tasks", "todos", "missions"]);
  const navigate = useUi((u) => u.navigate);
  const [clearing, setClearing] = useState(false);
  const data = o.data;
  const total = data?.categories.reduce((a, c) => a + c.events, 0) ?? 0;
  const problems = data?.categories.reduce((a, c) => a + c.problems, 0) ?? 0;
  const bg = data?.background;
  const runningNow = (bg?.running_conversations ?? 0) + (bg?.scheduler.running ?? 0) + (bg?.vault.filter((v) => v.status === "processing").length ?? 0) + (bg?.missions_active ?? 0) + (bg?.forge_runs_running ?? 0);
  const open = data?.permissions.filter((p) => p.open) ?? [];
  return (
    <div className="h-full overflow-y-auto">
      <PageHeader
        eyebrow="Trust"
        title="Trust Center"
        subtitle="What Atlas did, what it sent and where, and what it may do. Built only from what Atlas recorded on this computer; nothing here is sent anywhere."
        actions={
          <>
            <Button
              icon={<Download className="size-4" aria-hidden />}
              onClick={async () => {
                try {
                  const p = await api.trustExport(30);
                  if (p) toast.success(`Saved to ${p}`);
                } catch (e) {
                  toast.error(errText(e, "Export failed"));
                }
              }}
            >
              Export activity
            </Button>
            <Button icon={<Eraser className="size-4" aria-hidden />} onClick={() => setClearing(true)}>
              Clear history…
            </Button>
          </>
        }
      />
      <div className="space-y-6 px-8 py-6" data-trust>
        {!data ? (
          <Skeleton className="h-24" />
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-4" data-trust-summary>
              <Panel className="px-4 py-3">
                <p className="text-xs text-text-3">Recorded activity (7 days)</p>
                <p className="mt-1 font-display text-lg font-semibold">{total}</p>
              </Panel>
              <Panel className="px-4 py-3">
                <p className="text-xs text-text-3">Sent off this computer (7 days)</p>
                <p className="mt-1 font-display text-lg font-semibold" data-left-device-count>
                  {data.left_device_7d}
                </p>
              </Panel>
              <Panel className="px-4 py-3">
                <p className="text-xs text-text-3">Problems (7 days)</p>
                <p className={cn("mt-1 font-display text-lg font-semibold", problems > 0 && "text-warn")}>{problems}</p>
              </Panel>
              <Panel className="px-4 py-3">
                <p className="text-xs text-text-3">Running now</p>
                <p className="mt-1 flex items-center gap-2 font-display text-lg font-semibold">
                  {runningNow > 0 && <Loader2 className="size-4 animate-spin text-accent" aria-hidden />}
                  {runningNow}
                </p>
              </Panel>
            </div>

            <section aria-label="Background work" className="space-y-2" data-trust-background>
              <h2 className="font-display text-md font-semibold">Running and waiting</h2>
              <Panel className="grid gap-x-6 gap-y-2 px-4 py-3 text-sm sm:grid-cols-2">
                <p>
                  {bg!.running_conversations} conversation{bg!.running_conversations === 1 ? "" : "s"} replying now
                </p>
                <p>
                  {bg!.pending_approvals} approval{bg!.pending_approvals === 1 ? "" : "s"} waiting for you
                  {bg!.pending_approvals > 0 && (
                    <button type="button" className="ml-2 text-accent hover:underline" onClick={() => navigate("mission")}>
                      review
                    </button>
                  )}
                </p>
                <p>
                  Scheduler: {bg!.scheduler.pending} waiting{bg!.scheduler.next_at ? `, next ${relativeTime(bg!.scheduler.next_at)}` : ""}
                  {bg!.scheduler.missed_7d > 0 ? `, ${bg!.scheduler.missed_7d} missed this week` : ""}
                </p>
                <p>
                  Knowledge Vault: {bg!.vault.filter((v) => v.status === "processing").length} processing, {bg!.vault.filter((v) => v.status === "failed").length} failed
                </p>
                <p>Missions with Prometheus: {bg!.missions_active} active</p>
                <p>
                  Atlas Forge commands running: {bg!.forge_runs_running}
                  {bg!.tasks_interrupted_7d > 0 ? ` · ${bg!.tasks_interrupted_7d} interrupted this week` : ""}
                </p>
              </Panel>
            </section>

            <section aria-label="Where your data goes" className="space-y-2" data-trust-providers>
              <h2 className="font-display text-md font-semibold">Where your messages go</h2>
              <p className="text-xs text-text-3">
                Default: {data.routing.default_provider ?? "not set"}
                {data.routing.default_model ? ` · ${data.routing.default_model}` : ""} · switching to another provider when one fails is {data.routing.cross_provider_fallback ? "on" : "off"} · offline mode is{" "}
                {data.routing.offline_mode ? "on" : "off"}. Tokens are what each provider reported; costs are Atlas's estimates from its price list (providers do not report cost).
              </p>
              {data.providers.length ? (
                <ul className="space-y-1.5">
                  {data.providers.map((p) => (
                    <li key={p.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-line-1 bg-bg-2/70 px-4 py-2.5 text-sm" data-provider={p.label}>
                      <span className="flex min-w-48 items-center gap-2 font-medium">
                        {p.local ? <Cpu className="size-4 text-text-2" aria-hidden /> : <Cloud className="size-4 text-accent" aria-hidden />}
                        {p.label}
                        {p.is_default && <Badge tone="accent">default</Badge>}
                        {!p.enabled && <Badge>disabled</Badge>}
                      </span>
                      <span className="text-xs text-text-3">{p.local ? "On this computer" : "Cloud: leaves this computer"}</span>
                      <span className="text-xs text-text-2">
                        {p.requests_30d} requests (30 days){p.failed_30d ? `, ${p.failed_30d} failed` : ""}
                      </span>
                      <span className="text-xs text-text-2">
                        {formatTokens(p.input_tokens_30d)} in · {formatTokens(p.output_tokens_30d)} out
                      </span>
                      <span className="text-xs text-text-2">
                        {p.local ? "no cost" : `${formatUsd(p.estimated_cost_usd_30d)} estimated`}
                        {p.unpriced_requests_30d && !p.local ? ` (${p.unpriced_requests_30d} unpriced)` : ""}
                      </span>
                      <span className="ml-auto text-xs text-text-3">{p.last_used_at ? `last used ${relativeTime(p.last_used_at)}` : "not used"}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-text-3">No model provider is configured.</p>
              )}
            </section>

            <section aria-label="Permissions" className="space-y-2" data-trust-permissions>
              <h2 className="font-display text-md font-semibold">What Atlas may do</h2>
              <p className="text-xs text-text-3">
                {open.length} of {data.permissions.length} are on or allowed without asking. Every one of these is checked by Atlas's core at the moment an action runs, so a change here applies to the very next action.
              </p>
              <ul className="space-y-1.5">
                {data.permissions.map((p) => (
                  <li key={p.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-lg border border-line-1 bg-bg-2/70 px-4 py-2.5" data-permission={p.id}>
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-medium text-text-1">{p.name}</span>
                      <span className="block text-xs text-text-3">{p.allows}</span>
                      <span className="mt-0.5 block text-xs text-text-2">
                        {p.status} · {p.component}
                        {p.last_used_at ? ` · last used ${relativeTime(p.last_used_at)}` : ""}
                      </span>
                    </span>
                    <PermissionControl p={p} />
                  </li>
                ))}
              </ul>
            </section>

            <section aria-label="Activity by area" className="space-y-2">
              <h2 className="font-display text-md font-semibold">Activity</h2>
              <Timeline />
            </section>

            <p className="text-xs text-text-3" data-trust-retention>
              {data.retention.events_stored} records kept on this computer (at most {data.retention.max_events.toLocaleString()}
              {data.retention.audit_days ? `, deleted after ${data.retention.audit_days} days` : ""}){data.retention.oldest_event ? `, oldest ${relativeTime(data.retention.oldest_event)}` : ""}. Records hold names, counts and outcomes, never the text of your messages, documents or memories, and never keys.
            </p>
          </>
        )}
        {o.error && !data && <EmptyState icon={<ShieldCheck className="size-5" aria-hidden />} title="The Trust Center could not load" body={String(o.error)} />}
        {data && total === 0 && <p className="flex items-center gap-2 text-xs text-text-3"><Activity className="size-3.5" aria-hidden /> Nothing has been recorded in the last 7 days.</p>}
      </div>
      <ConfirmDialog
        open={clearing}
        onOpenChange={setClearing}
        title="Clear activity history?"
        body={<p>Every activity record on this computer is deleted. This cannot be undone. Atlas records that the history was cleared, so the record never silently disappears. Your conversations, memories and documents are not affected.</p>}
        confirmLabel="Clear history"
        danger
        typeToConfirm="CLEAR"
        onConfirm={async () => {
          try {
            const removed = await api.trustClear(0, "CLEAR");
            toast.success(`Cleared ${removed} records`);
          } catch (e) {
            toast.error(errText(e, "Could not clear the history"));
          }
        }}
      />
    </div>
  );
}
