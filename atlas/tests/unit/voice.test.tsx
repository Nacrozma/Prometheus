import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const synth = vi.fn();
const stopSpeech = vi.fn().mockResolvedValue(null);
const transcribe = vi.fn();
const cancelTranscription = vi.fn().mockResolvedValue(true);
vi.mock("@/lib/bridge", () => ({
  AtlasError: class AtlasError extends Error {
    constructor(
      public code: string,
      message: string,
    ) {
      super(message);
    }
  },
  api: {
    voiceSynthesize: (...a: unknown[]) => synth(...a),
    voiceStopSpeech: () => stopSpeech(),
    voiceTranscribe: (...a: unknown[]) => transcribe(...a),
    voiceCancelTranscription: () => cancelTranscription(),
  },
}));

// A minimal Web Audio stand-in that records what is played.
class FakeSource {
  buffer: unknown = null;
  onended: (() => void) | null = null;
  started = false;
  stopped = false;
  connect() {}
  start() {
    this.started = true;
    sources.push(this);
  }
  stop() {
    this.stopped = true;
  }
}
let sources: FakeSource[] = [];
class FakeCtx {
  state = "running";
  sampleRate = 48_000;
  destination = {};
  createGain() {
    return { gain: { value: 1 }, connect: (x: unknown) => x, disconnect() {} };
  }
  createAnalyser() {
    return { fftSize: 512, smoothingTimeConstant: 0, frequencyBinCount: 256, connect: (x: unknown) => x, getFloatTimeDomainData: (b: Float32Array) => b.fill(0.25) };
  }
  createBufferSource() {
    return new FakeSource();
  }
  createOscillator() {
    return { frequency: { value: 0 }, connect: (x: unknown) => x, start() {}, stop() {} };
  }
  createScriptProcessor() {
    return { onaudioprocess: null, connect: (x: unknown) => x, disconnect() {} };
  }
  decodeAudioData(b: ArrayBuffer) {
    return Promise.resolve({ duration: b.byteLength });
  }
  resume() {
    this.state = "running";
    return Promise.resolve();
  }
  suspend() {
    this.state = "suspended";
    return Promise.resolve();
  }
}
(window as unknown as { AudioContext: unknown }).AudioContext = FakeCtx;

const { AudioEngine, resample, toInt16, concat } = await import("@/features/voice/audioEngine");
const { computeBands, BANDS, STATE_INDEX } = await import("@/features/voice/ringShader");
const { voicePhase, useVoice } = await import("@/state/voice");
const { VoiceRing } = await import("@/features/voice/VoiceRing");

const flush = () => new Promise((r) => setTimeout(r, 0));

describe("speech playback queue", () => {
  beforeEach(() => {
    sources = [];
    synth.mockReset();
    stopSpeech.mockClear();
  });

  it("synthesises one sentence ahead, plays in order and returns to idle", async () => {
    synth.mockImplementation((text: string) => Promise.resolve(new ArrayBuffer(text.length)));
    const e = new AudioEngine();
    e.beginReply();
    e.enqueue(["First.", "Second one.", "Third sentence here."]);
    expect(e.state).toBe("processing");
    await flush();
    await flush();
    expect(e.state).toBe("speaking");
    expect(e.caption).toBe("First.");
    expect(synth.mock.calls.map((c) => c[0])).toEqual(["First.", "Second one.", "Third sentence here."].slice(0, synth.mock.calls.length));
    expect(e.level()).toBeGreaterThan(0.2); // read from the playback analyser
    sources[0]!.onended?.();
    await flush();
    expect(e.caption).toBe("Second one.");
    sources[1]!.onended?.();
    await flush();
    await flush();
    expect(e.caption).toBe("Third sentence here.");
    e.endReply();
    sources[2]!.onended?.();
    await flush();
    expect(e.state).toBe("idle");
    expect(synth).toHaveBeenCalledTimes(3);
  });

  it("stop silences at once, cancels synthesis and ignores late results", async () => {
    let release: (v: ArrayBuffer) => void = () => {};
    synth.mockImplementationOnce(() => Promise.resolve(new ArrayBuffer(4))).mockImplementation(() => new Promise((r) => (release = r)));
    const e = new AudioEngine();
    e.speak(["One.", "Two.", "Three."]);
    await flush();
    await flush();
    expect(e.state).toBe("speaking");
    e.stop();
    expect(e.state).toBe("idle");
    expect(sources[0]!.stopped).toBe(true);
    expect(stopSpeech).toHaveBeenCalledTimes(1);
    expect(e.interruptedAt).toBeGreaterThan(0);
    release(new ArrayBuffer(8)); // the engine finishes after the stop
    await flush();
    await flush();
    expect(sources).toHaveLength(1); // nothing new played
    expect(e.state).toBe("idle");
  });

  it("pause and resume keep the place; a synthesis error is reported, not retried", async () => {
    synth.mockResolvedValueOnce(new ArrayBuffer(4)).mockRejectedValueOnce(new Error("engine missing"));
    const e = new AudioEngine();
    e.speak(["A.", "B."]);
    await flush();
    await flush();
    e.pause();
    expect(e.state).toBe("paused");
    e.resume();
    expect(e.state).toBe("speaking");
    await flush();
    expect(e.error).toBe("Speech playback failed");
    expect(synth).toHaveBeenCalledTimes(2);
  });
});

describe("audio helpers", () => {
  it("downsamples to 16 kHz and converts to 16-bit without clipping errors", () => {
    const one = new Float32Array(48_000).fill(0.5);
    const r = resample(one, 48_000, 16_000);
    expect(r.length).toBe(16_000);
    expect(r[100]).toBeCloseTo(0.5);
    const i = toInt16(new Float32Array([0, 1, -1, 2, -2]));
    expect(Array.from(i)).toEqual([0, 32767, -32768, 32767, -32768]);
    expect(concat([new Float32Array([1]), new Float32Array([2, 3])]).length).toBe(3);
  });

  it("folds a spectrum into bands with fast attack and slow release", () => {
    const out = new Float32Array(BANDS);
    const loud = new Uint8Array(256).fill(255);
    computeBands(loud, out);
    expect(out[0]).toBeCloseTo(0.55, 2);
    computeBands(loud, out);
    expect(out[0]!).toBeGreaterThan(0.75);
    const silent = new Uint8Array(256);
    const before = out[0]!;
    computeBands(silent, out);
    expect(out[0]!).toBeLessThan(before);
    expect(out[0]!).toBeGreaterThan(before * 0.8); // released slowly, no flicker
  });
});

describe("voice ring and phases", () => {
  const base = { status: { tts_ready: true, stt_ready: true } as never, settings: { enabled: true } as never, capture: "off" as const, playback: "idle" as const, error: null, awaitingReply: false, interruptedAt: 0 };

  it("derives one visible state with listening and speaking taking priority", () => {
    expect(voicePhase(base, 10_000)).toBe("idle");
    expect(voicePhase({ ...base, capture: "listening", playback: "speaking" }, 10_000)).toBe("listening");
    expect(voicePhase({ ...base, capture: "transcribing" }, 10_000)).toBe("transcribing");
    expect(voicePhase({ ...base, playback: "speaking" }, 10_000)).toBe("speaking");
    expect(voicePhase({ ...base, playback: "paused" }, 10_000)).toBe("paused");
    expect(voicePhase({ ...base, awaitingReply: true }, 10_000)).toBe("processing");
    expect(voicePhase({ ...base, interruptedAt: 9_800 }, 10_000)).toBe("interrupted");
    expect(voicePhase({ ...base, error: "x" }, 10_000)).toBe("error");
    expect(voicePhase({ ...base, settings: { enabled: false } as never }, 10_000)).toBe("offline");
    expect(Object.keys(STATE_INDEX)).toHaveLength(9);
  });

  it("falls back to a static ring without WebGL2 and labels its state", () => {
    const { container, rerender } = render(<VoiceRing phase="speaking" size={64} />);
    const el = container.querySelector("[data-voice-ring]") as HTMLElement;
    expect(el.dataset.renderer).toBe("static");
    expect(el.dataset.state).toBe("speaking");
    expect(el.getAttribute("aria-label")).toBe("Speaking");
    rerender(<VoiceRing phase="offline" size={64} />);
    expect(el.dataset.state).toBe("offline");
  });
});

describe("push-to-talk store", () => {
  beforeEach(() => {
    transcribe.mockReset();
    useVoice.setState({ capture: "off", error: null, draft: null });
  });

  it("refuses clearly when voice is off or recognition isn't set up", async () => {
    useVoice.setState({ settings: { enabled: false } as never, status: null });
    await useVoice.getState().startListening();
    expect(useVoice.getState().error).toContain("Voice is off");
    useVoice.setState({ settings: { enabled: true } as never, status: { stt_ready: false } as never });
    await useVoice.getState().startListening();
    expect(useVoice.getState().error).toContain("isn't set up");
    expect(useVoice.getState().capture).toBe("off");
  });

  it("turns a recording into a draft, never sends it itself, and reports silence", async () => {
    useVoice.setState({ settings: { enabled: true, input_device: null, volume: 90, speed: 1 } as never, status: { stt_ready: true, fixtures: true } as never });
    transcribe.mockResolvedValueOnce({ text: " What is 6 times 7? ", audio_ms: 1200, elapsed_ms: 80, engine: "fixture" });
    await useVoice.getState().startListening();
    expect(useVoice.getState().capture).toBe("listening");
    await useVoice.getState().stopListening();
    expect(useVoice.getState().capture).toBe("off");
    expect(useVoice.getState().draft?.text).toBe("What is 6 times 7?");
    const [pcm, rate] = transcribe.mock.calls[0]!;
    expect(rate).toBe(16_000);
    expect(pcm).toBeInstanceOf(Int16Array);

    transcribe.mockResolvedValueOnce({ text: "", audio_ms: 800, elapsed_ms: 50, engine: "fixture" });
    await useVoice.getState().startListening();
    await useVoice.getState().stopListening();
    expect(useVoice.getState().error).toContain("didn't catch anything");

    await useVoice.getState().startListening();
    useVoice.getState().cancelListening();
    expect(useVoice.getState().capture).toBe("off");
  });
});
