import { Bell } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button, Tooltip } from "@/components/ui/primitives";
import { api } from "@/lib/bridge";
import { cn } from "@/lib/format";
import { useAtlasQuery } from "@/lib/query";
import type { AtlasNotification } from "@/lib/schemas";
import { useUi } from "@/state/ui";

const CATEGORY: Record<AtlasNotification["category"], string> = { approval: "Approval", reply: "Reply", mission: "Mission", error: "Problem", reminder: "Reminder", deadline: "Due today", briefing: "Briefing", focus: "Focus", test: "Test" };

function when(iso: string): string {
  const t = new Date(iso);
  if (Number.isNaN(t.getTime())) return "";
  const mins = Math.round((Date.now() - t.getTime()) / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  if (mins < 60 * 24) return `${Math.round(mins / 60)} h ago`;
  return t.toLocaleDateString();
}

/** Open the thing a notification is about. */
export function openTarget(target: string) {
  const ui = useUi.getState();
  if (target.startsWith("conversation:")) ui.openConversation(target.slice("conversation:".length));
  else if (target.startsWith("mission:")) ui.navigate("siblings");
  else if (target === "approvals") ui.navigate("mission");
  else if (target.startsWith("todo:")) ui.openTodo(target.slice("todo:".length));
  else if (target === "tasks") ui.navigate("tasks");
}

/** The bell in the rail: Atlas's own notification list. It works whether or not system notifications are on. */
export function NotificationBell() {
  const list = useAtlasQuery("notifications", () => api.notifications(50), ["notifications"]);
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const unread = list.data?.unread ?? 0;
  const items = list.data?.items ?? [];

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        setOpen(false);
      }
    };
    const onDown = (e: MouseEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("keydown", onKey, true);
    window.addEventListener("mousedown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      window.removeEventListener("mousedown", onDown);
    };
  }, [open]);

  const pick = (n: AtlasNotification) => {
    void api.notificationsMarkRead({ id: n.id }).catch(() => {});
    setOpen(false);
    openTarget(n.target);
  };

  return (
    <div ref={root} className="relative">
      <Tooltip label={unread ? `Notifications (${unread} new)` : "Notifications"}>
        <button
          onClick={() => setOpen((o) => !o)}
          aria-label={unread ? `Notifications (${unread} unread)` : "Notifications"}
          aria-expanded={open}
          aria-haspopup="dialog"
          data-bell
          data-unread={unread}
          className={cn("relative grid size-11 place-items-center rounded-md transition-colors", open ? "bg-accent-soft text-accent-strong" : "text-text-3 hover:bg-bg-3 hover:text-text-1")}
        >
          <Bell className="size-[1.15rem]" strokeWidth={1.75} aria-hidden />
        </button>
      </Tooltip>
      {/* The count sits beside the button, not inside it, so the button's name is exactly its label. */}
      {unread > 0 && (
        <span aria-hidden className="pointer-events-none absolute -right-0.5 -top-0.5 grid min-w-4 place-items-center rounded-full bg-accent px-1 text-[0.625rem] font-bold leading-4 text-text-inverse">
          {unread > 9 ? "9+" : unread}
        </span>
      )}
      {open && (
        <div
          role="dialog"
          aria-label="Notifications"
          data-notification-panel
          className="absolute bottom-0 left-[calc(100%+0.75rem)] z-40 flex max-h-[28rem] w-80 flex-col rounded-lg border border-line-2 bg-bg-2 shadow-xl"
        >
          <div className="flex items-center justify-between gap-2 border-b border-line-1 px-3 py-2">
            <p className="text-sm font-medium text-text-1">Notifications</p>
            <div className="flex items-center gap-1">
              <Button size="sm" variant="ghost" disabled={unread === 0} onClick={() => void api.notificationsMarkRead().catch(() => {})}>
                Mark all read
              </Button>
              <Button size="sm" variant="ghost" disabled={items.length === 0} onClick={() => void api.notificationsClear().catch(() => {})}>
                Clear
              </Button>
            </div>
          </div>
          {items.length === 0 ? (
            <p className="px-3 py-6 text-center text-xs text-text-3">Nothing yet. Approvals, finished replies and mission updates appear here.</p>
          ) : (
            <ul className="min-h-0 flex-1 overflow-y-auto py-1">
              {items.map((n) => (
                <li key={n.id}>
                  <button
                    onClick={() => pick(n)}
                    data-notification={n.category}
                    data-read={n.read_at ? "true" : "false"}
                    className="flex w-full flex-col gap-0.5 px-3 py-2 text-left hover:bg-bg-3 focus-visible:bg-bg-3"
                  >
                    <span className="flex items-center gap-2 text-xs">
                      {!n.read_at && <span aria-hidden className="size-1.5 shrink-0 rounded-full bg-accent" />}
                      <span className={cn("min-w-0 flex-1 truncate", n.read_at ? "text-text-2" : "font-medium text-text-1")}>{n.title}</span>
                      <span className="shrink-0 text-[0.6875rem] text-text-3">{when(n.created_at)}</span>
                    </span>
                    <span className="truncate text-[0.6875rem] text-text-3">
                      {CATEGORY[n.category]}
                      {n.held ? " · waiting for Focus to end" : ""}
                      {n.detail ? ` · ${n.detail}` : ""}
                      {n.read_at ? "" : " · unread"}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <button className="border-t border-line-1 px-3 py-2 text-left text-xs text-text-3 hover:text-text-1" onClick={() => (setOpen(false), useUi.getState().openSettings("desktop"))}>
            Notification settings…
          </button>
        </div>
      )}
    </div>
  );
}
