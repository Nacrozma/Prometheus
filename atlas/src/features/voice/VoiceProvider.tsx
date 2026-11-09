import { useEffect } from "react";
import { api } from "@/lib/bridge";
import { useAtlasQuery } from "@/lib/query";
import { onTurnEvent } from "@/state/turns";
import { useVoice } from "@/state/voice";
import { audio } from "./audioEngine";
import { SentenceStream } from "./speechText";

/**
 * Mounted once in the shell: keeps the voice state in step with settings and installed files,
 * speaks replies as they stream (when "read replies aloud" is on), and owns the voice shortcuts.
 * Ctrl/⌘+Shift+Space starts and stops listening. Esc cancels listening, otherwise stops speech,
 * and only then reaches the existing "stop the reply" shortcut.
 */
export function VoiceProvider() {
  const settings = useAtlasQuery("settings", api.settings, ["settings"]);
  const status = useAtlasQuery("voice-status", api.voiceStatus, ["settings"]);

  useEffect(() => {
    if (settings.data) useVoice.getState().setSettings(settings.data.voice);
  }, [settings.data]);
  useEffect(() => {
    if (status.data) useVoice.getState().setStatus(status.data);
  }, [status.data]);

  // Read replies aloud as they stream: complete sentences are spoken while the rest is written.
  useEffect(() => {
    const streams = new Map<string, SentenceStream>();
    return onTurnEvent((cid, e) => {
      const v = useVoice.getState();
      const on = Boolean(v.settings?.enabled && v.settings.speak_responses && v.status?.tts_ready);
      if (e.type === "finished") {
        const s = streams.get(cid);
        streams.delete(cid);
        v.setAwaitingReply(false);
        if (!on || !s) return;
        if (e.outcome === "completed") {
          audio.enqueue(s.flush());
          audio.endReply();
        } else {
          // Stopped or failed: say nothing more.
          audio.stop(false);
        }
        return;
      }
      if (!on) return;
      if (e.type === "started") {
        streams.set(cid, new SentenceStream());
        audio.beginReply();
      } else if (e.type === "text_delta") {
        let s = streams.get(cid);
        if (!s) {
          s = new SentenceStream();
          streams.set(cid, s);
          audio.beginReply();
        }
        audio.enqueue(s.push(e.text));
      } else if (e.type === "step_reset") {
        // The text streamed so far is being replaced; stop speaking it.
        streams.get(cid)?.reset();
        audio.stop(false);
        audio.beginReply();
      }
    });
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const v = useVoice.getState();
      if (e.key === " " && e.shiftKey && (e.ctrlKey || e.metaKey)) {
        if (!v.settings?.enabled) return;
        e.preventDefault();
        audio.context();
        void v.toggleListening();
      } else if (e.key === "Escape" && !document.querySelector("[data-first-launch]")) {
        if (v.capture !== "off") {
          e.preventDefault();
          e.stopImmediatePropagation();
          v.cancelListening();
        } else if (v.playback !== "idle") {
          e.preventDefault();
          e.stopImmediatePropagation();
          v.stopSpeaking();
        }
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, []);

  // Test builds expose what the voice measured, for end-to-end checks (stand-in engines only).
  useEffect(() => {
    if (!status.data?.fixtures) return;
    (window as unknown as { __atlasVoice?: unknown }).__atlasVoice = {
      level: () => audio.level(),
      playback: () => audio.state,
      capturing: () => audio.capturing,
      micLost: (reason: string) => audio.onCaptureLost?.(reason),
    };
  }, [status.data?.fixtures]);

  return null;
}
