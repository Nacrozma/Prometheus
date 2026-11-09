import { describe, expect, it } from "vitest";
import { SentenceStream, lastBoundary, lineToSpeech, splitSentences, toSpeech } from "@/features/voice/speechText";

describe("speakable text", () => {
  it("drops Markdown syntax but keeps the words", () => {
    expect(lineToSpeech("## Your **plan** for _today_")).toBe("Your plan for today.");
    expect(lineToSpeech("- Buy milk")).toBe("Buy milk.");
    expect(lineToSpeech("3. Call [Sam](https://example.com/x) at 9")).toBe("Call Sam at 9.");
    expect(lineToSpeech("See https://example.com/docs for more")).toBe("See a link for more");
    expect(lineToSpeech("Run `npm test` or `a-very-long-command --with --many --flags here`")).toBe("Run npm test or the code shown");
    expect(lineToSpeech("> quoted <b>bold</b> 🚀 text")).toBe("quoted bold text");
  });

  it("announces code and tables instead of reading them", () => {
    const md = "Here is the fix.\n```rust\nfn main() {}\n```\nAnd a summary:\n| a | b |\n|---|---|\n| 1 | 2 |\nDone.";
    expect(toSpeech(md)).toBe("Here is the fix. I've put the code on screen. And a summary: There's a table on screen. Done.");
  });

  it("splits sentences but not abbreviations, initials or decimals", () => {
    expect(splitSentences("Hello there. It costs 3.50 today! Ask Dr. Smith, e.g. tomorrow? Yes.")).toEqual([
      "Hello there.",
      "It costs 3.50 today!",
      "Ask Dr. Smith, e.g. tomorrow?",
      "Yes.",
    ]);
    expect(lastBoundary("No boundary yet")).toBe(-1);
  });
});

describe("streaming sentences", () => {
  it("returns complete sentences as they arrive and the rest at the end", () => {
    const s = new SentenceStream();
    const got: string[] = [];
    for (const piece of ["Sure. Here", " is the first", " step. Then ", "the second"]) got.push(...s.push(piece));
    expect(got).toEqual(["Sure.", "Here is the first step."]);
    expect(s.flush()).toEqual(["Then the second"]);
  });

  it("never speaks inside a code block, even when it streams in pieces", () => {
    const s = new SentenceStream();
    const got: string[] = [];
    for (const piece of ["Try this:\n``", "`py\nprint('Hello. World.')\n", "```\nThat prints a greeting."]) got.push(...s.push(piece));
    got.push(...s.flush());
    expect(got).toEqual(["Try this:", "I've put the code on screen.", "That prints a greeting."]);
  });

  it("reset forgets a discarded attempt", () => {
    const s = new SentenceStream();
    s.push("```\nhalf a code block");
    s.reset();
    expect([...s.push("Fresh start."), ...s.flush()]).toEqual(["Fresh start."]);
  });
});
