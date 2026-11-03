import { Cloud, Cpu } from "lucide-react";
import { Select } from "@/components/ui/primitives";
import { api } from "@/lib/bridge";
import { useAtlasQuery } from "@/lib/query";

export interface ModelChoice {
  providerId: string | null;
  model: string | null;
}

/** Per-conversation provider/model override. "Default" defers to Settings → Models. */
export function ModelPicker({ value, onChange }: { value: ModelChoice; onChange: (v: ModelChoice) => void }) {
  const providers = useAtlasQuery("providers", api.providers, ["providers"]);
  const settings = useAtlasQuery("settings", api.settings, ["settings"]);
  const list = (providers.data ?? []).filter((p) => p.enabled);
  const effectiveProvider = list.find((p) => p.id === (value.providerId ?? settings.data?.default_provider_id)) ?? list[0];
  const options: { key: string; label: string; providerId: string | null; model: string | null }[] = [
    { key: "default", label: "Default model", providerId: null, model: null },
  ];
  for (const p of list) {
    const ids = new Set<string>();
    if (p.default_model) ids.add(p.default_model);
    for (const m of p.models.slice(0, 40)) ids.add(m.id);
    for (const id of ids) {
      const name = p.models.find((m) => m.id === id)?.display_name ?? id;
      options.push({ key: `${p.id}::${id}`, label: `${p.label} — ${name}`, providerId: p.id, model: id });
    }
  }
  const current = value.providerId && value.model ? `${value.providerId}::${value.model}` : "default";
  return (
    <div className="flex items-center gap-2">
      {effectiveProvider && (
        <span
          className="inline-flex items-center gap-1 rounded-xs border border-line-2 px-1.5 py-0.5 text-[0.6875rem] text-text-2"
          title={effectiveProvider.local ? "Processed on this computer" : `Sent to ${effectiveProvider.label}`}
        >
          {effectiveProvider.local ? <Cpu className="size-3" aria-hidden /> : <Cloud className="size-3" aria-hidden />}
          {effectiveProvider.local ? "Local" : "Cloud"}
        </span>
      )}
      <Select
        aria-label="Model for this conversation"
        className="h-8 max-w-64 text-xs"
        value={current}
        onChange={(e) => {
          const o = options.find((x) => x.key === e.target.value);
          onChange({ providerId: o?.providerId ?? null, model: o?.model ?? null });
        }}
      >
        {options.map((o) => (
          <option key={o.key} value={o.key}>
            {o.label}
          </option>
        ))}
      </Select>
    </div>
  );
}
