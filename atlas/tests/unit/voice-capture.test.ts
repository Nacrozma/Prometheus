import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/bridge", () => ({
  AtlasError: class AtlasError extends Error {
    constructor(
      public code: string,
      message: string,
    ) {
      super(message);
    }
  },
  api: { voiceSynthesize: vi.fn(), voiceStopSpeech: vi.fn().mockResolvedValue(null) },
}));

// A Web Audio stand-in with worklet and output-device support, recording how capture was wired.
const log: string[] = [];
let workletFails = false;
let sinkFails: string | null = null;
const node = () => ({ gain: { value: 1 }, frequency: { value: 0 }, connect: (x: unknown) => x, disconnect() {}, start() {}, stop() {} });
class FakeWorkletNode {
  static last: FakeWorkletNode | null = null;
  port = { onmessage: null as ((e: { data: Float32Array }) => void) | null, postMessage: (m: unknown) => log.push(`port:${String(m)}`) };
  constructor(_ctx: unknown, name: string) {
    log.push(`worklet-node:${name}`);
    FakeWorkletNode.last = this;
  }
  connect(x: unknown) {
    return x;
  }
  disconnect() {
    log.push("worklet-disconnect");
  }
}
class FakeCtx {
  state = "running";
  sampleRate = 48_000;
  destination = {};
  sink = "";
  audioWorklet = {
    addModule: (url: string) => {
      log.push(`module:${url}`);
      return workletFails ? Promise.reject(new Error("blocked")) : Promise.resolve();
    },
  };
  createGain = node;
  createOscillator = node;
  createAnalyser() {
    return { ...node(), fftSize: 512, smoothingTimeConstant: 0, getFloatTimeDomainData: (b: Float32Array) => b.fill(0.2) };
  }
  createScriptProcessor() {
    log.push("script-processor");
    return { ...node(), onaudioprocess: null };
  }
  resume() {
    return Promise.resolve();
  }
  setSinkId(id: string) {
    if (id === sinkFails) return Promise.reject(new Error("gone"));
    this.sink = id;
    log.push(`sink:${id || "default"}`);
    return Promise.resolve();
  }
}
(window as unknown as { AudioContext: unknown }).AudioContext = FakeCtx;
(globalThis as unknown as { AudioWorkletNode: unknown }).AudioWorkletNode = FakeWorkletNode;

const { AudioEngine } = await import("@/features/voice/audioEngine");
const { wordAccuracy, normaliseWords, micVerdict, formatReport, CHECK_PHRASE } = await import("@/features/voice/checkReport");

describe("microphone capture", () => {
  it("collects samples through the audio worklet, loads the module once, and releases it on stop", async () => {
    log.length = 0;
    const e = new AudioEngine();
    await e.startCapture({ fixture: true });
    expect(e.captureBackend).toBe("worklet");
    expect(log.filter((l) => l.startsWith("module:"))).toEqual(["module:/voice-capture.worklet.js"]);
    expect(log).not.toContain("script-processor");
    // 0.5 s of audio arrives from the audio thread in blocks.
    for (let i = 0; i < 12; i++) FakeWorkletNode.last!.port.onmessage!({ data: new Float32Array(2048).fill(0.5) });
    const pcm = e.stopCapture();
    expect(pcm.length).toBe(Math.floor((12 * 2048) / 3));
    expect(pcm[10]).toBeGreaterThan(16_000);
    expect(log).toContain("port:stop");
    expect(log).toContain("worklet-disconnect");
    expect(e.capturing).toBe(false);

    await e.startCapture({ fixture: true });
    expect(log.filter((l) => l.startsWith("module:")).length).toBe(1);
    e.cancelCapture();
  });

  it("falls back to the older capture path when the worklet cannot load", async () => {
    log.length = 0;
    workletFails = true;
    const e = new AudioEngine();
    await e.startCapture({ fixture: true });
    expect(e.captureBackend).toBe("script-processor");
    expect(log).toContain("script-processor");
    e.cancelCapture();
    workletFails = false;
  });
});

describe("output device", () => {
  it("applies the chosen device, and falls back to the default when it is gone", async () => {
    log.length = 0;
    const e = new AudioEngine();
    expect(e.outputSelectable()).toBe(true);
    e.preferOutput("headset-1"); // remembered; no audio context is created just for this
    expect(log).toEqual([]);
    e.context();
    await Promise.resolve();
    expect(log).toContain("sink:headset-1");
    sinkFails = "usb-2";
    expect(await e.setOutputDevice("usb-2")).toBe(false);
    expect(log.at(-1)).toBe("sink:default");
    sinkFails = null;
    expect(await e.setOutputDevice(null)).toBe(true);
  });
});

describe("voice check", () => {
  it("scores recognised words in order, treating digits and number words alike", () => {
    expect(normaliseWords("At 9, call!")).toEqual(["at", "nine", "call"]);
    expect(wordAccuracy(CHECK_PHRASE, "Hello Atlas, please remind me to call my sister tomorrow at 9 in the morning.")).toBe(1);
    expect(wordAccuracy(CHECK_PHRASE, "Alo atlas please remind me to call my sister tomorrow at nine in the morning")).toBeCloseTo(14 / 15);
    expect(wordAccuracy(CHECK_PHRASE, "")).toBe(0);
    expect(wordAccuracy("one two three four", "four three two one")).toBe(0.25);
  });

  it("explains a result in plain words", () => {
    expect(micVerdict({ accuracy: 0, peakLevel: 0.001, speechMs: 4000, transcribeMs: 900 })).toContain("no sound");
    expect(micVerdict({ accuracy: 1, peakLevel: 0.2, speechMs: 4000, transcribeMs: 900 })).toBe("Accurate and quick.");
    expect(micVerdict({ accuracy: 1, peakLevel: 0.2, speechMs: 4000, transcribeMs: 9000 })).toContain("slow");
    expect(micVerdict({ accuracy: 0.5, peakLevel: 0.2, speechMs: 4000, transcribeMs: 900 })).toContain("missed");
  });

  it("writes a report with devices, timings and accuracy, and flags test builds", () => {
    const status = { fixtures: false, hardware: { os: "windows", arch: "x86_64", cpu: "Test CPU", logical_cores: 8, total_memory_mb: 16_384 } } as never;
    const report = formatReport(
      [
        { kind: "speaker", at: "10:00:00", device: "Headphones", voice: "Alba", firstAudioMs: 1840, heard: "clearly" },
        { kind: "microphone", at: "10:01:00", condition: "Quiet room", device: "USB mic", model: "Whisper base", language: "en", backend: "worklet", sampleRate: 48_000, speechMs: 4300, transcribeMs: 3200, peakLevel: 0.31, transcript: "hello atlas", accuracy: 0.8 },
      ],
      status,
      "0.4.1",
    );
    expect(report).toContain("Atlas 0.4.1");
    expect(report).toContain("Test CPU, 8 cores, 16 GB");
    expect(report).toContain("Headphones | voice Alba | first sound after 1.84 s | heard clearly");
    expect(report).toContain("Quiet room | USB mic | Whisper base (en) | spoke 4.30 s | recognised in 3.20 s | words right 80%");
    expect(report).toContain("contains no audio");
    expect(report).not.toContain("TEST BUILD");
    expect(formatReport([], { fixtures: true, hardware: null } as never, "x")).toContain("TEST BUILD");
  });
});
