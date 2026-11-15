import { CheckCircle2, CircleSlash, Cloud, Cpu, Loader2, Play, ShieldAlert, Square, Users, XCircle } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Badge, Button, EmptyState, Field, PageHeader, Panel, Select, Skeleton, Switch, Textarea, type Tone } from "@/components/ui/primitives";
import { api, AtlasError } from "@/lib/bridge";
import { cn, formatUsd, relativeTime } from "@/lib/format";
import { useAtlasQuery } from "@/lib/query";
import type { SpecialistMission as Mission, MissionStep, SpecialistsOverview } from "@/lib/schemas";
import { useUi } from "@/state/ui";

const errText = (e: unknown, fallback: string) => (e instanceof AtlasError ? e.message : fallback);

const MISSION_STATUS: Record<Mission["status"], { label: string; tone: Tone }> = {
  queued: { label: "Preparing", tone: "accent" },
  running: { label: "Running", tone: "accent" },
  completed: { label: "Completed", tone: "ok" },
  partial: { label: "Partly completed", tone: "warn" },
  failed: { label: "Failed", tone: "err" },
  cancelled: { label: "Cancelled", tone: "neutral" },
  interrupted: { label: "Interrupted", tone: "warn" },
};

/** Progress in words, only from what the core reports for the step. */
export function stepState(s: MissionStep): string {
  if (s.status === "running") return s.awaiting_approval ? "Awaiting your approval" : "Running";
  return { pending: "Waiting", completed: "Completed", failed: "Failed", invalid_output: "Returned an invalid result", cancelled: "Cancelled", skipped: "Skipped", interrupted: "Interrupted" }[s.status] ?? s.status;
}

/** What a step was given, in words (from its recorded context manifest). */
export function contextWords(m: Record<string, unknown> | null): string[] {
  if (!m) return [];
  const out: string[] = [];
  if (Array.isArray(m.previous_results) && m.previous_results.length) out.push("earlier results");
  if (Array.isArray(m.memories) && m.memories.length) out.push(`${m.memories.length} relevant ${m.memories.length === 1 ? "memory" : "memories"}`);
  if (Array.isArray(m.vault_documents)) out.push(`passages from ${(m.vault_documents as string[]).join(", ")}`);
  if (typeof m.vault_withheld === "number") out.push("document passages withheld (local-only)");
  if (typeof m.tasks === "number") out.push(`${m.tasks} open tasks`);
  if (typeof m.projects === "number") out.push(`${m.projects} projects`);
  if (typeof m.forge_project === "string") out.push("a Forge project");
  if (Array.isArray(m.files_changed)) out.push(`changed ${(m.files_changed as string[]).join(", ")}`);
  return out;
}

function StepCard({ s, name }: { s: MissionStep; name: string }) {
  const r = s.result;
  const ctx = contextWords(s.context_manifest as Record<string, unknown> | null);
  const icon =
    s.status === "completed" ? <CheckCircle2 className="size-4 text-ok" aria-hidden /> : s.status === "running" ? <Loader2 className="size-4 animate-spin text-accent" aria-hidden /> : s.status === "pending" ? <span className="size-4 rounded-full border border-line-2" aria-hidden /> : s.status === "cancelled" || s.status === "skipped" ? <CircleSlash className="size-4 text-text-3" aria-hidden /> : <XCircle className="size-4 text-err" aria-hidden />;
  return (
    <li className="rounded-lg border border-line-1 bg-bg-3/40 px-3 py-2.5" data-step={s.specialist_id} data-step-status={s.status}>
      <p className="flex flex-wrap items-center gap-2 text-sm">
        {icon}
        <span className="font-medium text-text-1">{name}</span>
        <span className={cn("text-xs", s.awaiting_approval ? "text-warn" : "text-text-3")}>{stepState(s)}</span>
        {s.provider && (
          <span className="ml-auto flex items-center gap-1 text-xs text-text-3">
            {s.local ? <Cpu className="size-3.5" aria-hidden /> : <Cloud className="size-3.5 text-accent" aria-hidden />}
            {s.provider}
            {s.model ? ` · ${s.model}` : ""}
            {s.input_tokens != null && s.input_tokens + (s.output_tokens ?? 0) > 0 ? ` · ${s.input_tokens + (s.output_tokens ?? 0)} tokens` : ""}
            {!s.local && s.estimated_cost_usd != null ? ` · ${formatUsd(s.estimated_cost_usd)} est.` : ""}
          </span>
        )}
      </p>
      {ctx.length > 0 && <p className="mt-1 text-xs text-text-3">Given: {ctx.join(" · ")}</p>}
      {s.error && <p className="mt-1 text-xs text-err">{s.error}</p>}
      {r && (
        <div className="mt-2 space-y-1.5 text-sm" data-step-result>
          <p className="text-text-1">{r.summary}</p>
          {r.findings.length > 0 && (
            <ul className="list-disc space-y-0.5 pl-5 text-text-2">
              {r.findings.map((f, i) => (
                <li key={i} className="whitespace-pre-wrap">{f}</li>
              ))}
            </ul>
          )}
          {r.evidence.length > 0 && (
            <p className="text-xs text-text-3">
              Evidence: {r.evidence.map((e) => e.source).join(" · ")}
            </p>
          )}
          {r.recommendations.length > 0 && <p className="text-xs text-text-2">Recommends: {r.recommendations.join("; ")}</p>}
          {r.uncertainties.length > 0 && <p className="text-xs text-text-3">Uncertain: {r.uncertainties.join("; ")}</p>}
          {r.warnings.length > 0 && (
            <p className="flex items-start gap-1 text-xs text-warn">
              <ShieldAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden /> {r.warnings.join("; ")}
            </p>
          )}
          {r.disagreements.length > 0 && <p className="text-xs text-warn">Disagrees with an earlier specialist: {r.disagreements.join("; ")}</p>}
          {r.proposed_actions.length > 0 && <p className="text-xs text-text-2">Proposed (not done): {r.proposed_actions.join("; ")}</p>}
        </div>
      )}
    </li>
  );
}

function MissionCard({ m, names }: { m: Mission; names: Record<string, string> }) {
  const st = MISSION_STATUS[m.status];
  const open = useUi((u) => u.openConversation);
  const active = m.status === "queued" || m.status === "running";
  return (
    <li className="rounded-lg border border-line-2 bg-bg-2/70 px-4 py-3" data-mission={m.title} data-mission-status={m.status}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-sm font-medium text-text-1">{m.title}</span>
        <Badge tone={st.tone}>{st.label}</Badge>
        {active && (
          <Button
            size="sm"
            variant="ghost"
            icon={<Square className="size-3.5" aria-hidden />}
            onClick={async () => {
              try {
                await api.cancelSpecialistMission(m.id);
              } catch (e) {
                toast.error(errText(e, "Could not cancel"));
              }
            }}
          >
            Cancel
          </Button>
        )}
      </div>
      <p className="mt-0.5 text-xs text-text-3">
        {m.workflow.map((w) => names[w] ?? w).join(" → ")} · {m.origin === "atlas" ? "started by Atlas in a conversation" : "started by you"} · {relativeTime(m.created_at)}
        {m.conversation_id && (
          <button type="button" className="ml-2 text-accent hover:underline" onClick={() => open(m.conversation_id)}>
            open conversation
          </button>
        )}
      </p>
      <ol className="mt-2 space-y-1.5">
        {m.steps.map((s) => (
          <StepCard key={s.id} s={s} name={names[s.specialist_id] ?? s.specialist_id} />
        ))}
      </ol>
      {m.status === "partial" && <p className="mt-2 text-xs text-warn">Some specialists did not finish; the results above are what they did produce.</p>}
    </li>
  );
}

function NewMission({ data }: { data: SpecialistsOverview }) {
  const projects = useAtlasQuery("projects", () => api.projects(false), ["projects"]);
  const forge = useAtlasQuery("forge-projects", api.forgeProjects, ["forge"]);
  const [team, setTeam] = useState("research_report");
  const [objective, setObjective] = useState("");
  const [project, setProject] = useState("");
  const [forgeId, setForgeId] = useState("");
  const [busy, setBusy] = useState(false);
  const steps = data.workflows.find((w) => w.id === team)?.steps ?? [team];
  const needsForge = steps.some((s) => data.specialists.find((x) => x.specialist.id === s)?.specialist.forge);
  const enabledIds = new Set(data.specialists.filter((s) => s.enabled).map((s) => s.specialist.id));
  const blocked = steps.filter((s) => !enabledIds.has(s));
  return (
    <Panel className="space-y-3 p-4" data-new-mission>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Who works on it" htmlFor="mission-team">
          <Select id="mission-team" value={team} onChange={(e) => setTeam(e.target.value)}>
            <optgroup label="Teams (in order)">
              {data.workflows.map((w) => (
                <option key={w.id} value={w.id}>
                  {w.name}
                </option>
              ))}
            </optgroup>
            <optgroup label="One specialist">
              {data.specialists.map((s) => (
                <option key={s.specialist.id} value={s.specialist.id}>
                  {s.specialist.name}
                </option>
              ))}
            </optgroup>
          </Select>
        </Field>
        <Field label="Project (scopes documents and tasks)" htmlFor="mission-project">
          <Select id="mission-project" value={project} onChange={(e) => setProject(e.target.value)}>
            <option value="">No project</option>
            {(projects.data ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </Select>
        </Field>
      </div>
      {needsForge && (
        <Field label="Atlas Forge project" htmlFor="mission-forge" hint="Engineering specialists work only inside a Forge project; edits and test runs ask you first.">
          <Select id="mission-forge" value={forgeId} onChange={(e) => setForgeId(e.target.value)}>
            <option value="">Choose a project…</option>
            {(forge.data ?? []).map((f) => (
              <option key={f.id} value={f.id}>
                {f.name}
              </option>
            ))}
          </Select>
        </Field>
      )}
      <Field label="Objective" htmlFor="mission-objective">
        <Textarea id="mission-objective" rows={3} value={objective} maxLength={4000} onChange={(e) => setObjective(e.target.value)} placeholder="What should they work on? Be specific." />
      </Field>
      <div className="flex flex-wrap items-center gap-3">
        <Button
          variant="primary"
          icon={<Play className="size-4" aria-hidden />}
          loading={busy}
          disabled={objective.trim().length < 3 || (needsForge && !forgeId) || blocked.length > 0 || !data.enabled}
          onClick={async () => {
            setBusy(true);
            try {
              await api.startSpecialistMission(objective, steps, project || null, needsForge ? forgeId : null);
              setObjective("");
              toast.success("Mission started");
            } catch (e) {
              toast.error(errText(e, "The mission could not start"));
            } finally {
              setBusy(false);
            }
          }}
        >
          Start mission
        </Button>
        <p className="text-xs text-text-3">
          {blocked.length ? `Switched off: ${blocked.join(", ")}.` : "Each specialist gets only the context it needs; anything that changes files or uses the internet asks you first, and runs on the model your routing picks."}
        </p>
      </div>
    </Panel>
  );
}

export function SpecialistsPage() {
  const o = useAtlasQuery("specialists", api.specialistsOverview, ["specialists", "approvals", "tasks"]);
  const settings = useAtlasQuery("settings", api.settings, ["settings"]);
  const data = o.data;
  const names = Object.fromEntries((data?.specialists ?? []).map((s) => [s.specialist.id, s.specialist.name]));
  return (
    <div className="h-full overflow-y-auto">
      <PageHeader eyebrow="Your team" title="Specialists" subtitle="Focused capabilities Atlas can bring in for research, plans, writing, data, your documents, projects, security and code. Atlas stays in charge: it picks them, gives them only what they need, and reviews what they produce." />
      <div className="space-y-6 px-8 py-6" data-specialists>
        {!data ? (
          <Skeleton className="h-40" />
        ) : (
          <>
            <Panel className="flex flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3 text-sm">
              <label className="flex items-center gap-2">
                <Switch
                  checked={data.enabled}
                  label="Atlas may consult specialists"
                  onChange={async (v) => {
                    if (settings.data) await api.updateSettings({ ...settings.data, specialists: { enabled: v } });
                  }}
                />
                Atlas may consult specialists in conversations
              </label>
              <p className="min-w-64 flex-1 text-xs text-text-3">Every specialist action follows the same permissions and approvals as Atlas and appears in the Trust Center.</p>
            </Panel>

            <section aria-label="Start a mission" className="space-y-2">
              <h2 className="font-display text-md font-semibold">Start a mission</h2>
              <NewMission data={data} />
            </section>

            <section aria-label="Missions" className="space-y-2" data-missions>
              <h2 className="font-display text-md font-semibold">Missions</h2>
              {data.missions.length ? (
                <ul className="space-y-2">
                  {data.missions.map((m) => (
                    <MissionCard key={m.id} m={m} names={names} />
                  ))}
                </ul>
              ) : (
                <EmptyState icon={<Users className="size-5" aria-hidden />} title="No missions yet" body="Start one above, or ask Atlas for focused work in a conversation: it will bring in the right specialist when it helps." />
              )}
            </section>

            <section aria-label="The team" className="space-y-2" data-team>
              <h2 className="font-display text-md font-semibold">The team</h2>
              <ul className="grid gap-2 lg:grid-cols-2">
                {data.specialists.map(({ specialist: s, enabled, tools }) => (
                  <li key={s.id} className={cn("rounded-lg border border-line-1 bg-bg-2/70 px-4 py-3", !enabled && "opacity-60")} data-specialist={s.id}>
                    <div className="flex items-center gap-2">
                      <span className="flex-1 text-sm font-medium text-text-1">{s.name}</span>
                      <Badge>{s.domain}</Badge>
                      <Switch checked={enabled} label={`${s.name} available`} onChange={async (v) => { try { await api.setSpecialistEnabled(s.id, v); } catch (e) { toast.error(errText(e, "Could not change")); } }} />
                    </div>
                    <p className="mt-1 text-xs text-text-2">{s.summary}</p>
                    <p className="mt-1 text-xs text-text-3">Needs: {s.needs}</p>
                    <p className="mt-1 text-xs text-text-3">
                      Tools: {tools.length ? tools.map((t) => `${t.id}${t.permission && t.permission !== "read_only" ? " (asks first)" : ""}${t.network ? " (internet)" : ""}${!t.registered ? " (unavailable)" : ""}`).join(", ") : "none: it works only from what it is given"}
                    </p>
                    <p className="mt-1 text-xs text-text-3">
                      Given: {[s.memories ? `up to ${s.memories} relevant memories` : null, s.vault_passages ? `up to ${s.vault_passages} document passages` : null, s.tasks ? "open tasks" : null, s.projects ? "project records" : null, s.forge ? `a Forge project (${s.forge === "architect" ? "read-only" : "can propose edits"})` : null].filter(Boolean).join(", ") || "only the objective and earlier results"}
                      {` · v${s.version} · ${s.tier_hint} work · up to ${s.max_steps} steps`}
                    </p>
                  </li>
                ))}
              </ul>
            </section>
          </>
        )}
      </div>
    </div>
  );
}
