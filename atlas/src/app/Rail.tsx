import { Activity, Brain, ListTodo, Cable, Hammer, FolderKanban, FolderOpen, Home, Library, MessageSquareText, Mic, Octagon, Orbit, Plug, Settings2 } from "lucide-react";
import { toast } from "sonner";
import { Emblem } from "@/components/Emblem";
import { NotificationBell } from "@/features/desktop/NotificationBell";
import { Tooltip } from "@/components/ui/primitives";
import { api } from "@/lib/bridge";
import { cn } from "@/lib/format";
import { useAtlasQuery } from "@/lib/query";
import { useTurns } from "@/state/turns";
import { useUi, type Route } from "@/state/ui";

export const NAV: { route: Route; label: string; icon: typeof Home; shortcut: string }[] = [
  { route: "home", label: "Home", icon: Home, shortcut: "1" },
  { route: "companion", label: "Companion", icon: MessageSquareText, shortcut: "2" },
  { route: "tasks", label: "Tasks", icon: ListTodo, shortcut: "" },
  { route: "map", label: "Atlas Map", icon: Orbit, shortcut: "3" },
  { route: "forge", label: "Atlas Forge", icon: Hammer, shortcut: "4" },
  { route: "siblings", label: "Siblings", icon: Cable, shortcut: "" },
  { route: "mission", label: "Mission Control", icon: Activity, shortcut: "5" },
  { route: "projects", label: "Projects", icon: FolderKanban, shortcut: "6" },
  { route: "memory", label: "Memory", icon: Brain, shortcut: "7" },
  { route: "files", label: "Files", icon: FolderOpen, shortcut: "8" },
  { route: "vault", label: "Knowledge Vault", icon: Library, shortcut: "" },
  { route: "integrations", label: "Integrations", icon: Plug, shortcut: "9" },
  { route: "voice", label: "Voice", icon: Mic, shortcut: "" },
];

export async function emergencyStop() {
  try {
    const n = await api.emergencyStop();
    toast.warning(n > 0 ? `Stopped ${n} running ${n === 1 ? "task" : "tasks"}. Pending approvals were cancelled.` : "Nothing was running. Pending approvals were cleared.");
  } catch {
    toast.error("Emergency stop failed");
  }
}

export function Rail() {
  const route = useUi((s) => s.route);
  const navigate = useUi((s) => s.navigate);
  const running = useTurns((s) => Object.values(s.byConversation).some((t) => t.running));
  const approvals = useAtlasQuery("approvals", api.pendingApprovals, ["approvals"]);
  const pending = approvals.data?.length ?? 0;

  const item = (r: Route, label: string, Icon: typeof Home, shortcut?: string, badge?: number) => {
    const active = route === r;
    return (
      <Tooltip key={r} label={<span>{label}{shortcut && <span className="ml-2 text-text-3">Ctrl {shortcut}</span>}</span>}>
        <button
          onClick={() => navigate(r)}
          aria-label={badge ? `${label} (${badge} waiting for approval)` : label}
          aria-current={active ? "page" : undefined}
          className={cn(
            "group relative grid size-11 place-items-center rounded-md transition-colors duration-[var(--dur-fast)]",
            active ? "bg-accent-soft text-accent-strong" : "text-text-3 hover:bg-bg-3 hover:text-text-1",
          )}
        >
          <span aria-hidden className={cn("absolute -left-[13px] h-5 w-[3px] rounded-r-full bg-accent transition-opacity", active ? "opacity-100" : "opacity-0")} />
          <Icon className="size-[1.15rem]" strokeWidth={1.75} aria-hidden />
          {badge ? (
            <span aria-hidden className="absolute -right-0.5 -top-0.5 grid min-w-4 place-items-center rounded-full bg-warn px-1 text-[0.625rem] font-bold leading-4 text-text-inverse">
              {badge}
            </span>
          ) : null}
        </button>
      </Tooltip>
    );
  };

  return (
    <nav aria-label="Main" className="flex h-full w-[var(--rail-width)] shrink-0 flex-col items-center gap-1.5 border-r border-line-1 bg-bg-0/70 py-4">
      <button aria-label="ATLAS home" onClick={() => navigate("home")} className="mb-3 rounded-md p-1">
        <Emblem size={34} animated={running} glow={running} />
      </button>
      {NAV.map((n) => item(n.route, n.label, n.icon, n.shortcut, n.route === "mission" ? pending : undefined))}
      <div className="mt-auto flex flex-col items-center gap-1.5">
        <NotificationBell />
        <Tooltip label={running ? "Emergency stop: cancel all running tasks" : "Emergency stop (nothing running)"}>
          <button
            onClick={emergencyStop}
            aria-label="Emergency stop"
            className={cn(
              "grid size-11 place-items-center rounded-md transition-colors",
              running ? "bg-err-soft text-err hover:bg-[color:var(--err)]/25" : "text-text-3 hover:bg-bg-3 hover:text-text-1",
            )}
          >
            <Octagon className="size-[1.15rem]" strokeWidth={1.75} aria-hidden />
          </button>
        </Tooltip>
        {item("settings", "Settings", Settings2, ",")}
      </div>
    </nav>
  );
}
