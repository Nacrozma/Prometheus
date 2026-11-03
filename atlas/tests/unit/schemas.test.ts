import { describe, expect, it } from "vitest";
import { relativeTime, formatUsd } from "@/lib/format";
import { TurnEventSchema, SettingsSchema } from "@/lib/schemas";

describe("IPC schemas", () => {
  it("accepts a valid turn event and rejects a malformed one", () => {
    expect(TurnEventSchema.safeParse({ type: "text_delta", text: "x" }).success).toBe(true);
    expect(TurnEventSchema.safeParse({ type: "text_delta", text: 5 }).success).toBe(false);
    expect(TurnEventSchema.safeParse({ type: "unknown_event" }).success).toBe(false);
  });

  it("rejects settings with unknown enum values", () => {
    const bad = { companion: { tone: "sarcastic" } };
    expect(SettingsSchema.safeParse(bad).success).toBe(false);
  });
});

describe("format helpers", () => {
  it("labels unknown costs honestly", () => {
    expect(formatUsd(null)).toBe("unknown");
    expect(formatUsd(0.004)).toBe("< $0.01");
    expect(formatUsd(1.234)).toBe("$1.23");
  });
  it("formats relative times", () => {
    const now = Date.parse("2026-01-01T12:00:00Z");
    expect(relativeTime("2026-01-01T11:59:50Z", now)).toBe("just now");
    expect(relativeTime("2026-01-01T11:00:00Z", now)).toBe("1 h ago");
    expect(relativeTime(null, now)).toBe("never");
  });
});
