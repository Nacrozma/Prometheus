import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

// Windows and macOS file systems ignore case: two modules whose paths differ only in case (OrbitSpace.tsx and
// orbitSpace.ts) resolve to the same file there and break the Windows build, while Linux CI passes.
describe("source file names", () => {
  it("never differ only in letter case", () => {
    const seen = new Map<string, string>();
    const clashes: string[] = [];
    const walk = (dir: string) => {
      for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
        const p = path.join(dir, e.name);
        if (e.isDirectory()) walk(p);
        else {
          const key = p.toLowerCase().replace(/\.(tsx?|jsx?|mjs)$/, "");
          if (seen.has(key)) clashes.push(`${seen.get(key)} ↔ ${p}`);
          else seen.set(key, p);
        }
      }
    };
    for (const d of ["src", "tests"]) walk(path.resolve(__dirname, "../..", d));
    expect(clashes).toEqual([]);
  });
});
