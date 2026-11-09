/**
 * Turning Atlas's Markdown replies into speech. Only the reply text is ever spoken: never reasoning,
 * tool output or interface metadata (those arrive as separate events and never reach here).
 *
 * `toSpeech` rewrites one piece of Markdown into plain speakable text. `SentenceStream` takes the
 * reply as it streams in and hands back complete sentences as soon as they exist, so speaking can
 * start before a long reply has finished. Code blocks and tables are announced once, not read.
 */

const CODE_NOTE = "I've put the code on screen.";
const TABLE_NOTE = "There's a table on screen.";
const ABBREVIATIONS = new Set(["mr", "mrs", "ms", "dr", "prof", "st", "vs", "etc", "e.g", "i.e", "approx", "no", "fig", "inc", "ltd", "jr", "sr"]);

/** Make sure a fragment ends with punctuation so the voice pauses at line and list breaks. */
function terminate(s: string): string {
  const t = s.trim();
  if (!t) return "";
  return /[.!?…:;,]["')\]]*$/.test(t) ? t : `${t}.`;
}

/** Plain speakable text for one line of Markdown (no fences or tables; the stream handles those). */
export function lineToSpeech(line: string): string {
  let s = line;
  s = s.replace(/<[^>]+>/g, " ");
  s = s.replace(/^\s{0,3}(?:[-*_]\s*){3,}$/, ""); // horizontal rule
  const heading = /^\s{0,3}#{1,6}\s+/.test(s);
  const listItem = /^\s*(?:[-*+]|\d+[.)])\s+/.test(s);
  s = s.replace(/^\s{0,3}#{1,6}\s+/, "");
  s = s.replace(/^\s*>\s?/, "");
  s = s.replace(/^\s*(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?/, "");
  s = s.replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1");
  s = s.replace(/\[([^\]]+)\]\([^)]*\)/g, "$1");
  s = s.replace(/https?:\/\/[^\s)>\]]+/g, "a link");
  s = s.replace(/`([^`]+)`/g, (_, code: string) => (code.length <= 32 ? code : "the code shown"));
  s = s.replace(/(\*\*|__)(.+?)\1/g, "$2");
  s = s.replace(/(^|[\s(])[*_]([^*_\s][^*_]*?)[*_](?=[\s).,!?:;]|$)/g, "$1$2");
  s = s.replace(/~~(.+?)~~/g, "$1");
  s = s.replace(/\p{Extended_Pictographic}️?/gu, "");
  s = s.replace(/[*_#`|]/g, " ");
  s = s.replace(/\s+/g, " ").trim();
  return heading || listItem ? terminate(s) : s;
}

/** Plain speakable text for a whole Markdown message. */
export function toSpeech(md: string): string {
  const stream = new SentenceStream();
  return [...stream.push(md), ...stream.flush()].join(" ");
}

/** Index just after the last sentence boundary in `s`, or -1. */
export function lastBoundary(s: string): number {
  let found = -1;
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (c !== "." && c !== "!" && c !== "?" && c !== "…") continue;
    let j = i + 1;
    while (j < s.length && `"')]`.includes(s[j] ?? "")) j++;
    if (j >= s.length || s[j] !== " ") continue;
    let k = j;
    while (k < s.length && s[k] === " ") k++;
    if (k >= s.length) continue;
    if (!/[A-Z0-9"'([\u00C0-\u024F\u0600-\u06FF]/.test(s[k] ?? "")) continue;
    if (c === ".") {
      const word = s.slice(0, i).split(/\s/).pop()?.toLowerCase().replace(/^[("']+/, "") ?? "";
      if (ABBREVIATIONS.has(word) || /^[a-z]$/i.test(word)) continue;
    }
    found = k;
  }
  return found;
}

/** Split speakable text into sentences. */
export function splitSentences(text: string): string[] {
  const out: string[] = [];
  let rest = text.trim();
  for (;;) {
    const b = firstBoundary(rest);
    if (b < 0) break;
    out.push(rest.slice(0, b).trim());
    rest = rest.slice(b).trim();
  }
  if (rest) out.push(rest);
  return out.filter(Boolean);
}

function firstBoundary(s: string): number {
  for (let i = 0; i < s.length; i++) {
    const b = lastBoundary(s.slice(0, i + 2));
    if (b > 0) return b;
  }
  return -1;
}

/**
 * Incremental speech from a streaming Markdown reply. `push` returns sentences that are complete;
 * `flush` returns what remains at the end. Code blocks and tables are announced once each.
 */
export class SentenceStream {
  private line = "";
  private inFence = false;
  private inTable = false;

  push(delta: string): string[] {
    const out: string[] = [];
    this.line += delta;
    let nl: number;
    while ((nl = this.line.indexOf("\n")) >= 0) {
      const full = this.line.slice(0, nl);
      this.line = this.line.slice(nl + 1);
      out.push(...this.completeLine(full));
    }
    // Speak finished sentences of the line still being written (long paragraphs are one line).
    if (!this.inFence && !this.inTable && !/^\s*(```|~~~|\|)/.test(this.line)) {
      const b = lastBoundary(this.line);
      if (b > 0) {
        const ready = this.line.slice(0, b);
        this.line = this.line.slice(b);
        const spoken = lineToSpeech(ready);
        if (spoken) out.push(...splitSentences(spoken));
      }
    }
    return out;
  }

  flush(): string[] {
    const rest = this.line;
    this.line = "";
    const out = rest ? this.completeLine(rest) : [];
    this.inFence = false;
    this.inTable = false;
    return out;
  }

  reset(): void {
    this.line = "";
    this.inFence = false;
    this.inTable = false;
  }

  private completeLine(full: string): string[] {
    if (/^\s*(```|~~~)/.test(full)) {
      const opening = !this.inFence;
      this.inFence = !this.inFence;
      return opening ? [CODE_NOTE] : [];
    }
    if (this.inFence) return [];
    if (/^\s*\|.*\|\s*$/.test(full)) {
      if (this.inTable) return [];
      this.inTable = true;
      return [TABLE_NOTE];
    }
    this.inTable = false;
    const spoken = lineToSpeech(full);
    return spoken ? splitSentences(spoken) : [];
  }
}
