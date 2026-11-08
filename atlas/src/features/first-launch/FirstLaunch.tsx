import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import { Emblem, useReducedMotion } from "@/components/Emblem";
import { api } from "@/lib/bridge";
import { DEDICATION, PHASES, scene, startTimes, WELCOME, type Phase } from "./sequence";
import { Starfield } from "./Starfield";

function globeSize(): number {
  const short = Math.min(window.innerWidth, window.innerHeight);
  return Math.round(Math.min(220, Math.max(96, short * 0.26)));
}

/**
 * The one-time introduction: a deep-navy universe, stars, the Atlas globe, the creator's
 * dedication and Atlas's first words. It sits above the app, which stays inert underneath and is
 * ready the moment it ends. Skip (button or Esc) is always available. With reduced motion it is
 * a still scene where only the words change.
 *
 * `mode="first"` records completion in the core when it ends or is skipped; closing the app
 * part-way leaves it unrecorded, so it plays again next time. `mode="replay"` records nothing.
 */
export function FirstLaunch({ mode, onDone }: { mode: "first" | "replay"; onDone: () => void }) {
  const reducedNow = useReducedMotion();
  // The timeline is fixed when the introduction starts.
  const [reduced] = useState(reducedNow);
  const [phase, setPhase] = useState<Phase>("void");
  const [globe, setGlobe] = useState(globeSize);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const finished = useRef(false);
  const rootRef = useRef<HTMLDivElement>(null);

  const finish = useCallback(() => {
    if (finished.current) return;
    finished.current = true;
    timers.current.forEach(clearTimeout);
    // Never blocks: if recording fails, the app opens anyway and the introduction plays next launch.
    if (mode === "first") void api.completeFirstLaunch().catch((e) => console.warn("[atlas] the introduction could not be recorded", e));
    onDone();
  }, [mode, onDone]);

  useEffect(() => {
    const t = startTimes(reduced);
    timers.current = PHASES.slice(1).map((p) => setTimeout(() => setPhase(p), t[p]));
    return () => timers.current.forEach(clearTimeout);
  }, [reduced]);

  useEffect(() => {
    if (phase === "done") finish();
  }, [phase, finish]);

  const skip = useCallback(() => {
    if (finished.current) return;
    timers.current.forEach(clearTimeout);
    setPhase("leaving");
    timers.current = [setTimeout(finish, reduced ? 0 : 450)];
  }, [finish, reduced]);

  useEffect(() => {
    // Focus the scene (not the Skip button) so no focus ring appears; Tab reaches Skip, Esc skips.
    rootRef.current?.focus({ preventScroll: true });
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        skip();
      }
    };
    const onResize = () => setGlobe(globeSize());
    window.addEventListener("keydown", onKey);
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", onResize);
    };
  }, [skip]);

  const s = scene(phase);
  const fade = (ms: number): CSSProperties => (reduced ? { transition: "none" } : { transition: `opacity ${ms}ms cubic-bezier(0.65, 0, 0.35, 1), transform ${ms}ms cubic-bezier(0.2, 0.8, 0.2, 1)` });
  // Words fade out, then leave the accessibility tree and the page text.
  const line = (on: boolean, ms: number): CSSProperties => ({
    opacity: on ? 1 : 0,
    visibility: on ? "visible" : "hidden",
    transform: on || reduced ? "none" : "translateY(6px)",
    transition: reduced ? "none" : `opacity ${ms}ms ease, transform ${ms}ms cubic-bezier(0.2, 0.8, 0.2, 1), visibility 0s linear ${on ? 0 : ms}ms`,
  });

  return (
    <div
      data-first-launch={mode}
      data-phase={phase}
      data-reduced={String(reduced)}
      ref={rootRef}
      tabIndex={-1}
      role="region"
      aria-label="Introduction"
      className="fixed inset-0 z-[60] overflow-hidden select-none outline-none"
      style={{ background: "#02050c", opacity: s.leaving ? 0 : 1, ...fade(800) }}
    >
      {/* The universe lights up behind the globe. */}
      <div
        aria-hidden
        className="absolute inset-0"
        style={{
          background:
            "radial-gradient(62vmax 46vmax at 50% 40%, rgb(28 143 184 / 0.24), transparent 64%), radial-gradient(90vmax 60vmax at 50% 118%, rgb(45 212 191 / 0.09), transparent 62%), linear-gradient(#02050c, #050c1a)",
          opacity: s.lit ? 1 : 0.35,
          ...fade(1800),
        }}
      />
      <div aria-hidden className="absolute inset-0" style={{ opacity: s.stars ? 1 : 0, ...fade(1600) }}>
        <Starfield reduced={reduced} className="h-full w-full" />
      </div>

      <div className="relative flex h-full flex-col items-center justify-center px-6">
        <div style={{ opacity: s.globe ? 1 : 0, transform: s.globe || reduced ? "none" : "scale(0.93)", ...fade(1700) }}>
          <Emblem size={globe} animated={!reduced && s.globe} glow={s.lit} />
        </div>
        <div role="status" aria-live="polite" className="relative mt-[6vh] h-[6.5em] w-full max-w-3xl text-center">
          <p
            data-dedication
            aria-hidden={!s.dedication}
            className="absolute inset-x-0 top-0 font-display font-light"
            style={{ ...line(s.dedication, 1400), fontSize: "clamp(1.6rem, 3.4vw, 2.75rem)", letterSpacing: "0.02em", color: "#eaf8ff", textShadow: "0 0 28px rgb(60 207 230 / 0.35)" }}
          >
            {DEDICATION}
          </p>
          <p
            data-welcome
            aria-hidden={!s.welcome}
            className="absolute inset-x-0 top-0 font-display"
            style={{ ...line(s.welcome, 1100), fontSize: "clamp(1.05rem, 1.9vw, 1.45rem)", color: "rgb(214 236 250 / 0.9)" }}
          >
            {WELCOME}
          </p>
        </div>
      </div>

      <button
        type="button"
        onClick={skip}
        aria-label="Skip the introduction"
        className="absolute bottom-6 right-6 rounded-md px-3 py-1.5 text-xs uppercase tracking-[0.2em] text-[rgb(214_236_250/0.55)] outline-none transition-colors hover:text-[rgb(234_248_255/0.95)] focus-visible:ring-2 focus-visible:ring-[rgb(60_207_230/0.7)]"
      >
        Skip
      </button>
    </div>
  );
}
