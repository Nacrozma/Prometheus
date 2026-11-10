import { listen } from "@tauri-apps/api/event";
import { useEffect } from "react";
import { audio } from "@/features/voice/audioEngine";
import { api } from "@/lib/bridge";
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

  // Opening a conversation clears the notices about it.
  const conversation = useUi((s) => (s.route === "companion" ? s.activeConversationId : null));
  useEffect(() => {
    if (conversation) void api.notificationsMarkRead({ target: `conversation:${conversation}` }).catch(() => {});
  }, [conversation]);

  return null;
}
