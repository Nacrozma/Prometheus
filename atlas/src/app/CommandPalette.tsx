import { Command } from "cmdk";
import { Download, HeartPulse, MessageSquarePlus, Octagon, Search, Settings2, Wrench } from "lucide-react";
import { toast } from "sonner";
import { api, AtlasError } from "@/lib/bridge";
import { useAtlasQuery } from "@/lib/query";
import { useUi, type SettingsSection } from "@/state/ui";
import { emergencyStop, NAV } from "./Rail";

/** Start a conversation. Without an explicit project, the default project from Settings applies. */
export async function newConversation(projectId?: string | null) {
  const project = projectId === undefined ? (await api.settings()).default_project_id : projectId;
  const c = await api.createConversation(project);
  useUi.getState().openConversation(c.id);
}

const SETTINGS: { section: SettingsSection; label: string }[] = [
  { section: "companion", label: "Companion & personality" },
  { section: "models", label: "Models & routing" },
  { section: "permissions", label: "Tool permissions" },
  { section: "memory", label: "Memory" },
  { section: "appearance", label: "Appearance & accessibility" },
  { section: "files", label: "File workspace" },
  { section: "limits", label: "Limits & network" },
  { section: "usage", label: "Usage & costs" },
  { section: "data", label: "Data, backups & privacy" },
  { section: "diagnostics", label: "Diagnostics" },
  { section: "shortcuts", label: "Keyboard shortcuts" },
  { section: "about", label: "About ATLAS" },
];

const item =
  "flex cursor-pointer items-center gap-2.5 rounded-sm px-2.5 py-2 text-sm text-text-2 data-[selected=true]:bg-bg-4 data-[selected=true]:text-text-1";

export function CommandPalette() {
  const open = useUi((s) => s.paletteOpen);
  const setOpen = useUi((s) => s.setPalette);
  const ui = useUi();
  const convs = useAtlasQuery("palette-convs", () => (open ? api.conversations({ limit: 12 }) : Promise.resolve([])), ["conversations"]);
  const tools = useAtlasQuery("palette-tools", () => (open ? api.tools() : Promise.resolve([])), ["registry"]);
  const projects = useAtlasQuery("palette-projects", () => (open ? api.projects(false) : Promise.resolve([])), ["projects"]);

  const run = (fn: () => void | Promise<void>) => async () => {
    setOpen(false);
    try {
      await fn();
    } catch (e) {
      toast.error(e instanceof AtlasError ? e.message : "That action failed");
    }
  };

  return (
    <Command.Dialog
      open={open}
      onOpenChange={setOpen}
      label="Command palette"
      className="fixed left-1/2 top-[14vh] z-50 w-[min(640px,calc(100vw-2rem))] -translate-x-1/2 overflow-hidden rounded-xl border border-line-2 bg-bg-2 shadow-3 anim-rise"
      overlayClassName="fixed inset-0 z-40 bg-[color:var(--bg-overlay)]"
    >
      <div className="flex items-center gap-2 border-b border-line-1 px-4">
        <Search className="size-4 text-text-3" aria-hidden />
        <Command.Input placeholder="Type a command or search…" className="h-12 flex-1 bg-transparent text-sm text-text-1 outline-none placeholder:text-text-3" />
      </div>
      <Command.List className="max-h-[52vh] overflow-y-auto p-2">
        <Command.Empty className="px-3 py-6 text-center text-sm text-text-3">No matching commands.</Command.Empty>
        <Command.Group heading="Actions" className="px-1 text-[0.6875rem] text-text-3 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5">
          <Command.Item className={item} onSelect={run(() => newConversation())}>
            <MessageSquarePlus className="size-4" aria-hidden /> New conversation
          </Command.Item>
          <Command.Item className={item} onSelect={run(emergencyStop)}>
            <Octagon className="size-4 text-err" aria-hidden /> Pause all active execution (emergency stop)
          </Command.Item>
          <Command.Item
            className={item}
            onSelect={run(async () => {
              const providers = await api.providers();
              if (!providers.length) return void toast("No AI providers are configured yet.");
              for (const p of providers) {
                const r = await api.testProvider(p.id);
                (r.ok ? toast.success : toast.error)(`${p.label}: ${r.message}`);
              }
            })}
          >
            <HeartPulse className="size-4" aria-hidden /> Check provider health
          </Command.Item>
          <Command.Item
            className={item}
            onSelect={run(async () => {
              const path = await api.exportAll();
              if (path) toast.success(`Exported to ${path}`);
            })}
          >
            <Download className="size-4" aria-hidden /> Export all data…
          </Command.Item>
        </Command.Group>
        <Command.Group heading="Go to" className="px-1 text-[0.6875rem] text-text-3 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5">
          {NAV.map((n) => (
            <Command.Item key={n.route} className={item} onSelect={run(() => ui.navigate(n.route))} keywords={[n.route]}>
              <n.icon className="size-4" aria-hidden /> {n.label}
              {n.shortcut && <span className="ml-auto text-[0.6875rem] text-text-3">Ctrl {n.shortcut}</span>}
            </Command.Item>
          ))}
        </Command.Group>
        {(convs.data?.length ?? 0) > 0 && (
          <Command.Group heading="Recent conversations" className="px-1 text-[0.6875rem] text-text-3 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5">
            {convs.data!.map((c) => (
              <Command.Item key={c.id} className={item} value={`conversation ${c.title} ${c.id}`} onSelect={run(() => ui.openConversation(c.id))}>
                {c.title}
              </Command.Item>
            ))}
          </Command.Group>
        )}
        {(projects.data?.length ?? 0) > 0 && (
          <Command.Group heading="Projects" className="px-1 text-[0.6875rem] text-text-3 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5">
            {projects.data!.map((p) => (
              <Command.Item key={p.id} className={item} value={`project ${p.name} ${p.id}`} onSelect={run(() => newConversation(p.id))}>
                New conversation in {p.name}
              </Command.Item>
            ))}
          </Command.Group>
        )}
        <Command.Group heading="Tools" className="px-1 text-[0.6875rem] text-text-3 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5">
          {(tools.data ?? []).map((t) => (
            <Command.Item key={t.id} className={item} value={`tool ${t.name} ${t.id}`} onSelect={run(() => ui.openMapNode(`tool:${t.id}`))}>
              <Wrench className="size-4" aria-hidden /> {t.name} <span className="ml-auto font-mono text-[0.6875rem] text-text-3">{t.id}</span>
            </Command.Item>
          ))}
        </Command.Group>
        <Command.Group heading="Settings" className="px-1 text-[0.6875rem] text-text-3 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5">
          {SETTINGS.map((s) => (
            <Command.Item key={s.section} className={item} value={`settings ${s.label}`} onSelect={run(() => ui.openSettings(s.section))}>
              <Settings2 className="size-4" aria-hidden /> {s.label}
            </Command.Item>
          ))}
        </Command.Group>
      </Command.List>
    </Command.Dialog>
  );
}
