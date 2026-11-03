import { Copy, Download, FileDown, HardDriveDownload, KeyRound, RotateCcw, ShieldCheck } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { applyAppearance } from "@/app/App";
import { ConfirmDialog } from "@/components/ui/dialog";
import { Badge, Button, ErrorNote, Input, Kbd, Panel, Segmented, Select, Skeleton, StatusPill, Switch } from "@/components/ui/primitives";
import { api, AtlasError } from "@/lib/bridge";
import { cn, formatTokens, formatUsd, permissionLabel, relativeTime } from "@/lib/format";
import { useAtlasQuery } from "@/lib/query";
import type { Settings } from "@/lib/schemas";
import { useUi, type SettingsSection } from "@/state/ui";

const SECTIONS: { id: SettingsSection; label: string }[] = [
  { id: "companion", label: "Companion" },
  { id: "models", label: "Models & routing" },
  { id: "permissions", label: "Permissions" },
  { id: "memory", label: "Memory" },
  { id: "appearance", label: "Appearance" },
  { id: "files", label: "File workspace" },
  { id: "limits", label: "Limits & network" },
  { id: "usage", label: "Usage & costs" },
  { id: "data", label: "Data & privacy" },
  { id: "diagnostics", label: "Diagnostics" },
  { id: "shortcuts", label: "Shortcuts" },
  { id: "about", label: "About" },
];

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

function NumberInput({ value, onCommit, min, max, label, nullable, step = 1 }: { value: number | null; onCommit: (v: number | null) => void; min: number; max: number; label: string; nullable?: boolean; step?: number }) {
  const [v, setV] = useState(value == null ? "" : String(value));
  useEffect(() => setV(value == null ? "" : String(value)), [value]);
  return (
    <Input
      aria-label={label}
      type="number"
      min={min}
      max={max}
      step={step}
      value={v}
      placeholder={nullable ? "No limit" : undefined}
      onChange={(e) => setV(e.target.value)}
      onBlur={() => {
        if (v === "" && nullable) return onCommit(null);
        const n = Number(v);
        if (!Number.isFinite(n) || n < min || n > max) {
          toast.error(`${label} must be between ${min} and ${max}`);
          setV(value == null ? "" : String(value));
          return;
        }
        if (n !== value) onCommit(n);
      }}
      className="w-32 text-right"
    />
  );
}

export function SettingsPage() {
  const section = useUi((s) => s.settingsSection);
  const open = useUi((s) => s.openSettings);
  const settings = useAtlasQuery("settings", api.settings, ["settings"]);

  const save = async (next: Settings) => {
    try {
      const saved = await api.updateSettings(next);
      applyAppearance(saved);
      settings.reload();
    } catch (e) {
      toast.error(e instanceof AtlasError ? e.message : String(e));
      settings.reload();
    }
  };

  return (
    <div className="flex h-full">
      <nav aria-label="Settings sections" className="w-56 shrink-0 overflow-y-auto border-r border-line-1 px-3 py-6">
        <p className="px-3 pb-3 font-display text-lg font-semibold">Settings</p>
        <ul className="space-y-0.5">
          {SECTIONS.map((s) => (
            <li key={s.id}>
              <button
                onClick={() => open(s.id)}
                aria-current={section === s.id ? "page" : undefined}
                className={cn("w-full rounded-md px-3 py-1.5 text-left text-sm", section === s.id ? "bg-bg-4 text-text-1" : "text-text-2 hover:bg-bg-3 hover:text-text-1")}
              >
                {s.label}
              </button>
            </li>
          ))}
        </ul>
      </nav>
      <div className="min-w-0 flex-1 overflow-y-auto px-10 py-8">
        <div key={section} className="mx-auto max-w-3xl anim-fade">
          <h1 className="mb-1 font-display text-xl font-semibold">{SECTIONS.find((s) => s.id === section)?.label}</h1>
          {settings.error ? (
            <ErrorNote message={settings.error.message} onRetry={settings.reload} />
          ) : !settings.data ? (
            <Skeleton className="mt-6 h-64" />
          ) : (
            <Section id={section} s={settings.data} save={save} />
          )}
        </div>
      </div>
    </div>
  );
}

function Section({ id, s, save }: { id: SettingsSection; s: Settings; save: (n: Settings) => Promise<void> }) {
  switch (id) {
    case "companion":
      return <CompanionSection s={s} save={save} />;
    case "models":
      return <ModelsSection s={s} save={save} />;
    case "permissions":
      return <PermissionsSection s={s} save={save} />;
    case "memory":
      return (
        <Panel className="mt-6 px-5">
          <Row title="Use memory" desc="When off, no memories are sent with requests and Atlas cannot save new ones.">
            <Switch checked={s.memory.enabled} label="Use memory" onChange={(v) => save({ ...s, memory: { ...s.memory, enabled: v } })} />
          </Row>
          <Row title="Memories per request" desc="The most relevant memories (plus pinned ones) attached to a message. 0 disables retrieval.">
            <NumberInput label="Memories per request" value={s.memory.max_retrieved} min={0} max={20} onCommit={(v) => save({ ...s, memory: { ...s.memory, max_retrieved: v ?? 0 } })} />
          </Row>
          <Row title="Manage memories" desc="Browse, edit, export or delete everything Atlas remembers.">
            <Button onClick={() => useUi.getState().navigate("memory")}>Open Memory</Button>
          </Row>
        </Panel>
      );
    case "appearance":
      return (
        <Panel className="mt-6 px-5">
          <Row title="Theme">
            <Segmented label="Theme" value={s.appearance.theme} onChange={(theme) => save({ ...s, appearance: { ...s.appearance, theme } })} options={[{ value: "dark", label: "Deep Orbit" }, { value: "light", label: "Daylight" }, { value: "system", label: "System" }]} />
          </Row>
          <Row title="Motion" desc="“System” follows your operating system's reduced-motion preference.">
            <Segmented label="Motion" value={s.appearance.motion} onChange={(motion) => save({ ...s, appearance: { ...s.appearance, motion } })} options={[{ value: "system", label: "System" }, { value: "reduced", label: "Reduced" }, { value: "full", label: "Full" }]} />
          </Row>
          <Row title="Text size" desc={`${s.appearance.font_scale}%`}>
            <input
              type="range"
              aria-label="Text size"
              min={85}
              max={130}
              step={5}
              value={s.appearance.font_scale}
              onChange={(e) => save({ ...s, appearance: { ...s.appearance, font_scale: Number(e.target.value) } })}
              className="w-48 accent-[color:var(--accent)]"
            />
          </Row>
        </Panel>
      );
    case "files":
      return (
        <Panel className="mt-6 px-5">
          <Row title="Workspace folder" desc={s.workspace_dir ? <span className="break-all font-mono">{s.workspace_dir}</span> : "Not chosen — file tools are unavailable."}>
            <Button onClick={async () => { try { await api.pickWorkspace(); } catch (e) { toast.error(e instanceof AtlasError ? e.message : String(e)); } }}>{s.workspace_dir ? "Change…" : "Choose…"}</Button>
          </Row>
          <Row title="Creating files" desc="Configured under Permissions → Local writes.">
            <Badge tone={s.permissions.local_write === "ask" ? "warn" : "ok"}>{s.permissions.local_write === "ask" ? "Asks first" : "Allowed"}</Badge>
          </Row>
          <Row title="Shared files" desc="Individual files outside the workspace that you shared.">
            <Button onClick={() => useUi.getState().navigate("files")}>Manage</Button>
          </Row>
        </Panel>
      );
    case "limits":
      return <LimitsSection s={s} save={save} />;
    case "usage":
      return <UsageSection s={s} save={save} />;
    case "data":
      return <DataSection s={s} save={save} />;
    case "diagnostics":
      return <DiagnosticsSection />;
    case "shortcuts":
      return (
        <Panel className="mt-6 px-5">
          {[
            ["Command palette", ["Ctrl", "K"]],
            ["New conversation", ["Ctrl", "N"]],
            ["Go to section 1–9", ["Ctrl", "1…9"]],
            ["Settings", ["Ctrl", ","]],
            ["Send message", ["Enter"]],
            ["New line in message", ["Shift", "Enter"]],
            ["Search the map", ["Enter in map search"]],
          ].map(([label, keys]) => (
            <Row key={label as string} title={label as string}>
              <span className="flex gap-1">{(keys as string[]).map((k) => <Kbd key={k}>{k}</Kbd>)}</span>
            </Row>
          ))}
          <p className="py-3 text-xs text-text-3">On macOS, use ⌘ in place of Ctrl.</p>
        </Panel>
      );
    case "about":
      return <AboutSection />;
  }
}

function CompanionSection({ s, save }: { s: Settings; save: (n: Settings) => Promise<void> }) {
  const [name, setName] = useState(s.companion.preferred_name);
  const projects = useAtlasQuery("projects", () => api.projects(false), ["projects"]);
  const c = s.companion;
  const set = (patch: Partial<Settings["companion"]>) => save({ ...s, companion: { ...c, ...patch } });
  return (
    <Panel className="mt-6 px-5">
      <Row title="Your name" desc="How Atlas addresses you. Leave empty to skip.">
        <Input aria-label="Your name" value={name} maxLength={60} onChange={(e) => setName(e.target.value)} onBlur={() => name !== c.preferred_name && set({ preferred_name: name })} className="w-56" />
      </Row>
      <Row title="Tone">
        <Segmented label="Tone" value={c.tone} onChange={(tone) => set({ tone })} options={[{ value: "warm", label: "Warm" }, { value: "balanced", label: "Balanced" }, { value: "precise", label: "Precise" }]} />
      </Row>
      <Row title="Response length">
        <Segmented label="Response length" value={c.verbosity} onChange={(verbosity) => set({ verbosity })} options={[{ value: "concise", label: "Concise" }, { value: "balanced", label: "Balanced" }, { value: "detailed", label: "Detailed" }]} />
      </Row>
      <Row title="Initiative" desc="How readily Atlas suggests next steps.">
        <Segmented label="Initiative" value={c.proactivity} onChange={(proactivity) => set({ proactivity })} options={[{ value: "reserved", label: "Reserved" }, { value: "balanced", label: "Balanced" }, { value: "proactive", label: "Proactive" }]} />
      </Row>
      <Row title="Reasoning effort" desc="Sent only to models that support it. Higher effort is slower and uses more tokens.">
        <Segmented label="Reasoning effort" value={c.effort} onChange={(effort) => set({ effort })} options={[{ value: "low", label: "Low" }, { value: "medium", label: "Medium" }, { value: "high", label: "High" }]} />
      </Row>
      <Row title="Show reasoning summaries" desc="When the model provides a summary of its reasoning, show it in a collapsed panel.">
        <Switch checked={c.show_reasoning_summary} label="Show reasoning summaries" onChange={(v) => set({ show_reasoning_summary: v })} />
      </Row>
      <Row title="Default project for new conversations">
        <Select aria-label="Default project" value={s.default_project_id ?? ""} onChange={(e) => save({ ...s, default_project_id: e.target.value || null })} className="w-56">
          <option value="">None</option>
          {(projects.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </Select>
      </Row>
    </Panel>
  );
}

function ModelsSection({ s, save }: { s: Settings; save: (n: Settings) => Promise<void> }) {
  const providers = useAtlasQuery("providers", api.providers, ["providers"]);
  const def = providers.data?.find((p) => p.id === s.default_provider_id);
  return (
    <>
      <Panel className="mt-6 px-5">
        <Row title="Default provider" desc="Used for new messages unless you pick another model in the conversation.">
          <Select aria-label="Default provider" value={s.default_provider_id ?? ""} onChange={(e) => save({ ...s, default_provider_id: e.target.value || null })} className="w-60">
            <option value="">—</option>
            {(providers.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
          </Select>
        </Row>
        <Row title="Default model" desc="Each provider's own default model is set in Integrations.">
          <span className="font-mono text-xs text-text-2">{def?.default_model ?? "—"}</span>
        </Row>
      </Panel>
      <h2 className="mb-2 mt-8 text-sm font-semibold text-text-2">Routing &amp; fallback</h2>
      <Panel className="px-5">
        <Row
          title="Fall back to another provider"
          desc="If your default provider is unavailable, use another configured provider. Off by default because it changes who receives your messages. When it happens, the conversation says so."
        >
          <Switch checked={s.routing.allow_cross_provider_fallback} label="Cross-provider fallback" onChange={(v) => save({ ...s, routing: { ...s.routing, allow_cross_provider_fallback: v } })} />
        </Row>
        <Row
          title="Anthropic refusal fallback"
          desc="If a Claude model declines a request, let Anthropic re-run it on its recommended fallback model (same provider). Atlas shows a notice whenever this happens."
        >
          <Switch checked={s.routing.anthropic_refusal_fallback} label="Anthropic refusal fallback" onChange={(v) => save({ ...s, routing: { ...s.routing, anthropic_refusal_fallback: v } })} />
        </Row>
        <Row title="How routing decides" desc="Your per-conversation choice, then your default provider and its default model. Tools are only offered to models that accept them; reasoning effort and summaries only to models that support them. Atlas never switches provider silently.">
          <span />
        </Row>
      </Panel>
    </>
  );
}

function PermissionsSection({ s, save }: { s: Settings; save: (n: Settings) => Promise<void> }) {
  const tools = useAtlasQuery("tools", api.tools, ["registry"]);
  const byClass = (c: string) => (tools.data ?? []).filter((t) => t.permission === c).map((t) => t.name).join(", ") || "none";
  return (
    <>
      <p className="mt-1 text-sm text-text-2">Enforced by Atlas's trusted core — not just requested of the model. Every approval covers one exact action, once.</p>
      <Panel className="mt-6 px-5">
        <Row title={`${permissionLabel.read_only} tools`} desc={`Allowed. ${byClass("read_only")}.`}>
          <Badge tone="ok">Always allowed</Badge>
        </Row>
        <Row title="Tools that send data off this computer" desc="For example, web search sends your query to the search provider.">
          <Segmented label="Network tools" value={s.permissions.network_tools} onChange={(v) => save({ ...s, permissions: { ...s.permissions, network_tools: v } })} options={[{ value: "ask", label: "Ask first" }, { value: "allow", label: "Allow" }]} />
        </Row>
        <Row title={`${permissionLabel.local_write} — create files and memories`} desc={byClass("local_write")}>
          <Segmented label="Local writes" value={s.permissions.local_write} onChange={(v) => save({ ...s, permissions: { ...s.permissions, local_write: v } })} options={[{ value: "ask", label: "Ask first" }, { value: "allow", label: "Allow" }]} />
        </Row>
        <Row title={`${permissionLabel.consequential} — send, publish, purchase, modify external records`} desc="Cannot be changed. No built-in tool in this version is consequential.">
          <Badge tone="warn">Always asks</Badge>
        </Row>
        <Row title={`${permissionLabel.destructive} — delete, privileged or unrestricted operations`} desc="Cannot be changed.">
          <Badge tone="err">Always denied</Badge>
        </Row>
      </Panel>
      <p className="mt-4 flex items-center gap-2 text-xs text-text-3"><ShieldCheck className="size-4 text-ok" aria-hidden /> Tool output, web pages and files can never approve anything themselves.</p>
    </>
  );
}

function LimitsSection({ s, save }: { s: Settings; save: (n: Settings) => Promise<void> }) {
  const l = s.limits;
  const set = (patch: Partial<Settings["limits"]>) => save({ ...s, limits: { ...l, ...patch } });
  return (
    <>
      <Panel className="mt-6 px-5">
        <Row title="Model steps per message" desc="Maximum model round-trips while working through tools (1–25).">
          <NumberInput label="Model steps" value={l.max_model_steps} min={1} max={25} onCommit={(v) => set({ max_model_steps: v ?? 8 })} />
        </Row>
        <Row title="Tool calls per task" desc="0 disables tools entirely.">
          <NumberInput label="Tool calls" value={l.max_tool_calls} min={0} max={50} onCommit={(v) => set({ max_tool_calls: v ?? 12 })} />
        </Row>
        <Row title="Request timeout (seconds)">
          <NumberInput label="Request timeout" value={l.request_timeout_secs} min={10} max={1800} onCommit={(v) => set({ request_timeout_secs: v ?? 300 })} />
        </Row>
        <Row title="Approval timeout (seconds)" desc="An unanswered approval expires and the action is not performed.">
          <NumberInput label="Approval timeout" value={l.approval_timeout_secs} min={15} max={3600} onCommit={(v) => set({ approval_timeout_secs: v ?? 600 })} />
        </Row>
        <Row title="Max output tokens per response">
          <NumberInput label="Max output tokens" value={l.max_output_tokens} min={256} max={128000} onCommit={(v) => set({ max_output_tokens: v ?? 16000 })} />
        </Row>
      </Panel>
      <h2 className="mb-2 mt-8 text-sm font-semibold text-text-2">Network</h2>
      <Panel className="px-5">
        <Row title="Offline mode" desc="Atlas contacts no cloud provider and runs no network tool. Local models (Ollama) keep working.">
          <Switch checked={s.network.offline_mode} label="Offline mode" onChange={(v) => save({ ...s, network: { offline_mode: v } })} />
        </Row>
      </Panel>
    </>
  );
}

function UsageSection({ s, save }: { s: Settings; save: (n: Settings) => Promise<void> }) {
  const usage = useAtlasQuery("usage", api.usage, ["usage"]);
  const u = usage.data;
  return (
    <>
      <p className="mt-1 text-sm text-text-2">Costs are <strong>estimates</strong> from published per-token prices and provider-reported token counts; prompt-cache discounts are not applied. Unknown prices are shown as unknown, never guessed.</p>
      {u && (
        <div className="mt-6 grid gap-3 sm:grid-cols-3">
          <Panel className="p-4"><p className="text-xs text-text-3">Estimated this month</p><p className="font-display text-xl font-semibold">{formatUsd(u.month_estimated_cost_usd)}</p>{u.month_has_unknown_costs && <p className="text-[0.6875rem] text-warn">+ requests with unknown cost</p>}</Panel>
          <Panel className="p-4"><p className="text-xs text-text-3">Requests today</p><p className="font-display text-xl font-semibold">{u.today_requests}</p></Panel>
          <Panel className="p-4"><p className="text-xs text-text-3">Since</p><p className="font-display text-xl font-semibold">{new Date(u.period_start).toLocaleDateString()}</p></Panel>
        </div>
      )}
      {u && u.by_model.length > 0 && (
        <Panel className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead><tr className="text-left text-[0.6875rem] uppercase tracking-wider text-text-3">{["Provider / model", "Requests", "Errors", "Tokens in / out", "Est. cost", "Avg time"].map((h) => <th key={h} className="px-4 py-2 font-medium">{h}</th>)}</tr></thead>
            <tbody>
              {u.by_model.map((m) => (
                <tr key={m.provider_id + m.model} className="border-t border-line-1">
                  <td className="px-4 py-2"><p>{m.provider_label ?? "removed provider"}</p><p className="font-mono text-[0.6875rem] text-text-3">{m.model}</p></td>
                  <td className="px-4 py-2">{m.requests}</td>
                  <td className="px-4 py-2">{m.errors}{m.rate_limited ? ` (${m.rate_limited} rate-limited)` : ""}</td>
                  <td className="px-4 py-2">{formatTokens(m.input_tokens)} / {formatTokens(m.output_tokens)}</td>
                  <td className="px-4 py-2">{m.unknown_cost_requests === m.requests ? "unknown" : formatUsd(m.estimated_cost_usd)}{m.unknown_cost_requests > 0 && m.unknown_cost_requests < m.requests ? "+" : ""}</td>
                  <td className="px-4 py-2">{m.avg_duration_ms ? `${(m.avg_duration_ms / 1000).toFixed(1)} s` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}
      <h2 className="mb-2 mt-8 text-sm font-semibold text-text-2">Limits</h2>
      <Panel className="px-5">
        <Row title="Monthly budget (USD)" desc="When estimated spend reaches this, new requests are blocked until next month or until you raise it.">
          <NumberInput label="Monthly budget" nullable value={s.usage.monthly_budget_usd} min={0} max={100000} step={0.5} onCommit={(v) => save({ ...s, usage: { ...s.usage, monthly_budget_usd: v } })} />
        </Row>
        <Row title="Daily request limit">
          <NumberInput label="Daily request limit" nullable value={s.usage.daily_request_limit} min={1} max={100000} onCommit={(v) => save({ ...s, usage: { ...s.usage, daily_request_limit: v } })} />
        </Row>
      </Panel>
    </>
  );
}

function DataSection({ s, save }: { s: Settings; save: (n: Settings) => Promise<void> }) {
  const [restoreInfo, setRestoreInfo] = useState<Record<string, unknown> | null>(null);
  const [removeKeys, setRemoveKeys] = useState(false);
  const run = async <T,>(fn: () => Promise<T>, ok?: (v: T) => string | null) => {
    try {
      const v = await fn();
      const m = ok?.(v);
      if (m) toast.success(m);
      return v;
    } catch (e) {
      toast.error(e instanceof AtlasError ? e.message : String(e));
      return undefined;
    }
  };
  return (
    <>
      <p className="mt-1 text-sm text-text-2">Everything Atlas stores lives on this computer. Messages you send to a cloud model are processed by that provider under its terms.</p>
      <Panel className="mt-6 px-5">
        <Row title="Export all data" desc="Settings, projects, memories and conversations as JSON. Never includes API keys.">
          <Button icon={<Download className="size-4" aria-hidden />} onClick={() => run(api.exportAll, (p) => (p ? `Exported to ${p}` : null))}>Export…</Button>
        </Row>
        <Row title="Back up the database" desc="A complete snapshot you can restore later. Keys are not included (they live in your system credential store).">
          <Button icon={<HardDriveDownload className="size-4" aria-hidden />} onClick={() => run(api.backupCreate, (p) => (p ? `Backup saved to ${p}` : null))}>Create backup…</Button>
        </Row>
        <Row title="Restore from a backup" desc="Atlas checks the file first and shows what it contains before anything is replaced.">
          <Button icon={<RotateCcw className="size-4" aria-hidden />} onClick={async () => { const info = await run(api.backupInspect); if (info) setRestoreInfo(info); }}>Choose backup…</Button>
        </Row>
      </Panel>
      <h2 className="mb-2 mt-8 text-sm font-semibold text-text-2">Retention</h2>
      <Panel className="px-5">
        <Row title="Delete conversations older than (days)" desc="Applies at startup to non-archived conversations. Empty keeps everything.">
          <NumberInput label="Conversation retention" nullable value={s.retention.conversation_days} min={1} max={36500} onCommit={(v) => save({ ...s, retention: { ...s.retention, conversation_days: v } })} />
        </Row>
        <Row title="Delete activity log entries older than (days)">
          <NumberInput label="Audit retention" nullable value={s.retention.audit_days} min={1} max={36500} onCommit={(v) => save({ ...s, retention: { ...s.retention, audit_days: v } })} />
        </Row>
      </Panel>
      <h2 className="mb-2 mt-8 text-sm font-semibold text-text-2">Credentials</h2>
      <Panel className="px-5">
        <Row title="Remove all stored keys" desc="Deletes every provider and integration key from your system credential store.">
          <Button variant="danger" icon={<KeyRound className="size-4" aria-hidden />} onClick={() => setRemoveKeys(true)}>Remove all keys…</Button>
        </Row>
      </Panel>
      <ConfirmDialog
        open={Boolean(restoreInfo)}
        onOpenChange={(v) => !v && setRestoreInfo(null)}
        title="Replace your current data with this backup?"
        body={
          restoreInfo && (
            <div className="space-y-2">
              <p>Backup <strong className="font-mono">{String(restoreInfo.file)}</strong> passed integrity checks and contains:</p>
              <ul className="list-disc pl-5">
                <li>{String(restoreInfo.conversations)} conversations</li>
                <li>{String(restoreInfo.memories)} memories</li>
                <li>{String(restoreInfo.projects)} projects</li>
                <li>{String(restoreInfo.providers)} provider configurations (keys are not part of backups)</li>
              </ul>
              <p>Your current conversations, memories, projects and settings will be replaced. Consider creating a backup of the current state first.</p>
            </div>
          )
        }
        confirmLabel="Restore backup"
        danger
        typeToConfirm="RESTORE"
        onConfirm={async () => void (await run(api.backupRestoreConfirm, () => "Backup restored"))}
      />
      <ConfirmDialog
        open={removeKeys}
        onOpenChange={setRemoveKeys}
        title="Remove all stored keys?"
        body={<p>Every provider and integration will need its key entered again.</p>}
        confirmLabel="Remove keys"
        danger
        typeToConfirm="REMOVE"
        onConfirm={async () => void (await run(() => api.removeAllCredentials("REMOVE"), () => "All keys removed"))}
      />
    </>
  );
}

function DiagnosticsSection() {
  const diag = useAtlasQuery("diag", api.diagnostics, ["providers", "registry", "tasks", "settings"]);
  const errors = useAtlasQuery("errors", () => api.recentErrors(40), ["tasks", "providers"]);
  const text = diag.data ? JSON.stringify({ diagnostics: diag.data, recent_events: errors.data ?? [] }, null, 2) : "";
  const d = diag.data as Record<string, Record<string, unknown>> | undefined;
  return (
    <>
      <p className="mt-1 text-sm text-text-2">A content-free health report. It never includes message text or keys. Nothing is sent anywhere unless you save or copy it yourself.</p>
      {d && (
        <div className="mt-6 grid gap-3 sm:grid-cols-2">
          <Panel className="p-4 text-sm"><p className="text-xs text-text-3">Database</p><StatusPill tone={d.database?.quick_check === "ok" ? "ok" : "err"} label={`Integrity: ${String(d.database?.quick_check)}`} /><p className="mt-1 text-xs text-text-3">Schema v{String(d.database?.schema_version)}</p></Panel>
          <Panel className="p-4 text-sm"><p className="text-xs text-text-3">Credential store</p><StatusPill tone={d.credential_store?.ok ? "ok" : "err"} label={String(d.credential_store?.backend)} />{typeof d.credential_store?.detail === "string" && <p className="mt-1 text-xs text-err">{d.credential_store.detail}</p>}</Panel>
          <Panel className="p-4 text-sm"><p className="text-xs text-text-3">Tools</p><p>{String(d.tools?.available)} available of {String(d.tools?.registered)} registered</p></Panel>
          <Panel className="p-4 text-sm"><p className="text-xs text-text-3">Task engine</p><p>{String(d.task_engine?.active_turns)} active · {String(d.task_engine?.waiting_approvals)} waiting</p></Panel>
        </div>
      )}
      <div className="mt-6 flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold text-text-2">Report preview</h2>
        <Button size="sm" className="ml-auto" icon={<Copy className="size-3.5" aria-hidden />} onClick={() => void navigator.clipboard?.writeText(text).then(() => toast.success("Copied"))}>Copy</Button>
        <Button size="sm" variant="subtle" icon={<FileDown className="size-3.5" aria-hidden />} onClick={async () => { const p = await api.saveTextViaDialog("atlas-diagnostics.json", "json", text); if (p) toast.success(`Saved to ${p}`); }}>Save report…</Button>
      </div>
      <pre className="mt-2 max-h-[28rem] overflow-auto rounded-md border border-line-1 bg-[color:var(--code-bg)] p-4 font-mono text-xs text-text-2">{text || "Loading…"}</pre>
      <h2 className="mb-2 mt-8 text-sm font-semibold text-text-2">Recent warnings and errors</h2>
      {errors.data?.length ? (
        <Panel className="divide-y divide-[color:var(--line-1)]">
          {errors.data.map((e) => (
            <div key={e.id} className="flex flex-wrap items-center gap-3 px-4 py-2 text-xs">
              <Badge tone={e.level === "error" ? "err" : "warn"}>{e.level}</Badge>
              <span className="font-mono text-text-1">{e.kind}</span>
              {e.tool_id && <span className="font-mono text-text-3">{e.tool_id}</span>}
              <span className="ml-auto text-text-3">{relativeTime(e.ts)}</span>
            </div>
          ))}
        </Panel>
      ) : (
        <p className="text-sm text-text-3">None recorded.</p>
      )}
    </>
  );
}

function AboutSection() {
  const info = useAtlasQuery("app-info", api.appInfo, []);
  const i = info.data;
  return (
    <Panel className="mt-6 px-5">
      <Row title="ATLAS Co-Pilot" desc="A local-first AI desktop companion."><Badge tone="accent">v{i?.version ?? "…"}</Badge></Row>
      <Row title="Platform"><span className="text-sm text-text-2">{i ? `${i.os} · ${i.arch}` : "…"}</span></Row>
      <Row title="Data folder" desc={<span className="break-all font-mono">{i?.data_dir ?? "…"}</span>}><span /></Row>
      <Row title="Credential store"><span className="text-sm text-text-2">{i?.credential_backend}</span></Row>
      {i?.e2e_build && <Row title="Build" desc="Automated-test build with a scripted provider and in-memory keys. Not for real use."><Badge tone="warn">E2E test build</Badge></Row>}
      <Row title="Updates" desc="This version does not update itself. New versions are installed from a release package; your data folder is kept."><span /></Row>
    </Panel>
  );
}
