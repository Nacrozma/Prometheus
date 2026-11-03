import { Cloud, Cpu, Globe, KeyRound, Plus, Star, Trash2, Wrench } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { Badge, Button, EmptyState, Field, Input, PageHeader, Panel, Select, Skeleton, StatusPill, Switch } from "@/components/ui/primitives";
import { api, AtlasError } from "@/lib/bridge";
import { cn, permissionLabel, relativeTime } from "@/lib/format";
import { useAtlasQuery } from "@/lib/query";
import type { Integration, ProviderConfig, ToolInfo } from "@/lib/schemas";
import { AddProviderForm, ProviderStatusPill } from "./providerUi";

async function act<T>(fn: () => Promise<T>, ok?: string): Promise<T | undefined> {
  try {
    const r = await fn();
    if (ok) toast.success(ok);
    return r;
  } catch (e) {
    toast.error(e instanceof AtlasError ? e.message : String(e));
    return undefined;
  }
}

function KeyDialog({ open, onOpenChange, title, onSave }: { open: boolean; onOpenChange: (v: boolean) => void; title: string; onSave: (k: string) => Promise<unknown> }) {
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Dialog
      open={open}
      onOpenChange={(v) => (setKey(""), onOpenChange(v))}
      title={title}
      description="The key goes straight to your operating system's credential store. Atlas never shows it again."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button
            variant="primary"
            loading={busy}
            disabled={!key.trim()}
            onClick={async () => {
              setBusy(true);
              await onSave(key);
              setBusy(false);
              setKey("");
              onOpenChange(false);
            }}
          >
            Save key
          </Button>
        </>
      }
    >
      <Input type="password" autoComplete="off" spellCheck={false} value={key} onChange={(e) => setKey(e.target.value)} aria-label="API key" className="font-mono" autoFocus />
    </Dialog>
  );
}

function ProviderCard({ p, isDefault }: { p: ProviderConfig; isDefault: boolean }) {
  const [testing, setTesting] = useState(false);
  const [keyOpen, setKeyOpen] = useState(false);
  const [del, setDel] = useState(false);
  const [edit, setEdit] = useState(false);
  const [label, setLabel] = useState(p.label);
  const [url, setUrl] = useState(p.base_url);
  const settings = useAtlasQuery("settings", api.settings, ["settings"]);
  const models = p.models.length ? p.models : p.default_model ? [{ id: p.default_model, display_name: p.default_model }] : [];

  const test = async () => {
    setTesting(true);
    const r = await act(() => api.testProvider(p.id));
    setTesting(false);
    if (r) (r.ok ? toast.success : toast.error)(`${p.label}: ${r.message}`);
  };

  return (
    <Panel className="flex flex-col gap-3 p-4">
      <div className="flex items-start gap-3">
        <div className="grid size-10 shrink-0 place-items-center rounded-md border border-line-2 bg-bg-3">
          {p.local ? <Cpu className="size-5 text-accent-teal" aria-hidden /> : <Cloud className="size-5 text-accent" aria-hidden />}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-semibold text-text-1">{p.label}</h3>
            {isDefault && <Badge tone="accent"><Star className="size-3" aria-hidden /> Default</Badge>}
            <Badge>{p.local ? "Local" : "Cloud"}</Badge>
          </div>
          <p className="truncate font-mono text-[0.6875rem] text-text-3">{p.base_url}</p>
        </div>
        <Switch checked={p.enabled} label={`Enable ${p.label}`} onChange={(v) => void act(() => api.updateProvider(p.id, p.label, p.base_url, p.default_model, v))} />
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
        <ProviderStatusPill p={p} />
        <span className="text-text-3">Checked {relativeTime(p.last_checked_at)}</span>
        {p.key_hint && <span className="inline-flex items-center gap-1 font-mono text-text-3"><KeyRound className="size-3" aria-hidden />{p.key_hint}</span>}
        <span className="text-text-3">{p.models.length ? `${p.models.length} ${p.models.length === 1 ? "model" : "models"}` : "model list not loaded"}</span>
      </div>
      {p.status_detail && p.status !== "connected" && <p className="rounded-sm bg-bg-1 px-2 py-1.5 text-xs text-text-2">{p.status_detail}</p>}
      <Field label="Default model" htmlFor={`m-${p.id}`}>
        <Select id={`m-${p.id}`} value={p.default_model ?? ""} onChange={(e) => void act(() => api.updateProvider(p.id, p.label, p.base_url, e.target.value || null, p.enabled))}>
          <option value="">— choose —</option>
          {models.map((m) => (
            <option key={m.id} value={m.id}>{m.display_name}{m.display_name !== m.id ? ` (${m.id})` : ""}</option>
          ))}
        </Select>
      </Field>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="subtle" loading={testing} onClick={test}>Test connection</Button>
        {["anthropic", "openai", "openai_compatible"].includes(p.kind) && (
          <Button size="sm" onClick={() => setKeyOpen(true)}>{p.has_credential ? "Replace key" : "Add key"}</Button>
        )}
        {p.has_credential && <Button size="sm" variant="ghost" onClick={() => void act(() => api.clearProviderKey(p.id), "Key removed from the credential store")}>Remove key</Button>}
        <Button size="sm" variant="ghost" onClick={() => setEdit(true)}>Edit</Button>
        {!isDefault && settings.data && (
          <Button size="sm" variant="ghost" onClick={() => void act(() => api.updateSettings({ ...settings.data!, default_provider_id: p.id }), `${p.label} is now the default`)}>
            Make default
          </Button>
        )}
        <Button size="sm" variant="ghost" className="ml-auto text-err" onClick={() => setDel(true)} icon={<Trash2 className="size-3.5" aria-hidden />}>
          Remove
        </Button>
      </div>
      <KeyDialog open={keyOpen} onOpenChange={setKeyOpen} title={`API key for ${p.label}`} onSave={(k) => act(() => api.setProviderKey(p.id, k), "Key saved — test the connection to confirm it works")} />
      <Dialog
        open={edit}
        onOpenChange={setEdit}
        title={`Edit ${p.label}`}
        footer={
          <>
            <Button variant="ghost" onClick={() => setEdit(false)}>Cancel</Button>
            <Button variant="primary" onClick={() => void act(() => api.updateProvider(p.id, label, url, p.default_model, p.enabled), "Saved").then(() => setEdit(false))}>Save</Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label="Name" htmlFor={`l-${p.id}`}><Input id={`l-${p.id}`} value={label} onChange={(e) => setLabel(e.target.value)} /></Field>
          <Field label="Endpoint" htmlFor={`u-${p.id}`} hint="Changing the endpoint marks the provider as untested."><Input id={`u-${p.id}`} value={url} onChange={(e) => setUrl(e.target.value)} /></Field>
        </div>
      </Dialog>
      <ConfirmDialog
        open={del}
        onOpenChange={setDel}
        title={`Remove ${p.label}?`}
        body={<p>The provider's settings are deleted and its key is removed from your credential store. Conversations are kept.</p>}
        confirmLabel="Remove provider"
        danger
        onConfirm={async () => void (await act(() => api.deleteProvider(p.id), "Provider removed"))}
      />
    </Panel>
  );
}

function IntegrationCard({ i }: { i: Integration }) {
  const [keyOpen, setKeyOpen] = useState(false);
  const [testing, setTesting] = useState(false);
  const tone = !i.implemented ? "neutral" : i.status === "connected" ? "ok" : i.status === "auth_failed" || i.status === "unavailable" ? "err" : i.has_credential ? "neutral" : "warn";
  const label = !i.implemented ? "Planned — not available in this version" : i.status === "connected" ? "Connected" : i.status === "auth_failed" ? "Key rejected" : i.status === "unavailable" ? "Unavailable" : i.has_credential ? "Configured — not tested yet" : "Not configured";
  return (
    <Panel className={cn("flex flex-col gap-3 p-4", !i.implemented && "opacity-70")}>
      <div className="flex items-start gap-3">
        <div className="grid size-10 shrink-0 place-items-center rounded-md border border-line-2 bg-bg-3">
          <Globe className="size-5 text-accent" aria-hidden />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-semibold">{i.name}</h3>
            <Badge>{i.category}</Badge>
          </div>
          <p className="text-xs text-text-2">{i.description}</p>
        </div>
        {i.implemented && <Switch checked={i.enabled} disabled={!i.has_credential} label={`Enable ${i.name}`} onChange={(v) => void act(() => api.setIntegrationEnabled(i.id, v))} />}
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
        <StatusPill tone={tone} label={label} />
        {i.key_hint && <span className="font-mono text-text-3">{i.key_hint}</span>}
        {i.last_checked_at && <span className="text-text-3">Checked {relativeTime(i.last_checked_at)}</span>}
      </div>
      <p className="text-xs text-text-3"><strong className="text-text-2">Permission scope:</strong> {i.permission_scope}</p>
      {i.status_detail && <p className="rounded-sm bg-bg-1 px-2 py-1.5 text-xs text-text-2">{i.status_detail}</p>}
      {i.implemented ? (
        <>
          <p className="text-xs text-text-3">{i.setup}</p>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={() => setKeyOpen(true)}>{i.has_credential ? "Replace key" : "Add key"}</Button>
            {i.has_credential && (
              <>
                <Button size="sm" variant="subtle" loading={testing} onClick={async () => { setTesting(true); await act(() => api.testIntegration(i.id)); setTesting(false); }}>
                  Test (uses 1 search credit)
                </Button>
                <Button size="sm" variant="ghost" onClick={() => void act(() => api.clearIntegrationKey(i.id), "Key removed")}>Disconnect</Button>
              </>
            )}
          </div>
          <KeyDialog open={keyOpen} onOpenChange={setKeyOpen} title={`API key for ${i.name}`} onSave={(k) => act(() => api.setIntegrationKey(i.id, k), "Key saved")} />
        </>
      ) : null}
    </Panel>
  );
}

const permTone = { read_only: "ok", local_write: "warn", consequential: "err", destructive: "err" } as const;

function ToolRow({ t }: { t: ToolInfo }) {
  const avail =
    t.availability.state === "available" ? { tone: "ok" as const, label: "Available" } : { tone: t.availability.state === "unavailable" ? ("err" as const) : ("warn" as const), label: t.availability.reason };
  return (
    <tr className="border-t border-line-1 align-top">
      <td className="py-2.5 pl-4 pr-3">
        <p className="font-medium text-text-1">{t.name}</p>
        <p className="font-mono text-[0.6875rem] text-text-3">{t.id} · v{t.version}</p>
      </td>
      <td className="px-3 py-2.5 text-xs text-text-2"><span className="line-clamp-2">{t.description}</span><span className="mt-0.5 block text-text-3">{t.data_scope}</span></td>
      <td className="px-3 py-2.5"><Badge tone={permTone[t.permission]}>{permissionLabel[t.permission]}</Badge>{t.network && <Badge tone="info" className="ml-1">Network</Badge>}</td>
      <td className="px-3 py-2.5">{t.enabled ? <StatusPill tone={avail.tone} label={avail.label} /> : <StatusPill tone="neutral" label="Disabled" />}</td>
      <td className="px-3 py-2.5 text-xs text-text-3">{t.use_count} runs{t.failure_count ? `, ${t.failure_count} failed` : ""}</td>
      <td className="py-2.5 pl-3 pr-4 text-right"><Switch checked={t.enabled} label={`Enable ${t.name}`} onChange={(v) => void act(() => api.setToolEnabled(t.id, v))} /></td>
    </tr>
  );
}

export function IntegrationsPage() {
  const providers = useAtlasQuery("providers", api.providers, ["providers"]);
  const integrations = useAtlasQuery("integrations", api.integrations, ["registry"]);
  const tools = useAtlasQuery("tools", api.tools, ["registry", "settings"]);
  const settings = useAtlasQuery("settings", api.settings, ["settings"]);
  const [adding, setAdding] = useState(false);

  return (
    <div className="h-full overflow-y-auto">
      <PageHeader eyebrow="Connections" title="Integrations" subtitle="AI providers, external services and the tools Atlas can use. Nothing is shown as connected until a real test succeeds." />
      <div className="space-y-10 px-8 py-6">
        <section aria-labelledby="h-providers">
          <div className="mb-3 flex items-center justify-between">
            <h2 id="h-providers" className="font-display text-md font-semibold">AI providers</h2>
            <Button variant="subtle" icon={<Plus className="size-4" aria-hidden />} onClick={() => setAdding((v) => !v)}>{adding ? "Close" : "Add provider"}</Button>
          </div>
          {adding && (
            <div className="mb-5">
              <AddProviderForm onDone={(_p, ok) => ok && setAdding(false)} />
            </div>
          )}
          {providers.loading && !providers.data ? (
            <div className="grid gap-4 lg:grid-cols-2"><Skeleton className="h-56" /><Skeleton className="h-56" /></div>
          ) : providers.data?.length ? (
            <div className="grid gap-4 lg:grid-cols-2">
              {providers.data.map((p) => <ProviderCard key={p.id} p={p} isDefault={settings.data?.default_provider_id === p.id} />)}
            </div>
          ) : !adding ? (
            <EmptyState icon={<Cloud className="size-5" aria-hidden />} title="No AI provider yet" body="Add Anthropic, OpenAI, an OpenAI-compatible service, or Ollama on this computer." action={<Button variant="primary" onClick={() => setAdding(true)}>Add a provider</Button>} />
          ) : null}
        </section>

        <section aria-labelledby="h-integrations">
          <h2 id="h-integrations" className="mb-3 font-display text-md font-semibold">Services</h2>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {(integrations.data ?? []).map((i) => <IntegrationCard key={i.id} i={i} />)}
          </div>
        </section>

        <section aria-labelledby="h-tools">
          <h2 id="h-tools" className="mb-1 font-display text-md font-semibold">Tools</h2>
          <p className="mb-3 text-sm text-text-2">Every tool Atlas can call, from the live registry. Disabled tools are never offered to the model.</p>
          <Panel className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead>
                <tr className="text-left text-[0.6875rem] uppercase tracking-wider text-text-3">
                  <th className="py-2 pl-4 pr-3 font-medium">Tool</th>
                  <th className="px-3 py-2 font-medium">What it does</th>
                  <th className="px-3 py-2 font-medium">Permission</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium">Activity</th>
                  <th className="py-2 pl-3 pr-4 text-right font-medium"><Wrench className="ml-auto size-3.5" aria-label="Enabled" /></th>
                </tr>
              </thead>
              <tbody>{(tools.data ?? []).map((t) => <ToolRow key={t.id} t={t} />)}</tbody>
            </table>
          </Panel>
        </section>
      </div>
    </div>
  );
}
