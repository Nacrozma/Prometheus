import { listen } from "@tauri-apps/api/event";
import { useEffect } from "react";
import { toast } from "sonner";
import { audio } from "@/features/voice/audioEngine";
import { api } from "@/lib/bridge";
import { onChange } from "@/lib/events";
import { useUi } from "@/state/ui";
import { useVoice } from "@/state/voice";

/** Put the caret in the message box once the Companion has rendered. */
function focusComposer(tries = 20) {
  const el = document.getElementById("composer") as HTMLTextAreaElement | null;
  if (el) return el.focus();
  if (tries > 0) setTimeout(() => focusComposer(tries - 1), 50);
}

/** What happens when the owner summons Atlas (global shortcut, tray, or a second launch). */
export function onSummon(listenRequested: boolean) {
  if (document.querySelector("[data-first-launch]")) return; // never cut the introduction short
  const ui = useUi.getState();
  ui.setPalette(false);
  if (ui.route !== "companion") ui.navigate("companion");
  const v = useVoice.getState();
  if (listenRequested && v.settings?.enabled && v.status?.stt_ready && v.capture === "off") {
    audio.context();
    void v.startListening();
  } else {
    focusComposer();
  }
}

/** Mounted once in the shell: reacts to summons and keeps notifications in step with what is on screen. */
export function PresenceProvider() {
  useEffect(() => {
    let off: (() => void) | null = null;
    let gone = false;
    void listen<{ listen?: boolean }>("atlas://summon", (e) => onSummon(Boolean(e.payload?.listen)))
      .then((un) => {
        if (gone) un();
        else off = un;
      })
      .catch(() => {});
    return () => {
      gone = true;
      off?.();
    };
  }, []);

  // A reminder that arrives while Atlas is open is shown right here, with Done and Snooze.
  useEffect(() => {
    const since = new Date().toISOString();
    const shown = new Set<string>();
    const check = () =>
      void api
        .notifications(10)
        .then(({ items }) => {
          for (const n of items) {
            if (n.read_at || n.created_at < since || shown.has(n.id)) continue;
            // Held by Focus Mode: no toast now, and none in a burst when the session ends (its
            // summary says what waited; the bell lists them).
            if (n.held) {
              shown.add(n.id);
              continue;
            }
            if (n.category === "focus") {
              // The end of a focus session: what happened, and where the held notifications are.
              shown.add(n.id);
              toast(n.title, { id: `focus-${n.id}`, description: n.detail, duration: 15_000 });
              continue;
            }
            if (n.category !== "reminder" && n.category !== "deadline") continue;
            shown.add(n.id);
            const id = n.target.startsWith("todo:") ? n.target.slice(5) : null;
            const read = () => void api.notificationsMarkRead({ id: n.id }).catch(() => {});
            toast(n.title, {
              id: `reminder-${n.id}`,
              description: n.detail,
              duration: 30_000,
              ...(id
                ? {
                    action: { label: "Done", onClick: () => (read(), void api.todoSetStatus(id, "done").catch(() => toast.error("The task could not be completed"))) },
                    cancel: { label: "Snooze 10 min", onClick: () => (read(), void api.todoSnooze(id, 10).catch(() => toast.error("The reminder could not be snoozed"))) },
                  }
                : { action: { label: "Open tasks", onClick: () => (read(), useUi.getState().navigate("tasks")) } }),
            });
          }
        })
        .catch(() => {});
    return onChange((topic) => {
      if (topic === "notifications") check();
    });
  }, []);

  // Opening a conversation clears the notices about it.
  const conversation = useUi((s) => (s.route === "companion" ? s.activeConversationId : null));
  useEffect(() => {
    if (conversation) void api.notificationsMarkRead({ target: `conversation:${conversation}` }).catch(() => {});
  }, [conversation]);

  return null;
}
