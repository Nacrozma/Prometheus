import { Keyboard, Mic, Settings2, ShieldCheck, Square, Volume2 } from "lucide-react";
import { Badge, Button, PageHeader, Panel, StatusPill } from "@/components/ui/primitives";
import { useUi } from "@/state/ui";
import { useVoice } from "@/state/voice";
import { audio } from "./audioEngine";
import { mb } from "./VoiceSettings";
import { useVoicePhase } from "./VoiceBar";
import { VoiceRing } from "./VoiceRing";

/**
 * The voice hub: Atlas's electric-blue ring at full size, what is set up, and a place to try it.
 * Configuration lives in Settings → Voice. Recognised speech from here goes to the Companion as an
 * ordinary message box entry, so voice and text share one conversation pipeline.
 */
export function VoicePage() {
  const navigate = useUi((s) => s.navigate);
  const openSettings = useUi((s) => s.openSettings);
  const v = useVoice();
  const phase = useVoicePhase();
  const st = v.status;
  const enabled = Boolean(v.settings?.enabled);

  return (
    <div className="h-full overflow-y-auto">
      <PageHeader
        eyebrow="Interaction"
        title="Voice"
        subtitle="Talk to Atlas with push-to-talk and hear it answer, entirely on this computer. Typing always works too."
        actions={<Button variant="subtle" icon={<Settings2 className="size-4" aria-hidden />} onClick={() => openSettings("voice")}>Voice settings</Button>}
      />
      <div className="grid gap-5 px-8 py-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Panel className="flex flex-col items-center gap-4 p-6 text-center">
          <VoiceRing phase={phase} size={220} />
          <p className="min-h-5 text-sm text-text-2" aria-live="polite">
            {v.caption && phase === "speaking" ? v.caption : v.error ? v.error : phase === "offline" ? "Voice isn't set up yet." : phase === "listening" ? "Listening…" : phase === "transcribing" ? "Understanding…" : ""}
          </p>
          <div className="flex flex-wrap justify-center gap-2">
            <Button
              variant={v.capture === "listening" ? "danger" : "primary"}
              icon={<Mic className="size-4" aria-hidden />}
              disabled={!enabled || !st?.stt_ready || v.capture === "transcribing"}
              onClick={async () => {
                audio.context();
                const wasListening = v.capture === "listening";
                await v.toggleListening();
                if (wasListening && useVoice.getState().draft) navigate("companion");
              }}
            >
              {v.capture === "listening" ? "Finish" : "Talk"}
            </Button>
            <Button
              icon={<Volume2 className="size-4" aria-hidden />}
              disabled={!enabled || !st?.tts_ready}
              onClick={() => {
                audio.context();
                v.speakText("Hello. I'm Atlas. It's good to hear from you.");
              }}
            >
              Preview voice
            </Button>
            {(v.playback === "speaking" || v.playback === "processing" || v.playback === "paused") && (
              <Button variant="ghost" icon={<Square className="size-4" aria-hidden />} onClick={v.stopSpeaking}>
                Stop
              </Button>
            )}
          </div>
          <p className="text-[0.6875rem] text-text-3">Push-to-talk: press Talk (or Ctrl+Shift+Space), speak, then press again. What you said appears in the Companion's message box for you to send.</p>
        </Panel>
        <div className="space-y-5">
          <Panel className="space-y-3 p-5">
            <h2 className="font-semibold">What's set up</h2>
            {!st ? (
              <p className="text-sm text-text-3">Checking…</p>
            ) : (
              <>
                <div className="flex flex-wrap gap-2 text-xs">
                  <StatusPill tone={enabled ? "ok" : "neutral"} label={enabled ? "Voice on" : "Voice off"} />
                  <StatusPill tone={st.tts_ready ? "ok" : "neutral"} label={st.tts_ready ? `Speaks with ${st.voices.find((x) => x.id === st.selected_voice)?.name ?? "a voice"}` : "Speech output not set up"} />
                  <StatusPill tone={st.stt_ready ? "ok" : "neutral"} label={st.stt_ready ? `Understands with ${st.stt_models.find((x) => x.id === st.selected_stt_model)?.name ?? "a model"}` : "Speech recognition not set up"} />
                  {st.fixtures && <Badge tone="warn">Test build: stand-in engines</Badge>}
                </div>
                {(!st.tts_ready || !st.stt_ready || !enabled) && (
                  <p className="text-sm text-text-2">
                    Atlas downloads its voice files only when you ask: speech output is about {mb((st.tts_engine?.bytes ?? 0) + (st.voices.find((x) => x.id === st.selected_voice)?.bytes ?? 0))} and speech recognition about{" "}
                    {mb((st.stt_engine?.bytes ?? 0) + (st.stt_models.find((x) => x.id === st.selected_stt_model)?.bytes ?? 0))}.{" "}
                    <button className="text-accent underline underline-offset-2" onClick={() => openSettings("voice")}>Set it up in Settings → Voice</button>.
                  </p>
                )}
              </>
            )}
          </Panel>
          <Panel className="space-y-2 p-5">
            <div className="flex items-center gap-2">
              <ShieldCheck className="size-5 text-ok" aria-hidden />
              <h2 className="font-semibold">Voice privacy</h2>
            </div>
            <ul className="list-disc space-y-1 pl-5 text-sm text-text-2">
              <li>Push-to-talk only, never always-listening. A visible indicator shows whenever the microphone is on.</li>
              <li>Speech is recognised and spoken on this computer. No speech service, no API key.</li>
              <li>No recordings are stored. Audio is discarded once it has been transcribed.</li>
              <li>Nothing you say is sent to Prometheus, and nothing is saved to memory automatically.</li>
            </ul>
            <Button variant="subtle" icon={<Keyboard className="size-4" aria-hidden />} onClick={() => navigate("companion")}>
              Type to Atlas instead
            </Button>
          </Panel>
        </div>
      </div>
    </div>
  );
}
