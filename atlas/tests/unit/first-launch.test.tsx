import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FirstLaunch } from "@/features/first-launch/FirstLaunch";
import { DEDICATION, PHASES, WELCOME, phaseAt, scene, shouldPlayAtStartup, startTimes, totalMs } from "@/features/first-launch/sequence";

const complete = vi.fn().mockResolvedValue({});
vi.mock("@/lib/bridge", () => ({ api: { completeFirstLaunch: () => complete() } }));

describe("introduction timeline", () => {
  it("keeps the dedication and welcome exactly as written", () => {
    expect(DEDICATION).toBe("Created with love.");
    expect(WELCOME).toBe("Welcome. I'm Atlas. It's good to finally meet you.");
  });

  it("moves forward through every phase, with time to read the words", () => {
    for (const reduced of [false, true]) {
      const t = startTimes(reduced);
      const starts = PHASES.map((p) => t[p]);
      expect([...starts].sort((a, b) => a - b)).toEqual(starts);
      expect(t.welcome - t.dedication).toBeGreaterThanOrEqual(3500);
      expect(t.leaving - t.welcome).toBeGreaterThanOrEqual(3000);
      expect(phaseAt(t.dedication + 1, reduced)).toBe("dedication");
      expect(phaseAt(totalMs(reduced), reduced)).toBe("done");
    }
    expect(totalMs(true)).toBeLessThan(totalMs(false));
    expect(totalMs(false)).toBeLessThanOrEqual(15000);
  });

  it("shows one line of words at a time", () => {
    for (const p of PHASES) {
      const s = scene(p);
      expect(s.dedication && s.welcome).toBe(false);
    }
  });

  it("plays at startup only until it has been completed or skipped once", () => {
    expect(shouldPlayAtStartup(null)).toBe(true);
    expect(shouldPlayAtStartup("2026-11-08T10:00:00Z")).toBe(false);
  });
});

describe("<FirstLaunch>", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    complete.mockClear();
    delete document.documentElement.dataset.motion;
  });
  afterEach(() => vi.useRealTimers());

  const advanceTo = (ms: number) => act(() => void vi.advanceTimersByTime(ms));
  const visible = (el: Element) => (el as HTMLElement).style.visibility === "visible";

  it("plays through, shows the dedication exactly once, and records completion once", () => {
    const done = vi.fn();
    const { container } = render(<FirstLaunch mode="first" onDone={done} />);
    const ded = container.querySelector("[data-dedication]")!;
    const wel = container.querySelector("[data-welcome]")!;
    expect(ded.textContent).toBe("Created with love.");
    expect(visible(ded)).toBe(false);

    advanceTo(startTimes(false).dedication + 10);
    expect(container.querySelector("[data-phase]")!.getAttribute("data-phase")).toBe("dedication");
    expect(visible(ded)).toBe(true);
    expect(visible(wel)).toBe(false);

    advanceTo(startTimes(false).welcome - startTimes(false).dedication);
    expect(visible(wel)).toBe(true);
    expect(visible(ded)).toBe(false);
    expect(wel.textContent).toBe(WELCOME);

    advanceTo(totalMs(false));
    expect(done).toHaveBeenCalledTimes(1);
    expect(complete).toHaveBeenCalledTimes(1);
  });

  it("can be skipped with the button or Esc at any moment", () => {
    const done = vi.fn();
    render(<FirstLaunch mode="first" onDone={done} />);
    advanceTo(1000);
    fireEvent.click(screen.getByRole("button", { name: "Skip the introduction" }));
    advanceTo(500);
    expect(done).toHaveBeenCalledTimes(1);
    expect(complete).toHaveBeenCalledTimes(1);
    // Later timers from the original timeline do nothing.
    advanceTo(totalMs(false));
    expect(done).toHaveBeenCalledTimes(1);

    const done2 = vi.fn();
    render(<FirstLaunch mode="replay" onDone={done2} />);
    fireEvent.keyDown(window, { key: "Escape" });
    advanceTo(500);
    expect(done2).toHaveBeenCalledTimes(1);
  });

  it("does not record anything when replayed", () => {
    const done = vi.fn();
    render(<FirstLaunch mode="replay" onDone={done} />);
    advanceTo(totalMs(false));
    expect(done).toHaveBeenCalledTimes(1);
    expect(complete).not.toHaveBeenCalled();
  });

  it("is a still scene with reduced motion: no transitions, words keep their reading time", () => {
    document.documentElement.dataset.motion = "reduced";
    const done = vi.fn();
    const { container } = render(<FirstLaunch mode="replay" onDone={done} />);
    const root = container.querySelector("[data-first-launch]") as HTMLElement;
    expect(root.dataset.reduced).toBe("true");
    expect(root.style.transition).toBe("none");
    advanceTo(startTimes(true).dedication + 10);
    expect(visible(container.querySelector("[data-dedication]")!)).toBe(true);
    advanceTo(totalMs(true));
    expect(done).toHaveBeenCalledTimes(1);
  });

  it("never blocks the app if recording completion fails", async () => {
    complete.mockRejectedValueOnce(new Error("database busy"));
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const done = vi.fn();
    render(<FirstLaunch mode="first" onDone={done} />);
    fireEvent.keyDown(window, { key: "Escape" });
    advanceTo(500);
    expect(done).toHaveBeenCalledTimes(1);
    await act(async () => {});
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });
});
