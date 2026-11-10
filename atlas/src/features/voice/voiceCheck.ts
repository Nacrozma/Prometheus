/**
 * The Voice check: measurements taken on the owner's real microphone and speakers.
 * Everything here is text and numbers. No audio is kept, and the report goes nowhere unless the
 * owner copies it.
 */
import type { VoiceStatus } from "@/lib/schemas";

/** The sentence the owner reads aloud (the same one the engine benchmark uses). */
export const CHECK_PHRASE = "Hello Atlas, please remind me to call my sister tomorrow at nine in the morning.";
/** The sentence Atlas speaks for the speaker check. */
export const SPEAKER_PHRASE = "This is Atlas, speaking on your computer. If you can hear this clearly, the speaker check has passed.";

export const CONDITIONS = ["Quiet room", "Background noise", "Speaking fast", "Speaking slowly", "Headset microphone", "Far from the microphone"] as const;
export type Condition = (typeof CONDITIONS)[number];

export interface MicResult {
  kind: "microphone";
  at: string;
  condition: Condition;
  device: string;
  model: string;
  language: string;
  backend: string;
  sampleRate: number;
  speechMs: number;
  transcribeMs: number;
  peakLevel: number;
  transcript: string;
  accuracy: number;
}

export interface SpeakerResult {
  kind: "speaker";
  at: string;
  device: string;
  voice: string;
  firstAudioMs: number;
  heard: "clearly" | "with problems" | "not at all";
}

export type CheckResult = MicResult | SpeakerResult;

const NUMBER_WORDS: Record<string, string> = {
  "0": "zero",
  "1": "one",
  "2": "two",
  "3": "three",
  "4": "four",
  "5": "five",
  "6": "six",
  "7": "seven",
  "8": "eight",
  "9": "nine",
  "10": "ten",
  "11": "eleven",
  "12": "twelve",
};

/** Lower-case words without punctuation; small numbers are spelled out so "9" matches "nine". */
export function normaliseWords(s: string): string[] {
  return s
    .toLowerCase()
    .split(/[^\p{L}\p{N}]+/u)
    .filter(Boolean)
    .map((w) => NUMBER_WORDS[w] ?? w);
}

/** Share of the expected words recognised, in order (longest common subsequence). 0..1. */
export function wordAccuracy(expected: string, heard: string): number {
  const r = normaliseWords(expected);
  const h = normaliseWords(heard);
  if (r.length === 0) return 0;
  let prev = new Array<number>(h.length + 1).fill(0);
  for (let i = 1; i <= r.length; i++) {
    const row = new Array<number>(h.length + 1).fill(0);
    for (let j = 1; j <= h.length; j++) {
      row[j] = r[i - 1] === h[j - 1] ? (prev[j - 1] ?? 0) + 1 : Math.max(prev[j] ?? 0, row[j - 1] ?? 0);
    }
    prev = row;
  }
  return (prev[h.length] ?? 0) / r.length;
}

/** A plain-language reading of one microphone attempt. */
export function micVerdict(r: Pick<MicResult, "accuracy" | "peakLevel" | "speechMs" | "transcribeMs">): string {
  if (r.peakLevel < 0.01) return "Almost no sound reached Atlas. Check the microphone choice and its level in Windows.";
  if (r.accuracy >= 0.93) return r.transcribeMs > r.speechMs * 1.5 ? "Accurate, but slow on this PC. A smaller model would answer sooner." : "Accurate and quick.";
  if (r.accuracy >= 0.8) return "Mostly right. A larger model, or speaking closer to the microphone, should help.";
  return "Many words were missed. Try a larger model, a quieter room or a different microphone.";
}

const pct = (v: number) => `${Math.round(v * 100)}%`;
const secs = (ms: number) => `${(ms / 1000).toFixed(2)} s`;

/** The report the owner can copy: machine, devices, models and every attempt. No audio, no ids. */
export function formatReport(results: CheckResult[], status: VoiceStatus | null, appVersion: string): string {
  const hw = status?.hardware;
  const lines = [
    "ATLAS voice check report",
    `Atlas ${appVersion}${status?.fixtures ? " (TEST BUILD: stand-in engines, not real speech)" : ""}`,
    hw ? `Computer: ${hw.os} ${hw.arch}, ${hw.cpu}, ${hw.logical_cores} cores, ${Math.round(hw.total_memory_mb / 1024)} GB memory` : "Computer: unknown",
    "",
  ];
  const speakers = results.filter((r): r is SpeakerResult => r.kind === "speaker");
  const mics = results.filter((r): r is MicResult => r.kind === "microphone");
  lines.push(`Speaker checks: ${speakers.length}`);
  for (const r of speakers) {
    lines.push(`- ${r.at} | ${r.device} | voice ${r.voice} | first sound after ${secs(r.firstAudioMs)} | heard ${r.heard}`);
  }
  lines.push("", `Microphone checks: ${mics.length}`);
  for (const r of mics) {
    lines.push(
      `- ${r.at} | ${r.condition} | ${r.device} | ${r.model} (${r.language}) | spoke ${secs(r.speechMs)} | recognised in ${secs(r.transcribeMs)} | ` +
        `words right ${pct(r.accuracy)} | peak level ${r.peakLevel.toFixed(3)} | capture ${r.backend} at ${r.sampleRate} Hz`,
      `  heard: "${r.transcript}"`,
    );
  }
  if (mics.length) {
    const avg = mics.reduce((s, r) => s + r.accuracy, 0) / mics.length;
    lines.push("", `Average words right: ${pct(avg)} over ${mics.length} attempt${mics.length === 1 ? "" : "s"}`);
  }
  lines.push("", `Phrase read aloud: "${CHECK_PHRASE}"`, "This report contains no audio. It was not sent anywhere.");
  return lines.join("\n");
}
