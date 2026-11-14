// Production/test separation: commands that exist only for the automated-test build (they stand
// in for real time passing, and so on) must be compiled out of the desktop app. This reads the
// Rust sources and fails if any such command, its registration, or the core method behind it
// loses its feature gate. The built binaries are also checked for the command name (see
// docs/project/STAGE4_TEST_REPORT.md).
import { describe, expect, it } from "vitest";
import appRs from "../../core/src/app.rs?raw";
import recapRs from "../../core/src/recap.rs?raw";
import commandsRs from "../../src-tauri/src/commands.rs?raw";
import cargoToml from "../../src-tauri/Cargo.toml?raw";
import bridgeTs from "../../src/lib/bridge.ts?raw";

const files: Record<string, string> = {
  "core/src/app.rs": appRs,
  "core/src/recap.rs": recapRs,
  "src-tauri/src/commands.rs": commandsRs,
  "src-tauri/Cargo.toml": cargoToml,
  "src/lib/bridge.ts": bridgeTs,
};
const src = (p: string): string => files[p] ?? "";

describe("test-only hooks stay out of the desktop app", () => {
  const commands = src("src-tauri/src/commands.rs");
  const lines = commands.split("\n");

  it("gates every e2e_ command function behind the e2e feature", () => {
    const fns = lines.map((l: string, i: number) => [l, i] as const).filter(([l]) => /\bfn e2e_\w+/.test(l));
    expect(fns.length).toBeGreaterThan(0);
    for (const [l, i] of fns) {
      const above = lines.slice(Math.max(0, i - 4), i).join("\n");
      expect(above, l).toContain('#[cfg(feature = "e2e")]');
    }
  });

  it("gates every e2e_ registration in the command handler", () => {
    const regs = lines.filter((l: string) => /^\s*(#\[cfg[^\]]*\]\s*)?e2e_\w+,/.test(l));
    expect(regs.length).toBeGreaterThan(0);
    for (const l of regs) expect(l, l).toMatch(/#\[cfg\(feature = "e2e"\)\]\s*e2e_\w+,/);
  });

  it("compiles the recap stand-in only with test support", () => {
    const app = src("core/src/app.rs");
    const recap = src("core/src/recap.rs");
    expect(app).toMatch(/#\[cfg\(any\(test, feature = "test-support"\)\)\]\s*pub fn recap_begin_minutes_ago/);
    expect(recap).toMatch(/#\[cfg\(any\(test, feature = "test-support"\)\)\]\s*pub fn begin_at/);
  });

  it("turns test support on only for the e2e build", () => {
    const cargo = src("src-tauri/Cargo.toml");
    expect(cargo).toMatch(/^e2e = \["atlas-core\/test-support"\]$/m);
    expect(cargo).not.toMatch(/atlas-core = \{[^}]*features = \[[^\]]*test-support/);
    const dflt = cargo.match(/^default = \[(.*)\]$/m)?.[1] ?? "";
    expect(dflt).not.toContain("e2e");
  });

  it("never calls a test hook from the app's own code", () => {
    const ui = src("src/lib/bridge.ts");
    expect(ui).not.toMatch(/e2e_(recap|seed|reset)/);
  });
});
