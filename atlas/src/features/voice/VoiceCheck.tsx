import { ClipboardCopy, Mic, Square, Volume2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Button, Select } from "@/components/ui/primitives";
import { api, AtlasError } from "@/lib/bridge";
import { useAtlasQuery } from "@/lib/query";
import type { Settings, VoiceStatus } from "@/lib/schemas";
import { useVoice } from "@/state/voice";
import { audio } from "./audioEngine";
import { CHECK_PHRASE, CONDITIONS, SPEAKER_PHRASE, formatReport, micVerdict, wordAccuracy, type CheckResult, type Condition, type MicResult } from "./checkReport";
import { VoiceRing } from "./VoiceRing";

const clock = () => new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

/**
 * Voice check: the owner tests their real speakers and microphone, and Atlas records what it
 * measured (timings, accuracy, devices). The results are the evidence for how voice behaves on
 * this PC; they stay on screen until copied, and no audio is kept.
 */
export function VoiceCheck({ v, st, devices }: { v: Settings["voice"]; st: VoiceStatus; devices: MediaDeviceInfo[] }) {
  const info = useAtlasQuery("app-info", api.appInfo, []);
  const [results, setResults] = useState<CheckResult[]>([]);
  const [condition, setCondition] = useState<Condition>("Quiet room");
  const [mic, setMic] = useState<"off" | "listening" | "transcribing">("off");
  const [speaker, setSpeaker] = useState<{ firstAudioMs: number | null } | null>(null);
  const peak = useRef(0);
  const started = useRef(0);
  const meter = useRef<ReturnType<typeof setInterval> | null>(null);

  const label = (kind: MediaDeviceKind, id: string | null | undefined) =>
    id ? devices.find((d) => d.kind === kind && d.deviceId === id)?.label || "Selected device" : "System default";
  const voiceName = st.voices.find((a) => a.id === st.selected_voice)?.name ?? st.selected_voice;
  const modelName = st.stt_models.find((a) => a.id === st.selected_stt_model)?.name ?? st.selected_stt_model;

  const stopMeter = () => {
    if (meter.current) clearInterval(meter.current);
    meter.current = null;
  };
  useEffect(
    () => () => {
      stopMeter();
      if (audio.capturing) audio.cancelCapture();
    },
    [],
  );

  // ----- speakers -----
  const playSpeaker = () => {
    if (!st.tts_ready) return toast.error("Set up speech output first.");
    audio.context();
    const t0 = performance.now();
    setSpeaker({ firstAudioMs: null });
    const off = audio.subscribe(() => {
      if (audio.state === "speaking") {
        off();
        setSpeaker((s) => (s && s.firstAudioMs == null ? { firstAudioMs: Math.round(performance.now() - t0) } : s));
      } else if (audio.error) {
        off();
        setSpeaker(null);
      }
    });
    useVoice.getState().speakText(SPEAKER_PHRASE);
  };
  const answerSpeaker = (heard: "clearly" | "with problems" | "not at all") => {
    if (!speaker || speaker.firstAudioMs == null) return;
    setResults((r) => [...r, { kind: "speaker", at: clock(), device: label("audiooutput", v.output_device), voice: voiceName, firstAudioMs: speaker.firstAudioMs ?? 0, heard }]);
    setSpeaker(null);
  };

  // ----- microphone -----
  const startMic = async () => {
    if (!st.stt_ready) return toast.error("Set up speech recognition first.");
    if (useVoice.getState().capture !== "off") return toast.error("Atlas is already listening.");
    try {
      await audio.startCapture({ deviceId: v.input_device, fixture: st.fixtures });
    } catch (e) {
      return toast.error(e instanceof AtlasError ? e.message : "The microphone could not be started.");
    }
    peak.current = 0;
    started.current = performance.now();
    meter.current = setInterval(() => {
      peak.current = Math.max(peak.current, audio.level());
    }, 50);
    setMic("listening");
  };
  const stopMic = async () => {
    if (mic !== "listening") return;
    stopMeter();
    const backend = audio.captureBackend ?? "unknown";
    const sampleRate = audio.context().sampleRate;
    const pcm = audio.stopCapture();
    setMic("transcribing");
    try {
      const t = await api.voiceTranscribe(pcm, 16_000);
      const result: MicResult = {
        kind: "microphone",
        at: clock(),
        condition,
        device: label("audioinput", v.input_device),
        model: modelName,
        language: v.language,
        backend,
        sampleRate,
        speechMs: t.audio_ms,
        transcribeMs: t.elapsed_ms,
        peakLevel: peak.current,
        transcript: t.text.trim(),
        accuracy: wordAccuracy(CHECK_PHRASE, t.text),
      };
      setResults((r) => [...r, result]);
    } catch (e) {
      toast.error(e instanceof AtlasError ? e.message : "Speech recognition failed.");
    } finally {
      pcm.fill(0);
      setMic("off");
    }
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(formatReport(results, st, info.data?.version ?? "unknown"));
      toast.success("Report copied");
    } catch {
      toast.error("The report could not be copied");
    }
  };

  return (
    <div className="flex flex-col gap-4" data-voice-check>
      {st.fixtures && <p className="text-xs text-warn">Test build: stand-in engines, so these results say nothing about real hardware.</p>}

      <div className="flex flex-col gap-2">
        <p className="text-xs font-medium text-text-1">1. Speakers or headphones</p>
        <div className="flex flex-wrap items-center gap-3">
          <Button size="sm" icon={<Volume2 className="size-3.5" aria-hidden />} onClick={playSpeaker} disabled={!st.tts_ready || speaker != null}>
            Play test sentence
          </Button>
          {speaker && speaker.firstAudioMs == null && <span className="text-xs text-text-3">Preparing speech…</span>}
          {speaker && speaker.firstAudioMs != null && (
            <span className="flex flex-wrap items-center gap-2 text-xs text-text-2" data-speaker-question>
              Did you hear it?
              <Button size="sm" onClick={() => answerSpeaker("clearly")}>Clearly</Button>
              <Button size="sm" onClick={() => answerSpeaker("with problems")}>With problems</Button>
              <Button size="sm" onClick={() => answerSpeaker("not at all")}>Not at all</Button>
            </span>
          )}
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <p className="text-xs font-medium text-text-1">2. Microphone</p>
        <p className="text-xs text-text-2">
          Press Start, read this aloud, then press Stop: <span className="text-text-1">“{CHECK_PHRASE}”</span>
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-xs text-text-2">
            Conditions
            <Select aria-label="Test conditions" value={condition} onChange={(e) => setCondition(e.target.value as Condition)} className="w-52" disabled={mic !== "off"}>
              {CONDITIONS.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </Select>
          </label>
          {mic === "listening" ? (
            <Button size="sm" variant="primary" icon={<Square className="size-3.5" aria-hidden />} onClick={() => void stopMic()}>
              Stop
            </Button>
          ) : (
            <Button size="sm" icon={<Mic className="size-3.5" aria-hidden />} onClick={() => void startMic()} disabled={!st.stt_ready || mic !== "off"} loading={mic === "transcribing"}>
              {mic === "transcribing" ? "Recognising…" : "Start"}
            </Button>
          )}
          {mic === "listening" && <VoiceRing phase="listening" size={40} />}
        </div>
      </div>

      {results.length > 0 && (
        <div className="flex flex-col gap-2">
          <ul className="flex flex-col gap-2 text-xs" data-check-results>
            {results.map((r, i) =>
              r.kind === "speaker" ? (
                <li key={i} className="rounded-md border border-line-1 px-3 py-2 text-text-2" data-result="speaker">
                  <span className="text-text-1">Speakers</span> · {r.device} · first sound after {(r.firstAudioMs / 1000).toFixed(2)} s · heard {r.heard}
                </li>
              ) : (
                <li key={i} className="rounded-md border border-line-1 px-3 py-2 text-text-2" data-result="microphone" data-accuracy={r.accuracy.toFixed(2)}>
                  <span className="text-text-1">Microphone</span> · {r.condition} · {r.device} · {Math.round(r.accuracy * 100)}% of words right · spoke {(r.speechMs / 1000).toFixed(1)} s,
                  recognised in {(r.transcribeMs / 1000).toFixed(1)} s
                  <br />
                  Heard: “{r.transcript || "nothing"}”
                  <br />
                  <span className="text-text-3">{micVerdict(r)}</span>
                </li>
              ),
            )}
          </ul>
          <div className="flex flex-wrap items-center gap-3">
            <Button size="sm" icon={<ClipboardCopy className="size-3.5" aria-hidden />} onClick={() => void copy()}>
              Copy report
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setResults([])}>
              Clear
            </Button>
          </div>
        </div>
      )}
      <p className="text-[0.6875rem] text-text-3">
        Each microphone attempt is recognised on this computer and then discarded. The report holds timings, device names and the recognised text; it is not saved or sent
        anywhere unless you copy it.
      </p>
    </div>
  );
}
