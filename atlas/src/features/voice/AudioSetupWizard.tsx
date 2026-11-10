import { Check, Download, Mic, Volume2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Dialog } from "@/components/ui/dialog";
import { Button, Select, Switch } from "@/components/ui/primitives";
import { api, AtlasError } from "@/lib/bridge";
import { useAtlasQuery } from "@/lib/query";
import type { ArtifactStatus, DownloadProgress, Settings } from "@/lib/schemas";
import { useVoice } from "@/state/voice";
import { audio } from "./audioEngine";
import { SPEAKER_PHRASE } from "./checkReport";
import { VoiceRing } from "./VoiceRing";

const STEPS = ["Welcome", "Speakers", "Microphone", "Done"] as const;
const mb = (bytes: number) => `${Math.max(1, Math.round(bytes / 1_000_000))} MB`;

function progressText(name: string, p: DownloadProgress | null): string {
  if (!p) return `Starting ${name}…`;
  if (p.phase === "downloading") return p.total ? `Downloading ${name}: ${Math.round((p.received / p.total) * 100)}%` : `Downloading ${name}: ${mb(p.received)}`;
  if (p.phase === "verifying") return `Checking ${name}…`;
  if (p.phase === "unpacking") return `Unpacking ${name}…`;
  return `${name} ready`;
}

/**
 * A guided setup for speakers and microphone: download what is needed (sizes shown first), pick
 * the devices, and try each one. Every step can be skipped, and closing the wizard keeps
 * whatever was already set up. It changes nothing that Settings → Voice could not.
 */
export function AudioSetupWizard({ open, onClose }: { open: boolean; onClose: () => void }) {
  const settings = useAtlasQuery("settings", api.settings, ["settings"]);
  const status = useAtlasQuery("voice-status", api.voiceStatus, ["settings"]);
  const s = settings.data;
  const st = status.data;
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const installing = useRef<string | null>(null);
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  const [heard, setHeard] = useState<"yes" | "no" | null>(null);
  const [mic, setMic] = useState<{ testing: boolean; peak: number | null }>({ testing: false, peak: null });
  const micTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const playback = useVoice((v) => v.playback);

  const loadDevices = async () => {
    try {
      setDevices((await navigator.mediaDevices?.enumerateDevices?.()) ?? []);
    } catch {
      setDevices([]);
    }
  };
  const stopMic = () => {
    if (micTimer.current) clearInterval(micTimer.current);
    micTimer.current = null;
    if (audio.capturing) audio.cancelCapture();
  };
  useEffect(() => {
    if (!open) return;
    setStep(0);
    setHeard(null);
    setMic({ testing: false, peak: null });
    void loadDevices();
    return () => {
      stopMic();
      if (installing.current) void api.voiceInstallCancel(installing.current).catch(() => {});
    };
  }, [open]);

  if (!s || !st) return null;
  const v = s.voice;
  const save = async (patch: Partial<Settings["voice"]>) => {
    try {
      await api.updateSettings({ ...s, voice: { ...v, ...patch } });
      settings.reload();
    } catch (e) {
      toast.error(e instanceof AtlasError ? e.message : "The setting could not be saved");
    }
  };

  const voice = st.voices.find((x) => x.id === st.selected_voice);
  const model = st.stt_models.find((x) => x.id === st.selected_stt_model);
  const need = (items: (ArtifactStatus | null | undefined)[]) => items.filter((x): x is ArtifactStatus => Boolean(x) && x!.state !== "installed");
  const outNeed = need([st.tts_engine, voice]);
  const inNeed = need([st.stt_engine, model]);
  const size = (items: ArtifactStatus[]) => mb(items.reduce((n, x) => n + x.bytes, 0));

  const install = async (items: ArtifactStatus[]) => {
    for (const a of items) {
      installing.current = a.id;
      setBusy(progressText(a.name, null));
      try {
        await api.voiceInstall(a.id, (p) => setBusy(progressText(a.name, p)));
      } catch (e) {
        if (!(e instanceof AtlasError && e.code === "cancelled")) toast.error(e instanceof AtlasError ? e.message : `Could not download ${a.name}`);
        break;
      }
    }
    installing.current = null;
    setBusy(null);
    status.reload();
  };
  const cancelInstall = () => {
    if (installing.current) void api.voiceInstallCancel(installing.current).catch(() => {});
  };

  const playTest = () => {
    setHeard(null);
    audio.context();
    useVoice.getState().speakText(SPEAKER_PHRASE);
  };
  const chooseOutput = async (id: string | null) => {
    if (!(await audio.setOutputDevice(id))) return toast.error("That output could not be used. Atlas is using the system default.");
    await save({ output_device: id });
  };
  const testMic = async () => {
    try {
      await audio.startCapture({ deviceId: v.input_device, fixture: st.fixtures });
    } catch (e) {
      return toast.error(e instanceof AtlasError ? e.message : "The microphone could not be started.");
    }
    void loadDevices(); // device names appear once access is granted
    let peak = 0;
    const started = performance.now();
    setMic({ testing: true, peak: null });
    micTimer.current = setInterval(() => {
      peak = Math.max(peak, audio.level());
      if (performance.now() - started > 4000) {
        stopMic();
        setMic({ testing: false, peak });
      }
    }, 50);
  };

  const inputs = devices.filter((d) => d.kind === "audioinput" && d.deviceId && d.deviceId !== "default");
  const outputs = devices.filter((d) => d.kind === "audiooutput" && d.deviceId && d.deviceId !== "default");
  const close = () => {
    stopMic();
    if (playback !== "idle") useVoice.getState().stopSpeaking();
    onClose();
  };
  const next = () => setStep((n) => Math.min(STEPS.length - 1, n + 1));

  const body = () => {
    switch (STEPS[step]) {
      case "Welcome":
        return (
          <div className="flex flex-col gap-3 text-sm text-text-2">
            <div className="flex items-center gap-4">
              <VoiceRing phase="idle" size={64} />
              <p>
                Atlas can listen and speak entirely on this computer. No speech service, no API key, and it works offline once set up. Voice is optional: Atlas works fully
                without it.
              </p>
            </div>
            <ul className="list-disc pl-5 text-xs text-text-3">
              <li>The microphone is on only while you hold a conversation with it (push-to-talk). Nothing listens in the background.</li>
              <li>Recordings are recognised on this computer and then discarded.</li>
              <li>
                Downloads: {outNeed.length ? `about ${size(outNeed)} for speaking` : "speaking is already set up"}, {inNeed.length ? `about ${size(inNeed)} for listening` : "listening is already set up"}. Each file is checked against its publisher's checksum.
              </li>
            </ul>
            {st.fixtures && <p className="text-xs text-warn">Test build: stand-in engines, not real speech.</p>}
          </div>
        );
      case "Speakers":
        return (
          <div className="flex flex-col gap-4 text-sm text-text-2" data-wizard-step="speakers">
            {!st.tts_supported ? (
              <p>Speech output isn't available for this system yet ({st.platform}). You can skip this step.</p>
            ) : !st.tts_ready ? (
              <div className="flex flex-col gap-2">
                <p>Atlas needs its speech engine and a voice ({size(outNeed)}).</p>
                <div className="flex items-center gap-3">
                  <Button size="sm" variant="primary" icon={<Download className="size-3.5" aria-hidden />} onClick={() => void install(outNeed)} disabled={busy != null}>
                    Download · {size(outNeed)}
                  </Button>
                  {busy && (
                    <>
                      <span className="text-xs text-text-3" role="status">
                        {busy}
                      </span>
                      <Button size="sm" variant="ghost" onClick={cancelInstall}>
                        Cancel
                      </Button>
                    </>
                  )}
                </div>
              </div>
            ) : (
              <>
                {audio.outputSelectable() ? (
                  <label className="flex items-center gap-2 text-xs">
                    Play through
                    <Select aria-label="Speakers or headphones" value={v.output_device ?? ""} onChange={(e) => void chooseOutput(e.target.value || null)} className="w-64">
                      <option value="">System default</option>
                      {outputs.map((d, i) => (
                        <option key={d.deviceId || i} value={d.deviceId}>
                          {d.label || `Output ${i + 1}`}
                        </option>
                      ))}
                    </Select>
                  </label>
                ) : (
                  <p className="text-xs text-text-3">Atlas plays through your system's default output. Change it in your system's sound settings.</p>
                )}
                <div className="flex flex-wrap items-center gap-3">
                  <Button size="sm" icon={<Volume2 className="size-3.5" aria-hidden />} onClick={playTest} disabled={playback !== "idle"}>
                    Play a test sentence
                  </Button>
                  {playback !== "idle" && <VoiceRing phase={playback === "speaking" ? "speaking" : "processing"} size={40} />}
                  <label className="flex items-center gap-2 text-xs">
                    Volume {v.volume}%
                    <input type="range" aria-label="Voice volume" min={0} max={100} step={5} value={v.volume} onChange={(e) => void save({ volume: Number(e.target.value) })} className="w-32 accent-[color:var(--accent)]" />
                  </label>
                </div>
                <div className="flex flex-wrap items-center gap-3 text-xs">
                  Could you hear it?
                  <Button size="sm" variant={heard === "yes" ? "primary" : "secondary"} onClick={() => setHeard("yes")}>
                    Yes
                  </Button>
                  <Button size="sm" variant={heard === "no" ? "primary" : "secondary"} onClick={() => setHeard("no")}>
                    No
                  </Button>
                </div>
                {heard === "no" && (
                  <p className="text-xs text-warn" role="status">
                    If the ring moved, Atlas is playing: check the volume above, your system volume and which output is selected. If the ring did not move, try the test again.
                  </p>
                )}
              </>
            )}
          </div>
        );
      case "Microphone":
        return (
          <div className="flex flex-col gap-4 text-sm text-text-2" data-wizard-step="microphone">
            {!st.stt_supported ? (
              <p>Speech recognition isn't available for this system yet ({st.platform}). You can skip this step; Atlas can still speak.</p>
            ) : !st.stt_ready ? (
              <div className="flex flex-col gap-2">
                <p>
                  Atlas needs its recognition engine and a model ({size(inNeed)}). Recommended for this PC:{" "}
                  <strong>{st.stt_models.find((x) => x.id === st.hardware.recommended_stt_model)?.name ?? "Whisper base"}</strong>.
                </p>
                <div className="flex items-center gap-3">
                  <Button size="sm" variant="primary" icon={<Download className="size-3.5" aria-hidden />} onClick={() => void install(inNeed)} disabled={busy != null}>
                    Download · {size(inNeed)}
                  </Button>
                  {busy && (
                    <>
                      <span className="text-xs text-text-3" role="status">
                        {busy}
                      </span>
                      <Button size="sm" variant="ghost" onClick={cancelInstall}>
                        Cancel
                      </Button>
                    </>
                  )}
                </div>
              </div>
            ) : (
              <>
                <label className="flex items-center gap-2 text-xs">
                  Microphone
                  <Select aria-label="Microphone" value={v.input_device ?? ""} onChange={(e) => void save({ input_device: e.target.value || null })} className="w-64" disabled={mic.testing}>
                    <option value="">System default</option>
                    {inputs.map((d, i) => (
                      <option key={d.deviceId || i} value={d.deviceId}>
                        {d.label || `Microphone ${i + 1}`}
                      </option>
                    ))}
                  </Select>
                </label>
                <div className="flex flex-wrap items-center gap-3">
                  <Button size="sm" icon={<Mic className="size-3.5" aria-hidden />} onClick={() => void testMic()} disabled={mic.testing}>
                    {mic.testing ? "Say something… (4 s)" : "Test the microphone"}
                  </Button>
                  {mic.testing && <VoiceRing phase="listening" size={40} />}
                </div>
                {mic.peak != null && (
                  <p className={mic.peak < 0.01 ? "text-xs text-warn" : "text-xs text-ok"} role="status" data-mic-result={mic.peak < 0.01 ? "silent" : "heard"}>
                    {mic.peak < 0.01
                      ? "Atlas heard almost nothing. Check that the right microphone is selected, that it isn't muted, and that your system allows desktop apps to use it."
                      : "Atlas can hear you."}
                  </p>
                )}
                <p className="text-[0.6875rem] text-text-3">This test only measures the level. Nothing is recorded or recognised.</p>
              </>
            )}
          </div>
        );
      case "Done":
        return (
          <div className="flex flex-col gap-4 text-sm text-text-2" data-wizard-step="done">
            <ul className="flex flex-col gap-1 text-xs">
              <li className="flex items-center gap-2">
                <Check className={st.tts_ready ? "size-3.5 text-ok" : "size-3.5 text-text-3"} aria-hidden />
                Speaking: {st.tts_ready ? "ready" : "not set up"}
              </li>
              <li className="flex items-center gap-2">
                <Check className={st.stt_ready ? "size-3.5 text-ok" : "size-3.5 text-text-3"} aria-hidden />
                Listening: {st.stt_ready ? "ready" : "not set up"}
              </li>
            </ul>
            <div className="flex items-center justify-between gap-4">
              <p className="text-xs">Read Atlas's replies aloud</p>
              <Switch checked={v.speak_responses} label="Read replies aloud" disabled={!st.tts_ready} onChange={(speak_responses) => void save({ speak_responses })} />
            </div>
            <p className="text-xs text-text-3">
              To talk: click the microphone in the Companion or press Ctrl + Shift + Space, speak, then click again. Esc stops Atlas speaking. To measure accuracy and
              timing on this PC, use Voice check in Settings → Voice.
            </p>
          </div>
        );
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !o && close()}
      title={`Set up voice · ${step + 1} of ${STEPS.length}`}
      description={STEPS[step]}
      width="max-w-xl"
      footer={
        <>
          {step > 0 && step < STEPS.length - 1 && (
            <Button variant="ghost" onClick={() => setStep((n) => n - 1)} disabled={busy != null}>
              Back
            </Button>
          )}
          {step === 0 ? (
            <Button
              variant="primary"
              onClick={() => {
                if (!v.enabled) void save({ enabled: true });
                next();
              }}
            >
              {v.enabled ? "Continue" : "Turn on voice and continue"}
            </Button>
          ) : step < STEPS.length - 1 ? (
            <Button variant="primary" onClick={next} disabled={busy != null}>
              {(STEPS[step] === "Speakers" && !st.tts_ready) || (STEPS[step] === "Microphone" && !st.stt_ready) ? "Skip" : "Continue"}
            </Button>
          ) : (
            <Button variant="primary" onClick={close}>
              Finish
            </Button>
          )}
        </>
      }
    >
      <div data-audio-wizard data-step={STEPS[step]}>
        {body()}
      </div>
    </Dialog>
  );
}
