import { Pause, Play, RotateCcw, Square, Volume2, VolumeX } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { IconButton } from "@/components/ui/primitives";
import { api, AtlasError } from "@/lib/bridge";
import { useVoice, voicePhase, type VoicePhase } from "@/state/voice";
import { useUi } from "@/state/ui";
import { audio } from "./audioEngine";
import { VoiceRing } from "./VoiceRing";

const HEADLINE: Record<VoicePhase, string> = {
  idle: "Voice ready",
  listening: "Listening… click the microphone again when you're done (Esc cancels)",
  transcribing: "Understanding what you said…",
  processing: "Thinking…",
  speaking: "Speaking",
  paused: "Paused",
  interrupted: "Stopped",
  error: "Voice",
  offline: "Voice isn't set up yet",
};

/** The phase, re-evaluated as time passes (the "stopped" state fades after a moment). */
export function useVoicePhase(): VoicePhase {
  const s = useVoice();
  const [, tick] = useState(0);
  useEffect(() => {
    if (performance.now() - s.interruptedAt > 800) return;
    const t = setTimeout(() => tick((n) => n + 1), 750);
    return () => clearTimeout(t);
  }, [s.interruptedAt]);
  return voicePhase(s);
}

/** A compact voice strip above the composer: the ring, what Atlas is doing or saying, and controls. */
export function VoiceBar() {
  const v = useVoice();
  const phase = useVoicePhase();
  const openSettings = useUi((s) => s.openSettings);
  if (!v.settings?.enabled) return null;
  const speaking = v.playback === "speaking" || v.playback === "paused" || v.playback === "processing";
  const muted = !v.settings.speak_responses;
  const toggleMute = async () => {
    try {
      const s = await api.settings();
      if (!muted) audio.stop(false);
      await api.updateSettings({ ...s, voice: { ...s.voice, speak_responses: muted } });
    } catch (e) {
      toast.error(e instanceof AtlasError ? e.message : "Could not change the setting");
    }
  };
  return (
    <div className="mx-auto flex w-full max-w-3xl items-center gap-3 px-6 pb-2" data-voice-bar aria-live="polite">
      <VoiceRing phase={phase} size={52} />
      <div className="min-w-0 flex-1 text-xs">
        <p className="text-text-3">{HEADLINE[phase]}</p>
        {v.caption && phase === "speaking" ? (
          <p className="truncate text-text-1" data-voice-caption>
            {v.caption}
          </p>
        ) : v.error ? (
          <p role="alert" className="text-warn">
            {v.error}{" "}
            <button className="underline underline-offset-2" onClick={v.clearError}>
              Dismiss
            </button>
          </p>
        ) : phase === "offline" ? (
          <button className="text-accent underline underline-offset-2" onClick={() => openSettings("voice")}>
            Set up voice in Settings
          </button>
        ) : null}
      </div>
      {speaking && (
        <>
          {v.playback === "paused" ? (
            <IconButton label="Resume speaking" size="sm" onClick={v.resume}>
              <Play className="size-4" aria-hidden />
            </IconButton>
          ) : (
            <IconButton label="Pause speaking" size="sm" onClick={v.pause} disabled={v.playback !== "speaking"}>
              <Pause className="size-4" aria-hidden />
            </IconButton>
          )}
          <IconButton label="Stop speaking (Esc)" size="sm" onClick={v.stopSpeaking}>
            <Square className="size-4" aria-hidden />
          </IconButton>
        </>
      )}
      {!speaking && audio.lastSpoken.length > 0 && v.status?.tts_ready && (
        <IconButton label="Say that again" size="sm" onClick={v.replay}>
          <RotateCcw className="size-4" aria-hidden />
        </IconButton>
      )}
      {v.status?.tts_ready && (
        <IconButton label={muted ? "Read replies aloud" : "Stop reading replies aloud"} size="sm" onClick={() => void toggleMute()} aria-pressed={!muted}>
          {muted ? <VolumeX className="size-4" aria-hidden /> : <Volume2 className="size-4" aria-hidden />}
        </IconButton>
      )}
    </div>
  );
}
