import { Button, Badge, Panel } from "@/components/ui/primitives";
import { api } from "@/lib/bridge";
import { relativeTime } from "@/lib/format";
import { useAtlasQuery } from "@/lib/query";
import { useUi } from "@/state/ui";

/** Settings → Sibling link: real pairing state, read from the core. */
export function SiblingSettingsSection() {
  const siblings = useAtlasQuery("siblings", api.siblings, ["siblings"]);
  const navigate = useUi((s) => s.navigate);
  const list = siblings.data ?? [];
  return (
    <>
      <p className="mt-1 text-sm text-text-2">
        Atlas can pair with Prometheus, a separately owned assistant on this computer, over an authenticated loopback link (Sibling Protocol v1). Atlas never opens a network listener, and works fully without a sibling.
      </p>
      <Panel className="mt-6 divide-y divide-line-1 px-5">
        {list.length === 0 && <p className="py-4 text-sm text-text-3">No sibling is paired.</p>}
        {list.map((s) => (
          <div key={s.id} className="flex flex-wrap items-center gap-3 py-4">
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">{s.name}</p>
              <p className="font-mono text-[0.68rem] text-text-3">{s.endpoint} · last verified {s.last_seen_at ? relativeTime(s.last_seen_at) : "never"}</p>
              {s.last_error && <p className="text-xs text-err">{s.last_error}</p>}
            </div>
            {s.status === "revoked" ? <Badge>unpaired</Badge> : s.connected ? <Badge tone="ok">connected</Badge> : <Badge tone="err">not connected</Badge>}
          </div>
        ))}
        <div className="flex flex-wrap items-center gap-3 py-4">
          <p className="min-w-0 flex-1 text-xs text-text-3">What is shared: only the objective, the context you type into a mission, and your replies. Never memory, files, conversation history, settings or API keys.</p>
          <Button size="sm" variant="secondary" onClick={() => navigate("siblings")}>Open Siblings</Button>
        </div>
      </Panel>
    </>
  );
}
