# ORBIT — Test report

Date: 2026-11-19 · Linux container (Python 3.13, PyQt6 offscreen/xvfb; Rust stable; Node 22).

## Prometheus

| Suite | Result |
|---|---|
| `python -m pytest tests -q` (whole suite, after ORBIT) | **498 passed, 2 skipped** (the 2 skips are pre-existing Linux skips) |
| `tests/test_orbit.py` (new) | 13 passed: plan normalisation (loops, bounds, proposals), plan extraction/partial/strip, every edit + refusals (loop, ambiguous name, bad priority), spoken commands, versions/compare/store/path-traversal/quarantine, workflow order and transitions, autonomy (manual always waits, balanced holds changes), recovery pauses and never re-runs, unknown operations never map to a tool, turn-taking (end of turn, cough, pause inside speech, idle once, adaptive floor) |
| Window smoke test (`tests/test_desktop_app.py`, extended) | passed: ORBIT page opens; edits make versions; undo is a new version; *Build workflow* disabled before approval; approval-first start → awaiting approval (nothing runs); an Architect step refuses a write before any card; an ordinary step raises the real approval card and records awaiting approval; Deny is passed to the worker and the step returns to running; immersive hides navigation and leaving the page restores it; outline lists the plan; reopening the session pauses the running step |
| `python -m app --self-test` | every section including ORBIT: ok |

Not tested here: a real model turn producing a plan (no provider in CI; the parser path is unit-tested and the
screenshot script uses a sample reply through the same parser), real microphone/speaker hardware (the turn-taker is
tested with level sequences), Windows (the Windows workflow runs on push — see `ORBIT_RELEASE_READINESS.md`).

## Atlas

| Suite | Result |
|---|---|
| `cargo test -p atlas-core` (whole core, after ORBIT, schema 10) | **all passed** (lib 137 passed / 1 ignored, plus every integration suite) |
| `orbit` Rust unit tests (new, 6) | loops dropped, unknown operations → atlas; extract/strip; edits and refusals; approval gate before build, one step at a time, no edits while running, completion unblocks, failure blocks, retry restores; manual always waits, recovery pauses; undo/restore/compare |
| `cargo check -p atlas-desktop` (Tauri commands) | passed |
| `npx tsc -b` | passed |
| `npx vitest run` (whole suite) | **100 passed** (19 files) incl. `tests/unit/orbit.test.ts` (8: turn-taking, commands, ambiguity, streaming, strip, layout on orbits, session contract) |
| `npx eslint` on changed folders | 0 errors, 8 hook-dependency warnings in `Orbit.tsx` (warnings do not fail `pnpm lint`) |

Not run: Atlas WebDriver e2e (`tests/e2e/run.sh` needs a built Tauri app) and a real turn against a provider.
