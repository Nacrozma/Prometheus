/**
 * The first-launch introduction: a fixed timeline of phases. Pure so it can be tested without a
 * browser. The component schedules one timer per phase change; nothing here touches the DOM.
 */

/** The creator's dedication. Shown exactly as written; never altered, translated or logged. */
export const DEDICATION = "Created with love.";
/** Atlas's first words, exactly as written; it never uses the owner's name. */
export const WELCOME = "Welcome. I'm Atlas. It's good to finally meet you.";

export type Phase = "void" | "stars" | "globe" | "illuminate" | "dedication" | "welcome" | "leaving" | "done";

export const PHASES: readonly Phase[] = ["void", "stars", "globe", "illuminate", "dedication", "welcome", "leaving", "done"];

/** Start time of each phase, in ms from the start. */
const FULL: Record<Phase, number> = {
  void: 0,
  stars: 700,
  globe: 1900,
  illuminate: 3500,
  dedication: 4700, // reading time to the next phase: 4.3 s
  welcome: 9000, // 3.8 s
  leaving: 12800,
  done: 13600,
};

/** Reduced motion: no movement, the scene appears at once; the words keep their reading time. */
const REDUCED: Record<Phase, number> = {
  void: 0,
  stars: 0,
  globe: 0,
  illuminate: 0,
  dedication: 400,
  welcome: 4400,
  leaving: 8000,
  done: 8000,
};

export function startTimes(reduced: boolean): Record<Phase, number> {
  return reduced ? REDUCED : FULL;
}

/** The phase showing `ms` after the start. */
export function phaseAt(ms: number, reduced: boolean): Phase {
  const t = startTimes(reduced);
  let current: Phase = "void";
  for (const p of PHASES) if (ms >= t[p]) current = p;
  return current;
}

export function totalMs(reduced: boolean): number {
  return startTimes(reduced).done;
}

/** Whether a phase has been reached (phases only move forward). */
export function reached(current: Phase, target: Phase): boolean {
  return PHASES.indexOf(current) >= PHASES.indexOf(target);
}

/** What is on screen in a phase. */
export function scene(phase: Phase) {
  return {
    stars: reached(phase, "stars"),
    globe: reached(phase, "globe"),
    lit: reached(phase, "illuminate"),
    dedication: phase === "dedication",
    welcome: phase === "welcome",
    leaving: reached(phase, "leaving"),
  };
}

/** Whether the introduction plays at startup: only until it has finished or been skipped once. */
export function shouldPlayAtStartup(completedAt: string | null | undefined): boolean {
  return !completedAt;
}
