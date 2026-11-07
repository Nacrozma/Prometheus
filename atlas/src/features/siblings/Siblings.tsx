import { Ban, Cable, CheckCircle2, Eye, Link2, Pause, Play, Plus, RefreshCw, Send, ShieldAlert, Wrench, XCircle } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { Emblem } from "@/components/Emblem";
import { Markdown } from "@/components/Markdown";
import { Badge, Button, EmptyState, ErrorNote, Field, Input, Panel, Segmented, Select, Spinner, Textarea } from "@/components/ui/primitives";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { api, AtlasError } from "@/lib/bridge";
import { cn, formatUsd, relativeTime } from "@/lib/format";
import { useAtlasQuery } from "@/lib/query";
import type { Mission, MissionDetail, MissionEvent, MissionMode, MissionState, Sibling } from "@/lib/schemas";
import { PrometheusAvatar } from "./avatar/PrometheusAvatar";
import type { SolarState } from "./avatar/solarShader";

function err(e: unknown, fallback: string) {
  return e instanceof AtlasError ? e.message : fallback;
}

export const STATE_LABEL: Record<MissionState, string> = {
  DRAFT: "Draft",
  PLANNED: "Planned",
  AWAITING_APPROVAL: "Awaiting your approval",
  RUNNING: "Running",
  REVIEWING: "Ready for your review",
  COMPLETED: "Completed",
  PAUSED: "Paused",
  FAILED: "Failed",
  CANCELLED: "Cancelled",
  NEEDS_USER_INPUT: "Needs your input",
};
const STATE_TONE: Record<MissionState, "neutral" | "accent" | "ok" | "warn" | "err" | "info"> = {
  DRAFT: "neutral",
  PLANNED: "neutral",
  AWAITING_APPROVAL: "warn",
  RUNNING: "accent",
  REVIEWING: "info",
  COMPLETED: "ok",
  PAUSED: "neutral",
  FAILED: "err",
  CANCELLED: "neutral",
  NEEDS_USER_INPUT: "warn",
};
const MODES: { value: MissionMode; label: string; blurb: string }[] = [
  { value: "collaborative", label: "Collaborative", blurb: "Atlas implements (in Forge, with your approvals); Prometheus reviews and proposes changes. The default." },
  { value: "consultation", label: "Consultation", blurb: "Ask Prometheus for advice or a second opinion. One answer; nothing is changed." },
  { value: "delegated", label: "Delegated", blurb: "Prometheus does the work in its own environment with its own tools and its owner's policy. Its dangerous tools stay refused unless its owner allows them." },
];

/** Avatar state from real link/mission state only. */
export function solarStateFor(sibling: Sibling | undefined, mission: Mission | undefined, recentActivity: boolean): SolarState {
  if (!sibling || sibling.status !== "paired" || !sibling.connected) return "offline";
  if (mission?.state === "RUNNING") return recentActivity ? "speaking" : "thinking";
  if (mission?.state === "AWAITING_APPROVAL" || mission?.state === "NEEDS_USER_INPUT") return "idle";
  return "idle";
}

// ---------------- pairing & status ----------------

function PairDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const [endpoint, setEndpoint] = useState("127.0.0.1:47653");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const pair = async () => {
    setBusy(true);
    try {
      const s = await api.pairSibling(endpoint, code);
      toast.success(`Paired with ${s.name}`);
      setCode("");
      onOpenChange(false);
    } catch (e) {
      toast.error(err(e, "Pairing failed"));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Pair with Prometheus"
      description="Prometheus is a separate assistant. Pairing lets the two talk on this computer only."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant="primary" loading={busy} disabled={!code.trim()} onClick={() => void pair()}>Pair</Button>
        </>
      }
    >
      <ol className="mb-4 list-decimal space-y-1 pl-5 text-sm text-text-2">
        <li>In the Prometheus folder, run <code className="font-mono text-text-1">python sibling_adapter.py --pair</code>.</li>
        <li>It prints a one-time code (valid 5 minutes). Type it below.</li>
      </ol>
      <div className="flex flex-col gap-4">
        <Field label="Pairing code" htmlFor="pair-code"><Input id="pair-code" className="font-mono uppercase tracking-widest" placeholder="ABCDE-FGH23" value={code} onChange={(e) => setCode(e.target.value)} autoFocus /></Field>
        <Field label="Address" htmlFor="pair-ep" hint="Only 127.0.0.1 / localhost is accepted: the link never leaves this computer.">
          <Input id="pair-ep" className="font-mono" value={endpoint} onChange={(e) => setEndpoint(e.target.value)} />
        </Field>
      </div>
      <p className="mt-4 text-xs text-text-3">The code never crosses the connection; both sides prove they know it. The shared secret is kept in your system's credential store. Prometheus never receives your API keys, memory or files unless you put them in a mission.</p>
    </Dialog>
  );
}

function Duo({ sibling, mission, activity }: { sibling?: Sibling; mission?: Mission; activity: boolean }) {
  const linked = Boolean(sibling?.connected);
  return (
    <div className="flex items-center justify-center gap-4 py-2" aria-label="Atlas and Prometheus">
      <div className="flex flex-col items-center gap-1">
        <Emblem size={56} glow animated={mission?.state === "RUNNING"} />
        <span className="text-xs font-medium text-accent-strong">Atlas</span>
      </div>
      <div className="relative h-px w-20" aria-hidden>
        <div className={cn("absolute inset-0", linked ? "bg-gradient-to-r from-[color:var(--accent)] to-[#f5a524]" : "border-t border-dashed border-line-3")} />
      </div>
      <div className="flex flex-col items-center gap-1">
        <PrometheusAvatar state={solarStateFor(sibling, mission, activity)} activity={activity ? 0.6 : 0} size={56} />
        <span className="text-xs font-medium text-[#f5b14c]">Prometheus</span>
      </div>
    </div>
  );
}

function SiblingCard({ s }: { s: Sibling }) {
  const [busy, setBusy] = useState(false);
  const [revoke, setRevoke] = useState(false);
  const [caps, setCaps] = useState(false);
  const tools = s.capabilities?.tools ?? [];
  const refresh = async () => {
    setBusy(true);
    try {
      const r = await api.refreshSibling(s.id);
      if (r.connected) toast.success("Health check passed");
      else toast.error(r.last_error ?? "Prometheus did not answer");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Panel className="p-4">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold">{s.name}</p>
          <p className="font-mono text-[0.68rem] text-text-3">{s.endpoint} · {s.id}</p>
        </div>
        {s.status === "revoked" ? <Badge>unpaired</Badge> : s.connected ? <Badge tone="ok">connected</Badge> : <Badge tone="err">not connected</Badge>}
      </div>
      {s.test_peer && <p className="mt-2 rounded-sm bg-warn-soft px-2 py-1 text-xs text-warn">This is the adapter's deterministic test backend, not Prometheus.</p>}
      <dl className="mt-3 grid grid-cols-[6.5rem_1fr] gap-x-2 gap-y-1 text-xs">
        <dt className="text-text-3">Protocol</dt><dd>sibling/1 · adapter {s.adapter_version ?? "?"}</dd>
        <dt className="text-text-3">Version</dt><dd>{s.remote_version ?? "unknown"}</dd>
        <dt className="text-text-3">Last verified</dt><dd>{s.last_seen_at ? relativeTime(s.last_seen_at) : "never"}</dd>
        <dt className="text-text-3">Workload</dt><dd>{s.health?.active_missions ?? 0} active mission(s)</dd>
        <dt className="text-text-3">Its models</dt><dd className="truncate">{s.capabilities?.providers?.join(", ") || "none reported"}</dd>
        {s.last_error && (<><dt className="text-text-3">Error</dt><dd className="text-err">{s.last_error}</dd></>)}
      </dl>
      <div className="mt-3 flex flex-wrap gap-2">
        {s.status === "paired" && <Button size="sm" variant="secondary" icon={<RefreshCw className="size-3.5" />} loading={busy} onClick={() => void refresh()}>Health check</Button>}
        <Button size="sm" variant="ghost" icon={<Eye className="size-3.5" />} onClick={() => setCaps(true)} disabled={!tools.length}>Capabilities ({tools.length})</Button>
        {s.status === "paired" ? (
          <Button size="sm" variant="ghost" className="text-err" icon={<Ban className="size-3.5" />} onClick={() => setRevoke(true)}>Unpair</Button>
        ) : (
          <Button size="sm" variant="ghost" onClick={() => void api.forgetSibling(s.id)}>Forget</Button>
        )}
      </div>
      <Dialog open={caps} onOpenChange={setCaps} title="What Prometheus reported it can do" description="Discovered from Prometheus over the link (CAPABILITIES), not assumed." width="max-w-2xl">
        <p className="mb-2 text-xs text-text-2">Modes: {s.capabilities?.modes?.join(", ") ?? "—"} · Dangerous tools: {s.capabilities?.dangerous_tools_policy === "refused" ? "refused for sibling missions" : "owner confirms each one in Prometheus's terminal"}</p>
        <ul className="divide-y divide-line-1">
          {tools.map((t) => (
            <li key={t.name} className="flex items-start gap-2 py-1.5 text-xs">
              <span className="w-44 shrink-0 font-mono text-text-1">{t.name}</span>
              <span className="min-w-0 flex-1 text-text-3">{t.description}</span>
              {t.dangerous && <Badge tone={t.available_to_siblings ? "warn" : "neutral"}>{t.available_to_siblings ? "dangerous · asks its owner" : "dangerous · refused"}</Badge>}
            </li>
          ))}
        </ul>
      </Dialog>
      <ConfirmDialog
        open={revoke}
        onOpenChange={setRevoke}
        title="Unpair Prometheus?"
        body={<p>Atlas deletes the pairing secret and stops talking to it. Prometheus's owner can also revoke it there with <code>python sibling_adapter.py --revoke {s.id}</code>. Mission history stays in the ledger.</p>}
        confirmLabel="Unpair"
        danger
        onConfirm={async () => {
          await api.revokeSibling(s.id);
        }}
      />
    </Panel>
  );
}

// ---------------- missions ----------------

function NewMissionDialog({ open, onOpenChange, siblings, onCreated }: { open: boolean; onOpenChange: (v: boolean) => void; siblings: Sibling[]; onCreated: (id: string) => void }) {
  const [mode, setMode] = useState<MissionMode>("collaborative");
  const [title, setTitle] = useState("");
  const [objective, setObjective] = useState("");
  const [context, setContext] = useState("");
  const paired = siblings.filter((s) => s.status === "paired");
  const [sib, setSib] = useState<string>("");
  const projects = useAtlasQuery("forge-projects", api.forgeProjects, ["forge"]);
  const [project, setProject] = useState("");
  useEffect(() => {
    if (!sib && paired[0]) setSib(paired[0].id);
  }, [paired, sib]);
  const create = async () => {
    try {
      const m = await api.createMission({ title, mode, objective, sharedContext: context, siblingId: sib || null, forgeProjectId: project || null, conversationId: null });
      onCreated(m.id);
      onOpenChange(false);
      setTitle("");
      setObjective("");
      setContext("");
    } catch (e) {
      toast.error(err(e, "Could not create the mission"));
    }
  };
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="New mission"
      description="A draft stays on this computer until you approve sending it."
      width="max-w-2xl"
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant="primary" disabled={!objective.trim()} onClick={() => void create()}>Create draft</Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <div>
          <Segmented label="Collaboration mode" value={mode} onChange={setMode} options={MODES.map((m) => ({ value: m.value, label: m.label }))} />
          <p className="mt-1.5 text-xs text-text-3">{MODES.find((m) => m.value === mode)?.blurb}</p>
        </div>
        <Field label="Title (optional)" htmlFor="nm-title"><Input id="nm-title" value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
        <Field label="Objective" htmlFor="nm-obj" hint="What you want done and what “done” means."><Textarea id="nm-obj" rows={4} value={objective} onChange={(e) => setObjective(e.target.value)} /></Field>
        <Field label="Context to share (optional)" htmlFor="nm-ctx" hint="Only this text goes to Prometheus with the objective — no memory, files, conversation history or keys. Paste the code or notes it needs.">
          <Textarea id="nm-ctx" rows={5} className="font-mono text-xs" value={context} onChange={(e) => setContext(e.target.value)} />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Sibling" htmlFor="nm-sib">
            <Select id="nm-sib" value={sib} onChange={(e) => setSib(e.target.value)}>
              <option value="">— none paired —</option>
              {paired.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </Select>
          </Field>
          <Field label="Atlas Forge project (optional)" htmlFor="nm-proj" hint="Where Atlas does its side of the work.">
            <Select id="nm-proj" value={project} onChange={(e) => setProject(e.target.value)}>
              <option value="">—</option>
              {projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </Select>
          </Field>
        </div>
      </div>
    </Dialog>
  );
}

type Filter = "all" | "conversation" | "activity" | "system";

function speaker(e: MissionEvent) {
  if (e.source === "prometheus") return { name: "Prometheus", tone: "text-[#f5b14c]" };
  if (e.source === "atlas") return { name: "Atlas", tone: "text-accent-strong" };
  if (e.source === "user") return { name: "You", tone: "text-text-1" };
  return { name: "System", tone: "text-text-3" };
}

function EventRow({ e, sibling, mission }: { e: MissionEvent; sibling?: Sibling; mission: Mission }) {
  const sp = speaker(e);
  if (e.source === "system" || e.kind === "state" || e.kind === "note" || e.kind === "sent") {
    return (
      <li className="flex items-center gap-2 py-1 pl-10 text-[0.72rem] text-text-3">
        <span className="h-px w-3 bg-line-3" aria-hidden />
        {e.content}
        <span className="ml-auto shrink-0">{relativeTime(e.created_at)}</span>
      </li>
    );
  }
  if (e.kind === "tool_request" || e.kind === "tool_result") {
    const parsed = ((): { tool?: string; result?: string } => {
      try {
        return JSON.parse(e.content) as { tool?: string; result?: string };
      } catch {
        return { result: e.content };
      }
    })();
    return (
      <li className="flex items-start gap-2 py-1 pl-10 text-[0.72rem]">
        <Wrench className="mt-0.5 size-3 shrink-0 text-[#f5b14c]" aria-hidden />
        <span className="min-w-0 flex-1 text-text-2">
          <span className="text-text-3">Prometheus {e.kind === "tool_request" ? "requested" : "got result from"}</span> <span className="font-mono text-text-1">{parsed.tool ?? "a tool"}</span>
          {e.kind === "tool_result" && parsed.result && <span className="block truncate font-mono text-text-3">{parsed.result}</span>}
        </span>
      </li>
    );
  }
  return (
    <li className="flex gap-3 py-2.5">
      <div className="mt-0.5 shrink-0">
        {e.source === "prometheus" ? (
          <PrometheusAvatar state={solarStateFor(sibling, mission, false)} size={28} birth={false} />
        ) : e.source === "atlas" ? (
          <Emblem size={28} />
        ) : (
          <div className="grid size-7 place-items-center rounded-full bg-bg-4 text-[0.65rem] font-semibold">You</div>
        )}
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-xs">
          <span className={cn("font-semibold", sp.tone)}>{sp.name}</span>
          <span className="text-text-3"> · {e.kind === "objective" ? "objective" : e.kind === "result" ? "result" : e.kind === "atlas_message" ? "sent to Prometheus" : e.kind}</span>
          <span className="text-text-3"> · {relativeTime(e.created_at)}</span>
        </p>
        <div className={cn("mt-1 rounded-md px-3 py-2 text-sm", e.source === "prometheus" ? "border border-[#f5a524]/20 bg-[#f5a524]/[0.04]" : "bg-bg-2")}>
          {e.source === "prometheus" ? <Markdown text={e.content} /> : <p className="whitespace-pre-wrap">{e.content}</p>}
        </div>
        {e.source === "prometheus" && <p className="mt-1 text-[0.68rem] text-text-3">From a separate assistant — untrusted input. Atlas does not act on it unless you do.</p>}
      </div>
    </li>
  );
}

function MissionView({ id, siblings }: { id: string; siblings: Sibling[] }) {
  const detail = useAtlasQuery<MissionDetail>(`mission:${id}`, () => api.missionDetail(id), ["missions"]);
  const [filter, setFilter] = useState<Filter>("all");
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  const [approve, setApprove] = useState(false);
  const [shared, setShared] = useState(false);
  const lastCount = useRef(0);
  const [activity, setActivity] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);
  const d = detail.data;
  useEffect(() => {
    const n = d?.events.filter((e) => e.source === "prometheus").length ?? 0;
    if (n > lastCount.current && lastCount.current > 0) {
      setActivity(true);
      const t = setTimeout(() => setActivity(false), 3000);
      lastCount.current = n;
      return () => clearTimeout(t);
    }
    lastCount.current = n;
  }, [d?.events]);
  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [d?.events.length]);

  if (detail.error) return <div className="p-6"><ErrorNote message={detail.error.message} onRetry={detail.reload} /></div>;
  if (!d) return <div className="grid flex-1 place-items-center"><Spinner /></div>;
  const m = d.mission;
  const sib = siblings.find((s) => s.id === m.sibling_id);
  const act = async (fn: () => Promise<unknown>, ok?: string) => {
    setBusy(true);
    try {
      await fn();
      if (ok) toast.success(ok);
    } catch (e) {
      toast.error(err(e, "That did not work"));
    } finally {
      setBusy(false);
      detail.reload();
    }
  };
  const visible = d.events.filter((e) => {
    if (filter === "all") return true;
    if (filter === "conversation") return ["objective", "message", "atlas_message", "result", "accepted"].includes(e.kind);
    if (filter === "activity") return e.kind.startsWith("tool_");
    return e.source === "system" || e.kind === "approved" || e.kind === "state";
  });
  const canReply = m.mode === "collaborative" && (m.state === "NEEDS_USER_INPUT" || m.state === "REVIEWING");
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex flex-wrap items-center gap-2 border-b border-line-1 px-5 py-3">
        <div className="min-w-0 flex-1">
          <h2 className="truncate font-display text-sm font-semibold">{m.title}</h2>
          <p className="text-xs text-text-3">{MODES.find((x) => x.value === m.mode)?.label} · {sib?.name ?? "no sibling"} · Atlas-side spend {formatUsd(d.atlas_spend_usd)}</p>
        </div>
        <Badge tone={STATE_TONE[m.state]}>{STATE_LABEL[m.state]}</Badge>
        <Button size="sm" variant="ghost" icon={<Eye className="size-3.5" />} onClick={() => setShared(true)}>What is shared</Button>
      </header>
      <div className="flex flex-wrap items-center gap-2 border-b border-line-1 bg-bg-1/40 px-5 py-2">
        {m.state === "DRAFT" && <Button size="sm" variant="secondary" loading={busy} onClick={() => void act(() => api.missionTransition(m.id, "PLANNED"))}>Mark as planned</Button>}
        {m.state === "PLANNED" && (
          <>
            <Button size="sm" variant="primary" icon={<ShieldAlert className="size-3.5" />} loading={busy} onClick={() => void act(() => api.missionTransition(m.id, "AWAITING_APPROVAL"))}>Review & approve sending</Button>
            <Button size="sm" variant="ghost" onClick={() => void act(() => api.missionTransition(m.id, "DRAFT"))}>Back to draft</Button>
          </>
        )}
        {m.state === "AWAITING_APPROVAL" && (
          <>
            <Button size="sm" variant="primary" icon={<Send className="size-3.5" />} loading={busy} onClick={() => setApprove(true)}>{m.sent_at ? "Retry sending (checks first)" : "Approve & send to Prometheus"}</Button>
            <Button size="sm" variant="ghost" onClick={() => void act(() => api.missionTransition(m.id, "PLANNED"))}>Not now</Button>
          </>
        )}
        {(m.state === "RUNNING" || m.state === "NEEDS_USER_INPUT") && <Button size="sm" variant="ghost" icon={<Pause className="size-3.5" />} onClick={() => void act(() => api.missionTransition(m.id, "PAUSED"))}>Pause updates</Button>}
        {m.state === "PAUSED" && <Button size="sm" variant="secondary" icon={<Play className="size-3.5" />} onClick={() => void act(() => api.missionTransition(m.id, "RUNNING"))}>Resume</Button>}
        {(m.state === "REVIEWING" || m.state === "NEEDS_USER_INPUT") && m.sent_at && (
          <Button size="sm" variant="secondary" icon={<CheckCircle2 className="size-3.5" />} loading={busy} onClick={() => void act(() => api.acceptMission(m.id, ""), "Mission completed")}>Accept result</Button>
        )}
        {m.sent_at && !["COMPLETED", "FAILED", "CANCELLED"].includes(m.state) && <Button size="sm" variant="ghost" icon={<RefreshCw className="size-3.5" />} onClick={() => void act(() => api.syncMission(m.id))}>Check now</Button>}
        {!["COMPLETED", "FAILED", "CANCELLED"].includes(m.state) && <Button size="sm" variant="ghost" className="ml-auto text-err" icon={<XCircle className="size-3.5" />} onClick={() => void act(() => api.cancelMission(m.id), "Mission cancelled")}>Cancel mission</Button>}
      </div>
      {m.last_error && <p className="border-b border-line-1 bg-err-soft px-5 py-1.5 text-xs text-err">Last attempt: {m.last_error}</p>}
      <div className="flex items-center gap-3 px-5 pt-3">
        <Duo sibling={sib} mission={m} activity={activity} />
        <div className="ml-auto">
          <Segmented label="Timeline filter" value={filter} onChange={setFilter} options={[{ value: "all", label: "All" }, { value: "conversation", label: "Conversation" }, { value: "activity", label: "Activity" }, { value: "system", label: "Approvals & system" }]} />
        </div>
      </div>
      <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto px-5 pb-4">
        <ol className="flex flex-col" aria-label="Mission timeline">
          {visible.map((e) => <EventRow key={e.id} e={e} sibling={sib} mission={m} />)}
        </ol>
        {m.state === "REVIEWING" && m.result_summary && (
          <Panel className="mt-3 border-[color:var(--info)]/30 p-4">
            <p className="text-xs font-semibold text-info">Result reported by Prometheus — check it before accepting</p>
            <div className="mt-2 text-sm"><Markdown text={m.result_summary} /></div>
          </Panel>
        )}
      </div>
      {canReply && (
        <form
          className="flex gap-2 border-t border-line-1 p-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (reply.trim()) void act(() => api.missionMessage(m.id, reply)).then(() => setReply(""));
          }}
        >
          <Textarea aria-label="Reply to Prometheus" rows={2} className="flex-1" placeholder={m.state === "REVIEWING" ? "Ask for changes…" : "Reply to Prometheus (only this text is sent)"} value={reply} onChange={(e) => setReply(e.target.value)} />
          <Button type="submit" variant="primary" icon={<Send className="size-4" />} loading={busy} disabled={!reply.trim()}>Send</Button>
        </form>
      )}
      <ConfirmDialog
        open={approve}
        onOpenChange={setApprove}
        title="Send this mission to Prometheus?"
        body={
          <div className="space-y-2 text-sm">
            <p>Exactly this leaves Atlas (to {sib?.name ?? "the sibling"} on this computer):</p>
            <pre className="max-h-64 overflow-auto rounded-md bg-bg-0 p-2 font-mono text-[0.7rem]">{JSON.stringify(d.outgoing, null, 2)}</pre>
            <p className="text-xs text-text-3">No memory, files, conversation history or API keys are included. A retry never starts the mission twice.</p>
          </div>
        }
        confirmLabel="Approve & send"
        onConfirm={() => act(() => api.sendMission(m.id), "Sent to Prometheus")}
      />
      <Dialog open={shared} onOpenChange={setShared} title="Shared with Prometheus" description={m.sent_at ? `Sent ${relativeTime(m.sent_at)}` : "Not sent yet — this is what would be sent."} width="max-w-2xl">
        <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap rounded-md bg-bg-0 p-3 font-mono text-xs">{JSON.stringify(d.outgoing, null, 2)}</pre>
        <p className="mt-2 text-xs text-text-3">Plus any replies you typed in this mission (shown in the timeline as “sent to Prometheus”).</p>
      </Dialog>
    </div>
  );
}

export function SiblingsPage() {
  const siblings = useAtlasQuery("siblings", api.siblings, ["siblings"]);
  const missions = useAtlasQuery("missions", api.missions, ["missions"]);
  const [pairOpen, setPairOpen] = useState(false);
  const [newOpen, setNewOpen] = useState(false);
  const [active, setActive] = useState<string | null>(null);
  const list = useMemo(() => missions.data ?? [], [missions.data]);
  useEffect(() => {
    if (!active && list[0]) setActive(list[0].id);
  }, [list, active]);
  const sibs = siblings.data ?? [];
  const paired = sibs.filter((s) => s.status === "paired");
  if (siblings.error) return <div className="p-8"><ErrorNote message={siblings.error.message} onRetry={siblings.reload} /></div>;
  return (
    <div className="flex h-full min-h-0">
      <aside className="flex w-80 shrink-0 flex-col gap-3 overflow-y-auto border-r border-line-1 p-4" aria-label="Siblings">
        <div className="flex items-center gap-2">
          <h1 className="flex-1 font-display text-base font-semibold">Siblings</h1>
          <Button size="sm" variant="secondary" icon={<Link2 className="size-3.5" />} onClick={() => setPairOpen(true)}>Pair</Button>
        </div>
        {sibs.length === 0 ? (
          <div className="rounded-lg border border-line-1 bg-bg-2/60 p-4 text-center">
            <PrometheusAvatar state="offline" size={72} className="mx-auto" />
            <p className="mt-3 text-sm font-medium">No sibling paired</p>
            <p className="mt-1 text-xs text-text-3">Prometheus is a separate engineering assistant. Atlas works fully without it; pairing adds consultation and shared missions.</p>
            <Button className="mt-3" size="sm" variant="primary" icon={<Cable className="size-3.5" />} onClick={() => setPairOpen(true)}>Pair with Prometheus</Button>
          </div>
        ) : (
          sibs.map((s) => <SiblingCard key={s.id} s={s} />)
        )}
        <div className="mt-2 flex items-center gap-2">
          <h2 className="flex-1 text-xs font-semibold uppercase tracking-wider text-text-3">Missions</h2>
          <Button size="sm" variant="ghost" icon={<Plus className="size-3.5" />} onClick={() => setNewOpen(true)}>New</Button>
        </div>
        <ul className="flex flex-col gap-1">
          {list.length === 0 && <li className="text-xs text-text-3">No missions yet.</li>}
          {list.map((m) => (
            <li key={m.id}>
              <button onClick={() => setActive(m.id)} aria-current={active === m.id ? "true" : undefined} className={cn("w-full rounded-md px-2.5 py-2 text-left hover:bg-bg-3", active === m.id && "bg-bg-3")}>
                <span className="block truncate text-sm">{m.title}</span>
                <span className="flex items-center gap-2 text-[0.68rem] text-text-3">
                  <Badge tone={STATE_TONE[m.state]}>{STATE_LABEL[m.state]}</Badge> {m.mode} · {relativeTime(m.updated_at)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </aside>
      <section className="flex min-w-0 flex-1 flex-col" aria-label="Sibling collaboration">
        {active ? (
          <MissionView key={active} id={active} siblings={sibs} />
        ) : (
          <EmptyState
            icon={<Cable className="size-5" aria-hidden />}
            title="Sibling collaboration"
            body={paired.length ? "Create a mission to consult Prometheus or work on something together. Every message here is real and recorded in the mission ledger." : "Pair with Prometheus first, or keep using Atlas on its own — nothing here is required."}
            action={<Button variant="primary" onClick={() => (paired.length ? setNewOpen(true) : setPairOpen(true))}>{paired.length ? "New mission" : "Pair with Prometheus"}</Button>}
          />
        )}
      </section>
      <PairDialog open={pairOpen} onOpenChange={setPairOpen} />
      <NewMissionDialog open={newOpen} onOpenChange={setNewOpen} siblings={sibs} onCreated={(id) => setActive(id)} />
    </div>
  );
}
