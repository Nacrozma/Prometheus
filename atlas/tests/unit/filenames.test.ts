import { describe, expect, it } from "vitest";

// Windows and macOS file systems ignore case: two modules whose paths differ only in case (OrbitSpace.tsx and
// orbitSpace.ts) resolve to the same file there and break the Windows build, while Linux CI passes.
// Vite lists the files at build time, so no Node APIs are needed (the app's tsconfig has no Node types).
const files = Object.keys(import.meta.glob(["/src/**/*.{ts,tsx,js,jsx,css}", "/tests/**/*.{ts,tsx,js,jsx,mjs}"]));

describe("source file names", () => {
  it("are listed", () => expect(files.length).toBeGreaterThan(50));
  it("never differ only in letter case", () => {
    const seen = new Map<string, string>();
    const clashes: string[] = [];
    for (const p of files) {
      const key = p.toLowerCase().replace(/\.(tsx?|jsx?|mjs)$/, "");
      const prev = seen.get(key);
      if (prev) clashes.push(`${prev} ↔ ${p}`);
      else seen.set(key, p);
    }
    expect(clashes).toEqual([]);
  });
});
