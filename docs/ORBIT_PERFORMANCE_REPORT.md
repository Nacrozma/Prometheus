# ORBIT — Performance report

Measured 2026-11-19 in the Linux container (offscreen Qt, painted-sun fallback for the paint test). Plan: 80 tasks,
6 phases, 70 dependencies (the maximum task count).

| Operation (Prometheus) | Time |
|---|---|
| normalise a plan | 0.55 ms |
| one cycle-checked edit | 0.50 ms |
| build a workflow | 1.97 ms |
| load a session (30 versions) | 5.0 ms |
| save a session (30 versions, 899 KB file) | **40.5 ms** on the UI thread |
| paint the stage with 80 bodies (grab) | 26 ms |

Design choices for resource use: the stage repaints only on change; the only animation timer runs while new bodies
settle and stops after 0.6 s; the avatar keeps its existing frame-rate policy (paused when hidden, still under
reduce motion); the turn-taker does constant work per level sample; streamed text re-renders the transcript per
delta.

**Finding:** session files grow with every version (full plan copy per version). At 30 versions of a maximal plan a
save costs ~40 ms and happens after each step transition. Acceptable now; recommended next step: store versions as
diffs or move saves off the UI thread.

Atlas: plan operations run in Rust on the command thread (same algorithms, not separately measured); the stage is
SVG re-rendered by React on session change.
