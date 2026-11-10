import { Download, Gauge, Mic, ShieldCheck, Trash2, Volume2, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { Badge, Button, Panel, Select, StatusPill, Switch } from "@/components/ui/primitives";
import { api, AtlasError } from "@/lib/bridge";
import { cn } from "@/lib/format";
import { useAtlasQuery } from "@/lib/query";
import type { ArtifactStatus, Benchmark, DownloadProgress, Settings } from "@/lib/schemas";
import { useVoice } from "@/state/voice";
import { audio } from "./audioEngine";
import { AudioSetupWizard } from "./AudioSetupWizard";
import { VoiceCheck } from "./VoiceCheck";
import { VoiceRing } from "./VoiceRing";

const LANGUAGES: [string, string][] = [
  ["auto", "Detect automatically"],
  ["en", "English"],
  ["ar", "Arabic"],
  ["fr", "French"],
  ["es", "Spanish"],
  ["de", "German"],
  ["it", "Italian"],
  ["pt", "Portuguese"],
  ["nl", "Dutch"],
  ["tr", "Turkish"],
  ["hi", "Hindi"],
  ["ur", "Urdu"],
  ["zh", "Chinese"],
  ["ja", "Japanese"],
];

export const mb = (bytes: number) => `${Math.max(1, Math.round(bytes / 1_000_000))} MB`;

function Section({ title, desc, children }: { title: string; desc?: ReactNode; children: ReactNode }) {
  return (
    <div className="border-b border-line-1 py-4 last:border-0">
      <p className="text-sm font-medium text-text-1">{title}</p>
      {desc && <p className="mt-0.5 text-xs text-text-3">{desc}</p>}
      <div className="mt-3">{children}</div>
    </div>
  );
}

/** Download / cancel / remove / verify for one catalog item, with real progress. */
export function ArtifactActions({ a, onUse, selected }: { a: ArtifactStatus; onUse?: () => void; selected?: boolean }) {
  const [progress, setProgress] = useState<DownloadProgress | null>(null);
  const [busy, setBusy] = useState(false);
  const install = async () => {
    setBusy(true);
    try {
      await api.voiceInstall(a.id, setProgress);
      toast.success(`${a.name} is ready`);
    } catch (e) {
      if (!(e instanceof AtlasError && e.code === "cancelled")) toast.error(e instanceof AtlasError ? e.message : "Download failed");
    } finally {
      setBusy(false);
      setProgress(null);
    }
  };
  const verify = async () => {
    try {
      const bad = await api.voiceVerify(a.id);
      if (bad.length) toast.error(`${a.name}: ${bad.length} file(s) changed or missing. Remove it and download it again.`);
      else toast.success(`${a.name}: every file matches its checksum`);
    } catch (e) {
      toast.error(e instanceof AtlasError ? e.message : "Could not check the files");
    }
  };
  const remove = async () => {
    try {
      await api.voiceRemove(a.id);
      toast.success(`${a.name} removed`);
    } catch (e) {
      toast.error(e instanceof AtlasError ? e.message : "Could not remove it");
    }
  };
  if (busy || a.installing) {
    const pct = progress?.phase === "downloading" && progress.total ? Math.round((progress.received / progress.total) * 100) : null;
    const label =
      progress?.phase === "verifying" ? "Checking integrity…" : progress?.phase === "unpacking" ? "Unpacking…" : pct !== null ? `Downloading ${pct}%` : "Downloading…";
    return (
      <div className="flex items-center gap-2" data-download={a.id}>
        <div className="h-1.5 w-28 overflow-hidden rounded-full bg-bg-4" role="progressbar" aria-label={`${a.name} download`} aria-valuenow={pct ?? undefined} aria-valuemin={0} aria-valuemax={100}>
          <div className="h-full bg-accent transition-[width]" style={{ width: `${pct ?? 15}%` }} />
        </div>
        <span className="text-xs text-text-3">{label}</span>
        <Button size="sm" variant="ghost" icon={<X className="size-3.5" aria-hidden />} onClick={() => void api.voiceInstallCancel(a.id)}>
          Cancel
        </Button>
      </div>
    );
  }
  if (a.state === "installed")
    return (
      <div className="flex flex-wrap items-center gap-1.5">
        {onUse && (selected ? <Badge tone="accent">In use</Badge> : <Button size="sm" onClick={onUse}>Use</Button>)}
        <Button size="sm" variant="ghost" onClick={() => void verify()}>Verify</Button>
        <Button size="sm" variant="ghost" icon={<Trash2 className="size-3.5" aria-hidden />} onClick={() => void remove()}>
          Remove<span className="sr-only"> {a.name}</span>
        </Button>
      </div>
    );
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {a.state === "damaged" && <Badge tone="warn">Damaged</Badge>}
      {a.state === "damaged" && (
        <Button size="sm" variant="ghost" onClick={() => void remove()}>
          Remove
        </Button>
      )}
      <Button size="sm" icon={<Download className="size-3.5" aria-hidden />} onClick={() => void install()} data-action="download">
        Download · {mb(a.bytes)}
        <span className="sr-only"> {a.name}</span>
      </Button>
    </div>
  );
}

function ItemRow({ a, selected, onUse, extra }: { a: ArtifactStatus; selected?: boolean; onUse?: () => void; extra?: ReactNode }) {
  return (
    <li className={cn("flex flex-wrap items-start gap-3 rounded-md border px-3 py-2.5", selected ? "border-accent/60 bg-accent-soft/30" : "border-line-1")} data-artifact={a.id} data-state={a.state}>
      <div className="min-w-0 flex-1 basis-64">
        <p className="text-sm text-text-1">
          {a.name} {a.recommended && <Badge tone="info">recommended</Badge>} {a.note && <span className="text-xs text-text-3">· {a.note}</span>}
        </p>
        <p className="text-xs text-text-3">{a.description}</p>
        <p className="mt-0.5 text-[0.6875rem] text-text-3">
          Licence:{" "}
          <button className="underline underline-offset-2 hover:text-text-1" onClick={() => void api.openExternal(a.license_url)}>
            {a.license}
          </button>
        </p>
      </div>
      <div className="flex items-center gap-2">
        {extra}
        <ArtifactActions a={a} onUse={onUse} selected={selected} />
      </div>
    </li>
  );
}

/** Settings → Voice. */
export function VoiceSettingsSection({ s, save }: { s: Settings; save: (n: Settings) => Promise<void> }) {
  const status = useAtlasQuery("voice-status", api.voiceStatus, ["settings"]);
  const v = s.voice;
  const set = (patch: Partial<Settings["voice"]>) => save({ ...s, voice: { ...v, ...patch } });
  const st = status.data;
  const voiceState = useVoice();
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [testing, setTesting] = useState(false);
  const [bench, setBench] = useState<Benchmark | null>(null);
  const [benchBusy, setBenchBusy] = useState(false);
  const [wizard, setWizard] = useState(false);
  const testTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadDevices = async () => {
    try {
      const all = await navigator.mediaDevices?.enumerateDevices?.();
      setDevices((all ?? []).filter((d) => d.kind === "audioinput" || d.kind === "audiooutput"));
    } catch {
      setDevices([]);
    }
  };
  useEffect(() => {
    void loadDevices();
    navigator.mediaDevices?.addEventListener?.("devicechange", loadDevices);
    return () => navigator.mediaDevices?.removeEventListener?.("devicechange", loadDevices);
  }, []);
  useEffect(() => () => {
    if (testTimer.current) clearTimeout(testTimer.current);
    if (audio.capturing && testing) audio.cancelCapture();
  }, [testing]);

  const inputs = devices.filter((d) => d.kind === "audioinput" && d.deviceId && d.deviceId !== "default");
  const outputs = devices.filter((d) => d.kind === "audiooutput" && d.deviceId && d.deviceId !== "default");
  const chooseOutput = async (id: string | null) => {
    if (!(await audio.setOutputDevice(id))) return toast.error("That output device could not be used. Atlas is using the system default.");
    await set({ output_device: id });
  };

  const preview = () => {
    if (!st?.tts_ready) return toast.error("Download the speech engine and a voice first.");
    audio.context();
    useVoice.getState().speakText("Hello. I'm Atlas. This is how I sound, speaking entirely on your computer.");
  };

  const testMic = async () => {
    try {
      await audio.startCapture({ deviceId: v.input_device, fixture: st?.fixtures });
      setTesting(true);
      await loadDevices(); // labels appear once access is granted
      testTimer.current = setTimeout(() => {
        audio.cancelCapture();
        setTesting(false);
      }, 4000);
    } catch (e) {
      toast.error(e instanceof AtlasError ? e.message : "The microphone could not be started.");
    }
  };

  const runBenchmark = async () => {
    setBenchBusy(true);
    try {
      setBench(await api.voiceBenchmark());
    } catch (e) {
      toast.error(e instanceof AtlasError ? e.message : "The benchmark could not run");
    } finally {
      setBenchBusy(false);
    }
  };

  const setupBoth = async (items: (ArtifactStatus | null | undefined)[]) => {
    for (const a of items) {
      if (!a || a.state === "installed") continue;
      try {
        await api.voiceInstall(a.id, () => {});
      } catch (e) {
        if (!(e instanceof AtlasError && e.code === "cancelled")) toast.error(e instanceof AtlasError ? e.message : `Could not download ${a.name}`);
        return;
      }
    }
    toast.success("Ready");
  };

  if (!st) return <Panel className="mt-6 p-5 text-sm text-text-3">Checking voice files…</Panel>;
  const voice = st.voices.find((x) => x.id === st.selected_voice);
  const model = st.stt_models.find((x) => x.id === st.selected_stt_model);
  const outSize = [st.tts_engine, voice].filter((x) => x && x.state !== "installed").reduce((n, x) => n + (x?.bytes ?? 0), 0);
  const inSize = [st.stt_engine, model].filter((x) => x && x.state !== "installed").reduce((n, x) => n + (x?.bytes ?? 0), 0);

  return (
    <Panel className="mt-6 px-5" data-voice-settings>
      <div className="flex flex-wrap items-center gap-4 border-b border-line-1 py-4">
        <VoiceRing phase={!v.enabled ? "offline" : voiceState.capture === "listening" ? "listening" : voiceState.playback === "speaking" ? "speaking" : "idle"} size={56} />
        <div className="min-w-0 flex-1 basis-64">
          <p className="text-sm font-medium text-text-1">Voice</p>
          <p className="mt-0.5 text-xs text-text-3">
            Talk to Atlas with push-to-talk and hear its replies. Everything runs on this computer: no speech service, no API key, and nothing is sent anywhere.
          </p>
          <div className="mt-2 flex flex-wrap gap-2 text-xs">
            <StatusPill tone={st.tts_ready ? "ok" : "neutral"} label={st.tts_ready ? "Speech output ready" : "Speech output not set up"} />
            <StatusPill tone={st.stt_ready ? "ok" : "neutral"} label={st.stt_ready ? "Speech recognition ready" : "Speech recognition not set up"} />
            {st.fixtures && <Badge tone="warn">Test build: stand-in engines, not real speech</Badge>}
          </div>
        </div>
        <Button size="sm" onClick={() => setWizard(true)} data-open-wizard>
          Guided setup…
        </Button>
        <Switch checked={v.enabled} label="Voice" onChange={(enabled) => void set({ enabled })} />
      </div>
      <AudioSetupWizard open={wizard} onClose={() => setWizard(false)} />

      <Section title="Speech output" desc="Piper voices, run by the sherpa-onnx engine. Downloaded once; works offline afterwards.">
        {!st.tts_supported ? (
          <p className="text-xs text-text-3">Speech output isn't available for this platform yet ({st.platform}).</p>
        ) : (
          <div className="space-y-3">
            {!st.tts_ready && (
              <Button size="sm" variant="primary" icon={<Download className="size-3.5" aria-hidden />} onClick={() => void setupBoth([st.tts_engine, voice])}>
                Set up speech output · {mb(outSize)}
              </Button>
            )}
            <ul className="space-y-2">
              {st.tts_engine && <ItemRow a={st.tts_engine} />}
              {st.voices.map((a) => (
                <ItemRow key={a.id} a={a} selected={a.id === st.selected_voice} onUse={() => void set({ tts_voice: a.id })} />
              ))}
            </ul>
            <div className="flex flex-wrap items-center gap-4">
              <Button size="sm" icon={<Volume2 className="size-3.5" aria-hidden />} onClick={preview} disabled={!st.tts_ready}>
                Preview voice
              </Button>
              <label className="flex items-center gap-2 text-xs text-text-2">
                Speed {v.speed.toFixed(2)}×
                <input type="range" aria-label="Speaking speed" min={0.5} max={2} step={0.05} value={v.speed} onChange={(e) => void set({ speed: Number(e.target.value) })} className="w-32 accent-[color:var(--accent)]" />
              </label>
              <label className="flex items-center gap-2 text-xs text-text-2">
                Volume {v.volume}%
                <input type="range" aria-label="Voice volume" min={0} max={100} step={5} value={v.volume} onChange={(e) => void set({ volume: Number(e.target.value) })} className="w-32 accent-[color:var(--accent)]" />
              </label>
              {audio.outputSelectable() ? (
                <label className="flex items-center gap-2 text-xs text-text-2">
                  Play through
                  <Select aria-label="Speakers or headphones" value={v.output_device ?? ""} onChange={(e) => void chooseOutput(e.target.value || null)} className="w-56">
                    <option value="">System default</option>
                    {outputs.map((d, i) => (
                      <option key={d.deviceId || i} value={d.deviceId}>
                        {d.label || `Output ${i + 1}`}
                      </option>
                    ))}
                  </Select>
                </label>
              ) : (
                <span className="text-xs text-text-3" data-output-fixed>Plays through the system's default output (this system doesn't let apps choose).</span>
              )}
            </div>
            <div className="flex items-center justify-between gap-4">
              <p className="text-xs text-text-2">Read Atlas's replies aloud (code and tables are mentioned, not read)</p>
              <Switch checked={v.speak_responses} label="Read replies aloud" onChange={(speak_responses) => void set({ speak_responses })} />
            </div>
          </div>
        )}
      </Section>

      <Section title="Speech recognition" desc="Whisper models, run by whisper.cpp. Push-to-talk only: the microphone is on only while you're talking to Atlas.">
        {!st.stt_supported ? (
          <p className="text-xs text-text-3">Speech recognition isn't available for this platform yet ({st.platform}); it is built for Windows. Typing always works.</p>
        ) : (
          <div className="space-y-3">
            {!st.stt_ready && (
              <Button size="sm" variant="primary" icon={<Download className="size-3.5" aria-hidden />} onClick={() => void setupBoth([st.stt_engine, model])}>
                Set up speech recognition · {mb(inSize)}
              </Button>
            )}
            <p className="text-xs text-text-2" data-recommendation>
              Recommended for this PC: <strong>{st.stt_models.find((x) => x.id === st.hardware.recommended_stt_model)?.name ?? "Whisper base"}</strong>. {st.hardware.recommendation}
            </p>
            <ul className="space-y-2">
              {st.stt_engine && <ItemRow a={st.stt_engine} />}
              {st.stt_models.map((a) => (
                <ItemRow key={a.id} a={a} selected={a.id === st.selected_stt_model} onUse={() => void set({ stt_model: a.id })} />
              ))}
            </ul>
            <div className="flex flex-wrap items-center gap-4">
              <label className="flex items-center gap-2 text-xs text-text-2">
                Language
                <Select aria-label="Speech language" value={LANGUAGES.some(([c]) => c === v.language) ? v.language : v.language.split("-")[0] ?? "auto"} onChange={(e) => void set({ language: e.target.value })} className="w-48">
                  {LANGUAGES.map(([c, l]) => (
                    <option key={c} value={c}>
                      {l}
                    </option>
                  ))}
                </Select>
              </label>
              <label className="flex items-center gap-2 text-xs text-text-2">
                Microphone
                <Select aria-label="Microphone" value={v.input_device ?? ""} onChange={(e) => void set({ input_device: e.target.value || null })} className="w-56">
                  <option value="">System default</option>
                  {inputs.map((d, i) => (
                    <option key={d.deviceId || i} value={d.deviceId}>
                      {d.label || `Microphone ${i + 1}`}
                    </option>
                  ))}
                </Select>
              </label>
              <Button size="sm" icon={<Mic className="size-3.5" aria-hidden />} onClick={() => void testMic()} disabled={testing}>
                {testing ? "Listening for 4 s…" : "Test microphone"}
              </Button>
              {testing && <VoiceRing phase="listening" size={40} />}
            </div>
            <p className="text-[0.6875rem] text-text-3">The microphone test shows the level only; nothing is recorded or transcribed.</p>
            <div className="flex items-center justify-between gap-4">
              <p className="text-xs text-text-2">Send recognised requests immediately (otherwise they wait in the box so you can edit them)</p>
              <Switch checked={v.auto_send} label="Send automatically" onChange={(auto_send) => void set({ auto_send })} />
            </div>
          </div>
        )}
      </Section>

      <Section title="Voice check" desc="Test your real speakers and microphone. Atlas records what it measured so you can see how voice behaves on this PC.">
        <VoiceCheck v={v} st={st} devices={devices} />
      </Section>

      <Section title="This computer" desc="Measured locally to recommend a model. Nothing is sent anywhere.">
        <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs sm:grid-cols-3" data-hardware>
          <dt className="text-text-3">Processor</dt>
          <dd className="col-span-1 truncate text-text-1 sm:col-span-2">{st.hardware.cpu}</dd>
          <dt className="text-text-3">Cores</dt>
          <dd className="text-text-1 sm:col-span-2">{st.hardware.logical_cores}{st.hardware.arch === "x86_64" && (st.hardware.avx2 ? " · AVX2" : " · no AVX2 (slower recognition)")}</dd>
          <dt className="text-text-3">Memory</dt>
          <dd className="text-text-1 sm:col-span-2">{(st.hardware.total_memory_mb / 1024).toFixed(1)} GB ({(st.hardware.available_memory_mb / 1024).toFixed(1)} GB free)</dd>
          <dt className="text-text-3">Free disk</dt>
          <dd className="text-text-1 sm:col-span-2">{st.hardware.free_disk_mb != null ? `${(st.hardware.free_disk_mb / 1024).toFixed(1)} GB` : "unknown"}</dd>
          <dt className="text-text-3">Voice files</dt>
          <dd className="text-text-1 sm:col-span-2">{mb(st.storage_bytes)} used</dd>
        </dl>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button size="sm" icon={<Gauge className="size-3.5" aria-hidden />} onClick={() => void runBenchmark()} loading={benchBusy} disabled={!st.tts_ready || !st.stt_ready}>
            Run benchmark
          </Button>
          <span className="text-[0.6875rem] text-text-3">Speaks a test sentence, then transcribes it with every downloaded model, and reports the real speed here.</span>
        </div>
        {bench && (
          <div className="mt-3 overflow-x-auto rounded-md border border-line-1" data-benchmark>
            <table className="w-full text-xs">
              <thead className="bg-bg-3 text-text-3">
                <tr>
                  <th className="px-3 py-1.5 text-left font-medium">Model</th>
                  <th className="px-3 py-1.5 text-left font-medium">Time</th>
                  <th className="px-3 py-1.5 text-left font-medium">Speed</th>
                  <th className="px-3 py-1.5 text-left font-medium">Words right</th>
                </tr>
              </thead>
              <tbody>
                <tr className="border-t border-line-1">
                  <td className="px-3 py-1.5">Voice: {bench.voice}</td>
                  <td className="px-3 py-1.5">{(bench.synthesis_ms / 1000).toFixed(2)} s</td>
                  <td className="px-3 py-1.5">{(1 / Math.max(bench.synthesis_rtf, 0.001)).toFixed(1)}× real time</td>
                  <td className="px-3 py-1.5">for {(bench.audio_ms / 1000).toFixed(1)} s of speech</td>
                </tr>
                {bench.models.map((m) => (
                  <tr key={m.id} className="border-t border-line-1">
                    <td className="px-3 py-1.5">{m.name}</td>
                    <td className="px-3 py-1.5">{(m.elapsed_ms / 1000).toFixed(2)} s</td>
                    <td className="px-3 py-1.5">{(1 / Math.max(m.real_time_factor, 0.001)).toFixed(1)}× real time</td>
                    <td className="px-3 py-1.5">{Math.round(m.word_accuracy * 100)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {bench.fixtures && <p className="px-3 py-1.5 text-[0.6875rem] text-warn">Test build: these numbers come from stand-in engines.</p>}
          </div>
        )}
      </Section>

      <Section title="Privacy">
        <ul className="space-y-1 text-xs text-text-2" data-voice-privacy>
          <li className="flex gap-2"><ShieldCheck className="mt-0.5 size-3.5 shrink-0 text-ok" aria-hidden /> Push-to-talk only. Atlas never listens in the background, and the microphone is released the moment you stop.</li>
          <li className="flex gap-2"><ShieldCheck className="mt-0.5 size-3.5 shrink-0 text-ok" aria-hidden /> Recordings are not stored. Audio stays in memory until it is transcribed on this computer, then it is discarded. Temporary audio files right now: {st.temp_audio_files}.</li>
          <li className="flex gap-2"><ShieldCheck className="mt-0.5 size-3.5 shrink-0 text-ok" aria-hidden /> Recognised text becomes an ordinary message, under your conversation and memory settings. It is never saved to memory automatically.</li>
          <li className="flex gap-2"><ShieldCheck className="mt-0.5 size-3.5 shrink-0 text-ok" aria-hidden /> Audio, transcripts and custom instructions are never sent to Prometheus.</li>
          <li className="flex gap-2"><ShieldCheck className="mt-0.5 size-3.5 shrink-0 text-ok" aria-hidden /> Downloads come only from the pinned sources listed above, and each one is checked against its published checksum. Offline mode blocks them.</li>
        </ul>
        <p className="mt-2 text-[0.6875rem] text-text-3">To free the space, remove items above, or delete the voice folder inside Atlas's data folder (Settings → About).</p>
      </Section>
    </Panel>
  );
}
