import { create } from "zustand";
import { audio, type PlaybackState } from "@/features/voice/audioEngine";
import { splitSentences, toSpeech } from "@/features/voice/speechText";
import { api, AtlasError } from "@/lib/bridge";
import type { Settings, VoiceStatus } from "@/lib/schemas";

export type VoicePhase = "idle" | "listening" | "transcribing" | "processing" | "speaking" | "paused" | "interrupted" | "error" | "offline";

interface VoiceStore {
  status: VoiceStatus | null;
  settings: Settings["voice"] | null;
  capture: "off" | "listening" | "transcribing";
  playback: PlaybackState;
  caption: string;
  error: string | null;
  /** A recognised request for the composer (nonce changes each time). */
  draft: { text: string; nonce: number } | null;
  /** Atlas is answering a request that was spoken. */
  awaitingReply: boolean;
  interruptedAt: number;
  setStatus: (s: VoiceStatus) => void;
  setSettings: (v: Settings["voice"]) => void;
  startListening: () => Promise<void>;
  stopListening: () => Promise<void>;
  cancelListening: () => void;
  toggleListening: () => Promise<void>;
  stopSpeaking: () => void;
  pause: () => void;
  resume: () => void;
  speakText: (markdown: string) => void;
  replay: () => void;
  setAwaitingReply: (on: boolean) => void;
  clearError: () => void;
}

let nonce = 0;

export const useVoice = create<VoiceStore>((set, get) => {
  audio.subscribe(() => set({ playback: audio.state, caption: audio.caption, interruptedAt: audio.interruptedAt, ...(audio.error ? { error: audio.error } : {}) }));
  audio.onCaptureLost = (reason) => {
    if (reason.startsWith("Recordings are limited")) void get().stopListening().then(() => set({ error: reason }));
    else {
      audio.cancelCapture();
      set({ capture: "off", error: reason });
    }
  };
  return {
    status: null,
    settings: null,
    capture: "off",
    playback: "idle",
    caption: "",
    error: null,
    draft: null,
    awaitingReply: false,
    interruptedAt: 0,
    setStatus: (status) => set({ status }),
    setSettings: (v) => {
      audio.setVolume(v.volume / 100);
      audio.speed = v.speed;
      set({ settings: v });
    },
    startListening: async () => {
      const { status, settings, capture } = get();
      if (capture !== "off") return;
      if (!settings?.enabled) return set({ error: "Voice is off. Turn it on in Settings → Voice." });
      if (!status?.stt_ready) return set({ error: "Speech recognition isn't set up yet. Download the engine and a model in Settings → Voice." });
      set({ error: null });
      try {
        await audio.startCapture({ deviceId: settings.input_device, fixture: status.fixtures });
        set({ capture: "listening" });
      } catch (e) {
        set({ capture: "off", error: e instanceof AtlasError ? e.message : "The microphone could not be started." });
      }
    },
    stopListening: async () => {
      if (get().capture !== "listening") return;
      const pcm = audio.stopCapture();
      set({ capture: "transcribing" });
      try {
        const t = await api.voiceTranscribe(pcm, 16_000);
        pcm.fill(0);
        if (get().capture !== "transcribing") return; // cancelled meanwhile
        if (!t.text.trim()) set({ capture: "off", error: "I didn't catch anything. Try again a little closer to the microphone." });
        else set({ capture: "off", draft: { text: t.text.trim(), nonce: ++nonce } });
      } catch (e) {
        pcm.fill(0);
        if (e instanceof AtlasError && e.code === "cancelled") return set({ capture: "off" });
        set({ capture: "off", error: e instanceof AtlasError ? e.message : "Speech recognition failed." });
      }
    },
    cancelListening: () => {
      const c = get().capture;
      if (c === "listening") audio.cancelCapture();
      if (c === "transcribing") void api.voiceCancelTranscription().catch(() => {});
      set({ capture: "off" });
    },
    toggleListening: async () => {
      if (get().capture === "listening") await get().stopListening();
      else if (get().capture === "off") await get().startListening();
    },
    stopSpeaking: () => {
      audio.stop(true);
      set({ awaitingReply: false });
    },
    pause: () => audio.pause(),
    resume: () => audio.resume(),
    speakText: (markdown) => {
      const { status } = get();
      if (!status?.tts_ready) return set({ error: "Speech output isn't set up yet. Download the engine and a voice in Settings → Voice." });
      set({ error: null });
      audio.speak(splitSentences(toSpeech(markdown)));
    },
    replay: () => {
      if (audio.lastSpoken.length) audio.speak([...audio.lastSpoken]);
    },
    setAwaitingReply: (awaitingReply) => set({ awaitingReply }),
    clearError: () => set({ error: null }),
  };
});

/** The single state the voice ring shows. */
export function voicePhase(s: Pick<VoiceStore, "status" | "settings" | "capture" | "playback" | "error" | "awaitingReply" | "interruptedAt">, now = performance.now()): VoicePhase {
  if (s.capture === "listening") return "listening";
  if (s.capture === "transcribing") return "transcribing";
  if (s.playback === "speaking") return "speaking";
  if (s.playback === "paused") return "paused";
  if (s.playback === "processing" || s.awaitingReply) return "processing";
  if (now - s.interruptedAt < 700) return "interrupted";
  if (s.error) return "error";
  if (!s.settings?.enabled || !s.status || (!s.status.tts_ready && !s.status.stt_ready)) return "offline";
  return "idle";
}
