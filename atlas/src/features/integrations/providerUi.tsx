import { Cloud, Cpu, KeyRound } from "lucide-react";
import { useState } from "react";
import { Button, Field, Input, Panel, StatusPill, type Tone } from "@/components/ui/primitives";
import { api, AtlasError } from "@/lib/bridge";
import { cn } from "@/lib/format";
import { useAtlasQuery } from "@/lib/query";
import type { ProviderConfig, ProviderStatus, ProviderTemplate } from "@/lib/schemas";

export const providerStatus: Record<ProviderStatus, { tone: Tone; label: string }> = {
  not_configured: { tone: "warn", label: "Not configured" },
  untested: { tone: "neutral", label: "Configured — not tested yet" },
  connected: { tone: "ok", label: "Connected" },
  unavailable: { tone: "err", label: "Unavailable" },
  auth_failed: { tone: "err", label: "Authentication failed" },
  rate_limited: { tone: "warn", label: "Rate limited" },
  degraded: { tone: "warn", label: "Temporarily degraded" },
};

export function ProviderStatusPill({ p }: { p: ProviderConfig }) {
  if (!p.enabled) return <StatusPill tone="neutral" label="Disabled" />;
  const s = providerStatus[p.status];
  return <StatusPill tone={s.tone} label={s.label} />;
}

/**
 * Add a provider: pick a kind, confirm the endpoint, paste a key (sent once to the OS credential
 * store), then test. Returns the created provider via onDone.
 */
export function AddProviderForm({ onDone, compact }: { onDone?: (p: ProviderConfig, ok: boolean) => void; compact?: boolean }) {
  const templates = useAtlasQuery("provider-templates", api.providerTemplates, []);
  const [tpl, setTpl] = useState<ProviderTemplate | null>(null);
  const [label, setLabel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);

  const choose = (t: ProviderTemplate) => {
    setTpl(t);
    setLabel(t.label);
    setBaseUrl(t.default_base_url);
    setModel(t.suggested_model);
    setError(null);
    setResult(null);
  };

  const save = async () => {
    if (!tpl) return;
    setBusy(true);
    setError(null);
    try {
      let p = await api.addProvider({ kind: tpl.kind, label, baseUrl, defaultModel: model.trim() || null });
      if (key.trim()) p = await api.setProviderKey(p.id, key);
      setKey("");
      const r = await api.testProvider(p.id);
      setResult({ ok: r.ok, message: r.message });
      // If the user left the model empty, pick the first listed model.
      if (r.ok && !r.provider.default_model && r.provider.models[0]) {
        await api.updateProvider(p.id, p.label, p.base_url, r.provider.models[0].id, true);
      }
      onDone?.(r.provider, r.ok);
    } catch (e) {
      setError(e instanceof AtlasError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className={cn("grid gap-2", compact ? "sm:grid-cols-2" : "sm:grid-cols-2 lg:grid-cols-4")} role="radiogroup" aria-label="Provider type">
        {(templates.data ?? []).map((t) => (
          <button
            key={t.kind}
            role="radio"
            aria-checked={tpl?.kind === t.kind}
            onClick={() => choose(t)}
            className={cn(
              "flex flex-col items-start gap-1 rounded-lg border px-3.5 py-3 text-left transition-colors",
              tpl?.kind === t.kind ? "border-accent bg-accent-softer shadow-[var(--glow-accent)]" : "border-line-2 bg-bg-2 hover:border-line-3",
            )}
          >
            <span className="flex items-center gap-1.5 text-sm font-semibold text-text-1">
              {t.local ? <Cpu className="size-4 text-accent-teal" aria-hidden /> : <Cloud className="size-4 text-accent" aria-hidden />}
              {t.label}
            </span>
            <span className="text-xs text-text-3">{t.local ? "Runs on this computer" : "Cloud service · your API key"}</span>
          </button>
        ))}
      </div>
      {tpl && (
        <Panel className="space-y-4 p-4 anim-rise">
          <p className="rounded-md border border-line-1 bg-bg-1 px-3 py-2 text-xs text-text-2">
            <strong className="text-text-1">Privacy: </strong>
            {tpl.privacy_note}
          </p>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Name" htmlFor="pv-label">
              <Input id="pv-label" value={label} onChange={(e) => setLabel(e.target.value)} />
            </Field>
            <Field label="Default model" htmlFor="pv-model" hint="Leave empty to pick from the list after testing.">
              <Input id="pv-model" value={model} onChange={(e) => setModel(e.target.value)} placeholder={tpl.local ? "e.g. qwen3" : ""} />
            </Field>
            <Field label="Endpoint" htmlFor="pv-url" hint="HTTPS, or http://localhost for local servers.">
              <Input id="pv-url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} spellCheck={false} />
            </Field>
            {tpl.needs_key && (
              <Field label="API key" htmlFor="pv-key" hint={tpl.key_help}>
                <div className="relative">
                  <KeyRound className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-text-3" aria-hidden />
                  <Input id="pv-key" type="password" autoComplete="off" spellCheck={false} value={key} onChange={(e) => setKey(e.target.value)} className="pl-8 font-mono" placeholder="Paste your key" />
                </div>
              </Field>
            )}
          </div>
          {!tpl.needs_key && <p className="text-xs text-text-3">{tpl.key_help}</p>}
          <p className="text-xs text-text-3">Keys are stored in your operating system's credential store, never in Atlas's database, logs or prompts.</p>
          {error && (
            <p role="alert" className="text-sm text-err">
              {error}
            </p>
          )}
          {result && (
            <p role="status" className={cn("text-sm", result.ok ? "text-ok" : "text-err")}>
              {result.ok ? "✓ " : "✕ "}
              {result.message}
            </p>
          )}
          <div className="flex justify-end">
            <Button variant="primary" loading={busy} disabled={!label.trim() || !baseUrl.trim() || (tpl.needs_key && !key.trim())} onClick={save}>
              Save and test connection
            </Button>
          </div>
        </Panel>
      )}
    </div>
  );
}
