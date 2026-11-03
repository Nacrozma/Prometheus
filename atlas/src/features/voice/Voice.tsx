import { Keyboard, Mic, MicOff, ShieldCheck, Volume2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge, Button, PageHeader, Panel, StatusPill } from "@/components/ui/primitives";
import { useUi } from "@/state/ui";

/**
 * Voice is designed (push-to-talk, explicit local vs cloud transcription, no stored recordings)
 * but speech-to-text is not implemented in this version, and this page says so. Text-to-speech is
 * offered only if the system's speech synthesis is actually present in this window.
 */
export function VoicePage() {
  const navigate = useUi((s) => s.navigate);
  const [voices, setVoices] = useState<SpeechSynthesisVoice[] | null>(null);
  const synth = typeof window !== "undefined" && "speechSynthesis" in window ? window.speechSynthesis : null;
  const mic = typeof navigator !== "undefined" && Boolean(navigator.mediaDevices?.getUserMedia);

  useEffect(() => {
    if (!synth) return;
    const load = () => setVoices(synth.getVoices());
    load();
    synth.addEventListener?.("voiceschanged", load);
    return () => synth.removeEventListener?.("voiceschanged", load);
  }, [synth]);

  const ttsAvailable = Boolean(synth && voices && voices.length > 0);

  return (
    <div className="h-full overflow-y-auto">
      <PageHeader eyebrow="Interaction" title="Voice" subtitle="Talk to Atlas with push-to-talk. Typing always works as a fallback." />
      <div className="grid gap-5 px-8 py-6 lg:grid-cols-2">
        <Panel className="space-y-3 p-5">
          <div className="flex items-center gap-2">
            <Mic className="size-5 text-accent" aria-hidden />
            <h2 className="font-semibold">Speech to text</h2>
            <Badge tone="warn" className="ml-auto">Not available yet</Badge>
          </div>
          <p className="text-sm text-text-2">
            Push-to-talk transcription is designed but not built into this version, so there is no microphone access at all. When it arrives, you'll choose
            between on-device transcription and a cloud service, the microphone will only be active while you hold the talk button, and recordings won't be stored.
          </p>
          <div className="flex flex-wrap gap-3 text-xs">
            <StatusPill tone="neutral" label="Microphone: never accessed" />
            <StatusPill tone={mic ? "neutral" : "warn"} label={mic ? "System microphone API present" : "No microphone API in this window"} />
          </div>
          <Button disabled icon={<MicOff className="size-4" aria-hidden />}>Hold to talk (coming later)</Button>
        </Panel>
        <Panel className="space-y-3 p-5">
          <div className="flex items-center gap-2">
            <Volume2 className="size-5 text-accent" aria-hidden />
            <h2 className="font-semibold">Read responses aloud</h2>
            <Badge tone={ttsAvailable ? "ok" : "neutral"} className="ml-auto">{ttsAvailable ? `${voices!.length} system voices` : "Not available here"}</Badge>
          </div>
          <p className="text-sm text-text-2">
            Uses your operating system's speech synthesis, on this computer. {ttsAvailable ? "You can test it below." : "This window doesn't expose system voices, so it's switched off."}
          </p>
          <Button
            disabled={!ttsAvailable}
            onClick={() => {
              if (!synth) return;
              synth.cancel();
              synth.speak(new SpeechSynthesisUtterance("Hello, I'm Atlas. This voice runs on your computer."));
            }}
          >
            Play a sample
          </Button>
          {ttsAvailable && <Button variant="ghost" onClick={() => synth?.cancel()}>Stop</Button>}
        </Panel>
        <Panel className="space-y-2 p-5 lg:col-span-2">
          <div className="flex items-center gap-2"><ShieldCheck className="size-5 text-ok" aria-hidden /><h2 className="font-semibold">Voice privacy commitments</h2></div>
          <ul className="list-disc space-y-1 pl-5 text-sm text-text-2">
            <li>Push-to-talk only — never always-listening.</li>
            <li>A visible indicator whenever the microphone is active.</li>
            <li>Clear labelling of local versus cloud transcription before any audio leaves this computer.</li>
            <li>No recordings stored by default.</li>
          </ul>
          <Button variant="subtle" icon={<Keyboard className="size-4" aria-hidden />} onClick={() => navigate("companion")}>Type to Atlas instead</Button>
        </Panel>
      </div>
    </div>
  );
}
