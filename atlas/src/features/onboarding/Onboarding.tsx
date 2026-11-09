import { Hammer, Wallet } from "lucide-react";
import { PrometheusAvatar } from "@/features/siblings/avatar/PrometheusAvatar";
import { ArrowLeft, ArrowRight, Check, Cloud, Cpu, FolderOpen, HardDrive, KeyRound, Orbit, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { applyAppearance } from "@/app/App";
import { Emblem } from "@/components/Emblem";
import { Badge, Button, Field, Input, Segmented, StatusPill } from "@/components/ui/primitives";
import { AddProviderForm } from "@/features/integrations/providerUi";
import { PersonalityPicker } from "@/features/companion/PersonalityPicker";
import { api, AtlasError } from "@/lib/bridge";
import { cn } from "@/lib/format";
import { useAtlasQuery } from "@/lib/query";
import type { Settings } from "@/lib/schemas";
import { useTurns } from "@/state/turns";
import { useUi } from "@/state/ui";

const STEPS = ["Welcome", "About you", "Your data", "AI model", "Workspace", "The Atlas", "Forge & siblings", "Ready"] as const;

export function Onboarding({ settings, onDone }: { settings: Settings; onDone: () => void }) {
  const [step, setStep] = useState(0);
  const [draft, setDraft] = useState(settings);
  const [sample, setSample] = useState<string | null>(null);
  const info = useAtlasQuery("app-info", api.appInfo, []);
  const providers = useAtlasQuery("providers", api.providers, ["providers"]);
  const live = useAtlasQuery("settings", api.settings, ["settings"]);
  const tools = useAtlasQuery("tools", api.tools, ["registry"]);
  const connected = (providers.data ?? []).some((p) => p.status === "connected");
  const workspace = live.data?.workspace_dir ?? null;

  const persist = async (patch: Partial<Settings> = {}) => {
    const base = live.data ?? draft;
    const next = { ...base, companion: draft.companion, appearance: draft.appearance, ...patch };
    const saved = await api.updateSettings(next);
    setDraft(saved);
    return saved;
  };

  const finish = async (then?: "chat" | "task") => {
    try {
      await persist({ onboarding_completed: true });
      onDone();
      const ui = useUi.getState();
      if (then) {
        const c = await api.createConversation(null, then === "task" ? "First tool-assisted task" : "");
        ui.openConversation(c.id);
        const prompt =
          then === "task"
            ? sample
              ? `Read the demo file "${sample}" in my workspace and tell me which categories went over plan, by how much. Use the calculator for the differences.`
              : "What is 17.5% of 2,340? Use your calculator tool and show the result."
            : `Hi Atlas! I'm ${draft.companion.preferred_name || "new here"}. Give me a quick tour of what you can help with.`;
        void useTurns.getState().send(c.id, prompt);
      } else {
        ui.navigate("home");
      }
    } catch (e) {
      toast.error(e instanceof AtlasError ? e.message : "Could not save settings");
    }
  };

  const next = () => setStep((s) => Math.min(s + 1, STEPS.length - 1));
  const back = () => setStep((s) => Math.max(s - 1, 0));
  const c = draft.companion;

  return (
    <div className="atmosphere flex h-full flex-col overflow-y-auto bg-bg-1">
      <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col px-6 py-10">
        <ol className="mb-10 flex items-center gap-2" aria-label="Setup progress">
          {STEPS.map((s, i) => (
            <li key={s} className="flex flex-1 flex-col gap-1.5">
              <span aria-hidden className={cn("h-1 rounded-full transition-colors duration-[var(--dur-med)]", i <= step ? "bg-accent" : "bg-bg-4")} />
              <span className={cn("hidden text-[0.6875rem] sm:block", i === step ? "text-text-1" : "text-text-3")} aria-current={i === step ? "step" : undefined}>
                {s}
              </span>
            </li>
          ))}
        </ol>

        <div key={step} className="flex-1 anim-rise">
          {step === 0 && (
            <div className="flex flex-col items-center pt-6 text-center">
              <Emblem size={120} animated glow />
              <p className="mt-8 text-xs font-semibold uppercase tracking-[0.3em] text-accent">ATLAS Co-Pilot</p>
              <h1 className="mt-3 font-display text-3xl font-semibold leading-tight">Hello. I'm Atlas.</h1>
              <p className="mt-4 max-w-lg text-md text-text-2">
                A calm, capable companion that lives on this computer. I can think things through with you, remember what you choose, and carry out
                tasks with tools — and I'll always ask before I change anything.
              </p>
              <div className="mt-8 grid w-full max-w-xl gap-3 text-left sm:grid-cols-3">
                {[
                  ["The Mind", "Conversation, planning and memory you control."],
                  ["The Engine", "Tools that do real work, within limits."],
                  ["The Guardian", "Permissions, approvals and private keys."],
                ].map(([t, d]) => (
                  <div key={t} className="rounded-lg border border-line-1 bg-bg-2/70 p-3">
                    <p className="font-display text-sm font-semibold text-text-1">{t}</p>
                    <p className="mt-0.5 text-xs text-text-2">{d}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {step === 1 && (
            <div className="space-y-6">
              <div>
                <h2 className="font-display text-xl font-semibold">Make Atlas yours</h2>
                <p className="mt-1 text-sm text-text-2">All optional, and you can change any of it later in Settings.</p>
              </div>
              <Field label="What should Atlas call you?" htmlFor="ob-name" hint="Leave empty if you'd rather not say.">
                <Input id="ob-name" value={c.preferred_name} maxLength={60} onChange={(e) => setDraft({ ...draft, companion: { ...c, preferred_name: e.target.value } })} />
              </Field>
              <Field label="Personality" hint="A starting point. Fine-tune tone, length and initiative later in Settings → Companion.">
                <PersonalityPicker value={c.personality} includeCustom={false} onChange={(personality) => setDraft({ ...draft, companion: { ...c, personality } })} />
              </Field>
              <Field label="Theme">
                <Segmented
                  label="Theme"
                  value={draft.appearance.theme}
                  onChange={(theme) => {
                    const d = { ...draft, appearance: { ...draft.appearance, theme } };
                    setDraft(d);
                    applyAppearance(d);
                  }}
                  options={[{ value: "dark", label: "Deep Orbit (dark)" }, { value: "light", label: "Daylight" }, { value: "system", label: "Match system" }]}
                />
              </Field>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-5">
              <h2 className="font-display text-xl font-semibold">Where your data lives</h2>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="rounded-lg border border-line-1 bg-bg-2/70 p-4">
                  <HardDrive className="size-5 text-accent-teal" aria-hidden />
                  <p className="mt-2 font-semibold">On this computer</p>
                  <p className="mt-1 text-sm text-text-2">Conversations, memories, projects, settings and task history are stored locally in a database only you control.</p>
                  {info.data?.data_dir && <p className="mt-2 break-all font-mono text-[0.6875rem] text-text-3">{info.data.data_dir}</p>}
                </div>
                <div className="rounded-lg border border-line-1 bg-bg-2/70 p-4">
                  <KeyRound className="size-5 text-accent" aria-hidden />
                  <p className="mt-2 font-semibold">Keys stay locked</p>
                  <p className="mt-1 text-sm text-text-2">API keys go into your system's credential store ({info.data?.credential_backend ?? "OS keychain"}). They are never shown again, logged, exported, or sent to an AI model.</p>
                </div>
                <div className="rounded-lg border border-line-1 bg-bg-2/70 p-4">
                  <Cloud className="size-5 text-info" aria-hidden />
                  <p className="mt-2 font-semibold">Cloud models see what you send</p>
                  <p className="mt-1 text-sm text-text-2">If you use a cloud AI provider, your messages — plus only the relevant memories and files Atlas attaches — are processed by that provider under its terms.</p>
                </div>
                <div className="rounded-lg border border-line-1 bg-bg-2/70 p-4">
                  <ShieldCheck className="size-5 text-ok" aria-hidden />
                  <p className="mt-2 font-semibold">No telemetry</p>
                  <p className="mt-1 text-sm text-text-2">Atlas sends nothing about you anywhere on its own. Diagnostics are only exported when you choose to, with a preview first.</p>
                </div>
              </div>
            </div>
          )}

          {step === 3 && (
            <div className="space-y-5">
              <div>
                <h2 className="font-display text-xl font-semibold">Connect an AI model</h2>
                <p className="mt-1 text-sm text-text-2">Use a cloud service with your own API key, or Ollama for fully local processing. You can add more later.</p>
              </div>
              {(providers.data ?? []).length > 0 && (
                <ul className="space-y-2">
                  {providers.data!.map((p) => (
                    <li key={p.id} className="flex items-center gap-3 rounded-md border border-line-1 bg-bg-2 px-3 py-2 text-sm">
                      {p.local ? <Cpu className="size-4 text-accent-teal" aria-hidden /> : <Cloud className="size-4 text-accent" aria-hidden />}
                      <span className="font-medium">{p.label}</span>
                      <span className="ml-auto">
                        <StatusPill tone={p.status === "connected" ? "ok" : p.status === "untested" ? "neutral" : "warn"} label={p.status === "connected" ? "Connected" : p.status.replace(/_/g, " ")} />
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              <AddProviderForm compact />
            </div>
          )}

          {step === 4 && (
            <div className="space-y-5">
              <div>
                <h2 className="font-display text-xl font-semibold">Choose a workspace folder</h2>
                <p className="mt-1 text-sm text-text-2">
                  Atlas can only read and create files inside this folder (plus individual files you explicitly share). It never overwrites existing files, and
                  creating anything asks you first.
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button variant="primary" icon={<FolderOpen className="size-4" aria-hidden />} onClick={async () => { try { await api.useDefaultWorkspace(); toast.success("Workspace ready"); } catch (e) { toast.error(e instanceof AtlasError ? e.message : String(e)); } }}>
                  Use Documents/Atlas Workspace
                </Button>
                <Button onClick={async () => { try { await api.pickWorkspace(); } catch (e) { toast.error(e instanceof AtlasError ? e.message : String(e)); } }}>Choose another folder…</Button>
              </div>
              {workspace && (
                <div className="space-y-3 rounded-lg border border-line-1 bg-bg-2 p-4">
                  <p className="text-sm"><Check className="mr-1 inline size-4 text-ok" aria-hidden />Workspace: <span className="break-all font-mono text-xs">{workspace}</span></p>
                  <div className="flex flex-wrap items-center gap-3">
                    <Button
                      size="sm"
                      variant="subtle"
                      disabled={Boolean(sample)}
                      onClick={async () => {
                        try {
                          setSample(await api.addSampleFile());
                          toast.success("Demo file added");
                        } catch (e) {
                          toast.error(e instanceof AtlasError ? e.message : String(e));
                        }
                      }}
                    >
                      {sample ? "Demo file added" : "Add a sample file (demo data)"}
                    </Button>
                    <span className="text-xs text-text-3">A small, clearly labelled pretend budget for trying file tasks. Delete it any time.</span>
                  </div>
                </div>
              )}
            </div>
          )}

          {step === 5 && (
            <div className="space-y-5">
              <div>
                <h2 className="font-display text-xl font-semibold">Meet the Atlas Map</h2>
                <p className="mt-1 text-sm text-text-2">
                  A living map of everything Atlas can reach — models, tools, memory, projects — drawn from its real state. When a task runs, its path
                  lights up; when something needs setup, the map says so.
                </p>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                {Object.entries(
                  (tools.data ?? []).reduce<Record<string, { total: number; ready: number }>>((acc, t) => {
                    const k = t.category;
                    acc[k] ??= { total: 0, ready: 0 };
                    acc[k].total += 1;
                    if (t.enabled && t.availability.state === "available") acc[k].ready += 1;
                    return acc;
                  }, {}),
                ).map(([cat, v]) => (
                  <div key={cat} className="flex items-center gap-3 rounded-md border border-line-1 bg-bg-2 px-3 py-2.5">
                    <Orbit className="size-4 text-accent" aria-hidden />
                    <span className="text-sm capitalize">{cat}</span>
                    <Badge tone={v.ready === v.total ? "ok" : "warn"} className="ml-auto">
                      {v.ready}/{v.total} ready
                    </Badge>
                  </div>
                ))}
              </div>
              <p className="text-xs text-text-3">Tools marked not ready need setup first (for example, web search needs a search API key).</p>
            </div>
          )}

          {step === 6 && (
            <div className="space-y-5">
              <div>
                <h2 className="font-display text-xl font-semibold">Engineering, costs and siblings</h2>
                <p className="mt-1 text-sm text-text-2">All optional — set them up whenever you like.</p>
              </div>
              <div className="space-y-3">
                <div className="flex gap-3 rounded-md border border-line-1 bg-bg-2 px-4 py-3">
                  <Hammer className="mt-0.5 size-5 shrink-0 text-accent" aria-hidden />
                  <div className="text-sm">
                    <p className="font-medium">Atlas Forge</p>
                    <p className="text-text-2">Work on a code project folder you choose, as Architect, Builder, Debugger or Reconstructor. Every edit, command and commit shows you the exact change and waits for approval, and Atlas can revert its own edits.</p>
                  </div>
                </div>
                <div className="flex gap-3 rounded-md border border-line-1 bg-bg-2 px-4 py-3">
                  <Wallet className="mt-0.5 size-5 shrink-0 text-accent" aria-hidden />
                  <div className="text-sm">
                    <p className="font-medium">Costs and budgets</p>
                    <p className="text-text-2">Cloud models are billed by the provider per token. Atlas estimates each request's cost from a price list that says which rates are verified, and you can set per-request, daily, monthly and per-mission limits in Settings → Usage & budgets.</p>
                  </div>
                </div>
                <div className="flex gap-3 rounded-md border border-[#f5a524]/25 bg-bg-2 px-4 py-3">
                  <PrometheusAvatar state="offline" size={22} birth={false} className="mt-0.5 shrink-0" />
                  <div className="text-sm">
                    <p className="font-medium">Prometheus (optional sibling)</p>
                    <p className="text-text-2">If Prometheus runs on this computer, you can pair it from Siblings. Atlas then can consult it or share missions with it. Only what you put in a mission is shared — never your memory, files, settings or keys — and Atlas works fully without it.</p>
                  </div>
                </div>
              </div>
            </div>
          )}

          {step === 7 && (
            <div className="flex flex-col items-center pt-4 text-center">
              <Emblem size={88} glow />
              <h2 className="mt-6 font-display text-2xl font-semibold">{c.preferred_name ? `You're all set, ${c.preferred_name}.` : "You're all set."}</h2>
              <ul className="mt-6 w-full max-w-md space-y-2 text-left text-sm">
                <li className="flex items-center gap-2"><StatusPill tone={connected ? "ok" : "warn"} label={connected ? "An AI model is connected" : "No model connected yet — add one in Integrations"} /></li>
                <li className="flex items-center gap-2"><StatusPill tone={workspace ? "ok" : "neutral"} label={workspace ? "Workspace folder chosen" : "No workspace — file tools stay off"} /></li>
                <li className="flex items-center gap-2"><StatusPill tone="ok" label="Changes always ask for your approval first" /></li>
                <li className="flex items-center gap-2"><StatusPill tone="neutral" label="Voice is optional and runs on this PC: turn it on later in Settings → Voice (downloads about 95 MB to speak, 150 MB to listen)" /></li>
              </ul>
              <div className="mt-8 flex flex-wrap justify-center gap-2">
                <Button variant="primary" size="lg" disabled={!connected} onClick={() => finish("chat")}>Start your first conversation</Button>
                <Button size="lg" disabled={!connected} onClick={() => finish("task")}>Try a safe tool task</Button>
                <Button size="lg" variant="ghost" onClick={() => finish()}>Go to Home</Button>
              </div>
            </div>
          )}
        </div>

        {step < STEPS.length - 1 && (
          <div className="mt-10 flex items-center justify-between">
            <Button variant="ghost" onClick={back} disabled={step === 0} icon={<ArrowLeft className="size-4" aria-hidden />}>
              Back
            </Button>
            <div className="flex gap-2">
              {(step === 3 || step === 4) && (
                <Button variant="ghost" onClick={next}>
                  Skip for now
                </Button>
              )}
              <Button
                variant="primary"
                onClick={async () => {
                  if (step === 1) {
                    try {
                      await persist();
                    } catch (e) {
                      return void toast.error(e instanceof AtlasError ? e.message : String(e));
                    }
                  }
                  next();
                }}
                icon={<ArrowRight className="size-4" aria-hidden />}
              >
                {step === 0 ? "Get started" : "Continue"}
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
