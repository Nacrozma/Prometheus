/**
 * Atlas's audio: speech playback and push-to-talk capture, both through Web Audio so the voice ring
 * reads *real* audio. Playback runs source → gain (volume) → analyser → speakers; capture runs
 * microphone → analyser, collected in memory only.
 *
 * Playback is a queue of sentences: each is synthesised by the local engine (one ahead of what is
 * playing, so speech flows) and played in order. `stop()` silences everything at once, discards
 * the queue and cancels synthesis in progress. It never touches the reply text, and never asks
 * for a new reply.
 *
 * Privacy: recordings exist only in memory until they are handed to the local recogniser, and the
 * buffers are cleared after use. The microphone is released as soon as listening stops.
 */
import { api, AtlasError } from "@/lib/bridge";

export type PlaybackState = "idle" | "processing" | "speaking" | "paused";
type Listener = () => void;

const STT_RATE = 16_000;
const MAX_RECORDING_MS = 120_000;

export class AudioEngine {
  private ctx: AudioContext | null = null;
  private gain: GainNode | null = null;
  private playAnalyser: AnalyserNode | null = null;
  private micAnalyser: AnalyserNode | null = null;
  private listeners = new Set<Listener>();

  // ----- playback -----
  private pending: string[] = [];
  private ready: { buffer: AudioBuffer; text: string }[] = [];
  private current: AudioBufferSourceNode | null = null;
  private generation = 0;
  private synthesizing = false;
  private replyOpen = false;
  state: PlaybackState = "idle";
  caption = "";
  lastSpoken: string[] = [];
  error: string | null = null;
  volume = 0.9;
  speed = 1;

  // ----- capture -----
  private stream: MediaStream | null = null;
  private source: AudioNode | null = null;
  private processor: ScriptProcessorNode | null = null;
  private fixtureNodes: AudioScheduledSourceNode[] = [];
  private chunks: Float32Array[] = [];
  private captureTimer: ReturnType<typeof setTimeout> | null = null;
  capturing = false;
  onCaptureLost: ((reason: string) => void) | null = null;

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  private emit() {
    for (const fn of this.listeners) fn();
  }

  /** Create or resume the audio context (call from a click or key press when possible). */
  context(): AudioContext {
    if (!this.ctx) {
      const AC = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      this.ctx = new AC();
      this.gain = this.ctx.createGain();
      this.gain.gain.value = this.volume;
      this.playAnalyser = this.ctx.createAnalyser();
      this.playAnalyser.fftSize = 512;
      this.playAnalyser.smoothingTimeConstant = 0.6;
      this.gain.connect(this.playAnalyser);
      this.playAnalyser.connect(this.ctx.destination);
    }
    if (this.ctx.state === "suspended" && this.state !== "paused") void this.ctx.resume().catch(() => {});
    return this.ctx;
  }

  setVolume(v: number) {
    this.volume = Math.max(0, Math.min(1, v));
    if (this.gain) this.gain.gain.value = this.volume;
  }

  /** The analyser whose audio the ring should show right now. */
  analyser(): AnalyserNode | null {
    if (this.capturing) return this.micAnalyser;
    if (this.state === "speaking" || this.state === "paused") return this.playAnalyser;
    return null;
  }

  /** Current loudness (0..1, RMS) of what is being played or recorded. */
  level(): number {
    const a = this.analyser();
    if (!a) return 0;
    const buf = new Float32Array(a.fftSize);
    a.getFloatTimeDomainData(buf);
    let sum = 0;
    for (const v of buf) sum += v * v;
    return Math.sqrt(sum / buf.length);
  }

  private setState(s: PlaybackState) {
    if (this.state !== s) {
      this.state = s;
      this.emit();
    }
  }

  /** Begin a new spoken reply; earlier speech stops. */
  beginReply() {
    this.stop(false);
    this.replyOpen = true;
    this.lastSpoken = [];
  }

  /** No more sentences will come for this reply. */
  endReply() {
    this.replyOpen = false;
    if (!this.current && !this.synthesizing && this.pending.length === 0 && this.ready.length === 0) this.setState("idle");
  }

  enqueue(sentences: string[]) {
    const clean = sentences.map((s) => s.trim()).filter(Boolean);
    if (!clean.length) return;
    this.context();
    this.error = null;
    this.pending.push(...clean);
    this.lastSpoken.push(...clean);
    if (this.state === "idle") this.setState("processing");
    void this.pump();
  }

  /** Speak a whole text now (replay, preview). */
  speak(sentences: string[]) {
    this.beginReply();
    this.enqueue(sentences);
    this.endReply();
  }

  private async pump() {
    const gen = this.generation;
    // Keep one sentence synthesised ahead of the one playing.
    while (!this.synthesizing && this.pending.length > 0 && this.ready.length < 2 && gen === this.generation) {
      const text = this.pending.shift()!;
      this.synthesizing = true;
      try {
        const wav = await api.voiceSynthesize(text, this.speed);
        if (gen !== this.generation) return;
        const buffer = await this.context().decodeAudioData(wav.slice(0));
        if (gen !== this.generation) return;
        this.ready.push({ buffer, text });
      } catch (e) {
        if (gen !== this.generation) return;
        if (!(e instanceof AtlasError && e.code === "cancelled")) {
          this.error = e instanceof AtlasError ? e.message : "Speech playback failed";
          this.pending = [];
          this.emit();
        }
      } finally {
        if (gen === this.generation) this.synthesizing = false;
      }
      this.playNext();
    }
    this.playNext();
  }

  private playNext() {
    if (this.current || this.state === "paused") return;
    const item = this.ready.shift();
    if (!item) {
      if (!this.synthesizing && this.pending.length === 0) {
        this.caption = "";
        this.setState(this.replyOpen ? "processing" : "idle");
        if (!this.replyOpen) this.emit();
      }
      return;
    }
    const ctx = this.context();
    const src = ctx.createBufferSource();
    src.buffer = item.buffer;
    src.connect(this.gain!);
    const gen = this.generation;
    src.onended = () => {
      if (gen !== this.generation) return;
      this.current = null;
      this.playNext();
      void this.pump();
    };
    this.current = src;
    this.caption = item.text;
    this.setState("speaking");
    this.emit();
    src.start();
    void this.pump();
  }

  /** Stop speaking now. `interrupted` marks a user interruption (shown briefly by the ring). */
  stop(interrupted = true) {
    const wasActive = this.state !== "idle";
    this.generation++;
    this.pending = [];
    this.ready = [];
    this.synthesizing = false;
    this.replyOpen = false;
    if (this.current) {
      this.current.onended = null;
      try {
        this.current.stop();
      } catch {
        /* already stopped */
      }
      this.current = null;
    }
    if (this.ctx?.state === "suspended") void this.ctx.resume().catch(() => {});
    if (wasActive) void api.voiceStopSpeech().catch(() => {});
    this.caption = "";
    this.state = "idle";
    if (interrupted && wasActive) this.interruptedAt = performance.now();
    this.emit();
  }
  interruptedAt = 0;

  pause() {
    if (this.state !== "speaking" || !this.ctx) return;
    void this.ctx.suspend();
    this.setState("paused");
  }

  resume() {
    if (this.state !== "paused" || !this.ctx) return;
    void this.ctx.resume();
    this.setState(this.current ? "speaking" : "processing");
    this.playNext();
  }

  // ----- capture -----

  /** Start recording. `fixture` uses a synthetic test signal instead of a microphone (test builds). */
  async startCapture(opts: { deviceId?: string | null; fixture?: boolean } = {}): Promise<void> {
    if (this.capturing) return;
    this.stop(false);
    const ctx = this.context();
    await ctx.resume().catch(() => {});
    this.chunks = [];
    this.micAnalyser = ctx.createAnalyser();
    this.micAnalyser.fftSize = 512;
    this.micAnalyser.smoothingTimeConstant = 0.5;
    if (opts.fixture) {
      // A 180 Hz voice-like tone shaped into syllables by a 4 Hz envelope. Clearly a test signal.
      const osc = ctx.createOscillator();
      osc.frequency.value = 180;
      const env = ctx.createGain();
      env.gain.value = 0.25;
      const lfo = ctx.createOscillator();
      lfo.frequency.value = 4;
      const depth = ctx.createGain();
      depth.gain.value = 0.2;
      lfo.connect(depth).connect(env.gain);
      osc.connect(env);
      osc.start();
      lfo.start();
      this.fixtureNodes = [osc, lfo];
      this.source = env;
    } else {
      if (!navigator.mediaDevices?.getUserMedia) throw new AtlasError("unavailable", "This window has no microphone access.");
      try {
        this.stream = await navigator.mediaDevices.getUserMedia({
          audio: { deviceId: opts.deviceId ? { exact: opts.deviceId } : undefined, channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        });
      } catch (e) {
        throw new AtlasError("microphone", microphoneError(e));
      }
      for (const t of this.stream.getAudioTracks()) {
        t.onended = () => this.lose("The microphone was disconnected.");
      }
      this.source = ctx.createMediaStreamSource(this.stream);
    }
    this.source.connect(this.micAnalyser);
    // ScriptProcessor is deprecated but supported by both WebView2 and WebKitGTK without loading a
    // separate module; it only copies samples into memory.
    this.processor = ctx.createScriptProcessor(4096, 1, 1);
    this.processor.onaudioprocess = (ev) => {
      if (this.capturing) this.chunks.push(new Float32Array(ev.inputBuffer.getChannelData(0)));
    };
    const mute = ctx.createGain();
    mute.gain.value = 0;
    this.source.connect(this.processor);
    this.processor.connect(mute).connect(ctx.destination);
    this.capturing = true;
    this.captureTimer = setTimeout(() => this.lose("Recordings are limited to two minutes; listening stopped."), MAX_RECORDING_MS);
    this.emit();
  }

  private lose(reason: string) {
    if (!this.capturing) return;
    this.onCaptureLost?.(reason);
  }

  /** Stop recording and return the audio as 16 kHz 16-bit samples (the buffers are cleared). */
  stopCapture(): Int16Array {
    const rate = this.ctx?.sampleRate ?? 48_000;
    const merged = concat(this.chunks);
    this.release();
    const out = toInt16(resample(merged, rate, STT_RATE));
    merged.fill(0);
    return out;
  }

  /** Stop recording and discard it. */
  cancelCapture() {
    this.release();
  }

  private release() {
    this.capturing = false;
    if (this.captureTimer) clearTimeout(this.captureTimer);
    this.captureTimer = null;
    for (const c of this.chunks) c.fill(0);
    this.chunks = [];
    this.processor?.disconnect();
    if (this.processor) this.processor.onaudioprocess = null;
    this.processor = null;
    this.source?.disconnect();
    this.source = null;
    for (const n of this.fixtureNodes) {
      try {
        n.stop();
      } catch {
        /* stopped */
      }
    }
    this.fixtureNodes = [];
    for (const t of this.stream?.getTracks() ?? []) {
      t.onended = null;
      t.stop();
    }
    this.stream = null;
    this.emit();
  }
}

export function microphoneError(e: unknown): string {
  const name = e instanceof DOMException ? e.name : "";
  if (name === "NotAllowedError" || name === "SecurityError")
    return "Microphone access was declined. Allow it when Atlas asks, or in Windows Settings → Privacy & security → Microphone (\"Let desktop apps access your microphone\").";
  if (name === "NotFoundError" || name === "OverconstrainedError") return "No microphone was found. Connect one, or choose another in Settings → Voice.";
  if (name === "NotReadableError") return "The microphone is in use by another app or could not be started.";
  return "The microphone could not be started.";
}

export function concat(chunks: Float32Array[]): Float32Array {
  const n = chunks.reduce((s, c) => s + c.length, 0);
  const out = new Float32Array(n);
  let o = 0;
  for (const c of chunks) {
    out.set(c, o);
    o += c.length;
  }
  return out;
}

/** Downsample by averaging each output sample's input window (a simple low-pass). */
export function resample(input: Float32Array, from: number, to: number): Float32Array {
  if (from === to) return input.slice();
  const ratio = from / to;
  const n = Math.floor(input.length / ratio);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(input.length, Math.max(start + 1, Math.floor((i + 1) * ratio)));
    let sum = 0;
    for (let j = start; j < end; j++) sum += input[j] ?? 0;
    out[i] = sum / (end - start);
  }
  return out;
}

export function toInt16(input: Float32Array): Int16Array {
  const out = new Int16Array(input.length);
  for (let i = 0; i < input.length; i++) {
    const v = Math.max(-1, Math.min(1, input[i] ?? 0));
    out[i] = v < 0 ? v * 0x8000 : v * 0x7fff;
  }
  return out;
}

/** The one audio engine for the app. */
export const audio = new AudioEngine();
