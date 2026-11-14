# Stage 4 test report: Focus Mode and "While you were away"

**Date:** 2026-11-14 · **Branch:** `claude/prometheus-ai-evaluation-pxqzfr` · **Platform:** Linux x86_64
container (Xvfb, WebKitWebDriver). Windows and macOS: covered by CI on push, not run here.
**Not released.** Nothing was published.

## Results

| Suite | Command | Result |
|---|---|---|
| Rust core, unit | `cargo test -p atlas-core` (lib) | 110 passed, 1 ignored (OS keyring; runs on Windows CI) |
| Rust core, integration | (same, `tests/*.rs`) | 72 passed: briefing 3, engine 31, **focus 8**, scheduler 8, sibling bridge 6, todos 7, voice 9 |
| Rust core, ignored by design | (same) | 4: live providers 2 (need keys), real Prometheus runtime 1, real voice engines 1 |
| Rust desktop shell | `cargo test -p atlas-desktop` | 2 passed |
| Clippy, `-D warnings` | core all targets; shell all targets, with and without `--features e2e` | clean |
| Frontend | `pnpm typecheck`, `pnpm lint`, `vitest run` | clean, clean, **75 passed** (15 files; 69 before this stage's verification + 5 test-hook guards + 1 countdown regression) |
| End-to-end, main phase | `tests/e2e/run.sh` → `app.e2e.mjs` | **24 of 24** |
| End-to-end, restart phase | `tests/e2e/run.sh` → `restart.e2e.mjs` (same app, same data folder, relaunched) | **1 of 1** |
| Production/test separation (compiled) | `tests/release/no-test-hooks.sh` | production binary: no test hooks; e2e binary: hooks present (the check can see them) |

Total Rust: 184 passed, 0 failed. End-to-end: 25 of 25.

The final end-to-end run used the build from commit `40d3264` plus the test-only change in `c91b823`.
After it, two clippy lints in older e2e-only code (`src-tauri/src/e2e.rs`) were fixed without changing
behaviour (`return Ok(x.await?)` → `return x.await`; a nested `if` collapsed). The end-to-end suite was
not rerun for that refactor.

## What is automated, what is mocked, what was not validated

* **Automated, real app:** the end-to-end suite drives the real desktop binary (Rust core, SQLite,
  React UI) over WebDriver. The model is a scripted stand-in (no provider key); keys are in memory.
* **Simulated:** the two hours away. Before start-up, the test build alone moves the recorded "last
  active" time and the running Focus session back by two hours. Everything after that is the real
  start-up path. The hook is compiled only with `--features e2e` (checked in the compiled binaries).
* **Not validated here:** Windows and macOS (CI), real providers, system notifications on a real
  desktop (the e2e build records them instead of showing them), real elapsed hours.

## Defects found and fixed during verification

| Defect | Effect | Fix | Regression test |
|---|---|---|---|
| `raise` took the database lock again (via `focus::is_active`) while holding it | Atlas froze on the first notice raised during a Focus session | Check on the held connection, under the same lock as the write | `desktop::tests::raising_during_focus_does_not_deadlock_…` (fails on a deadline, not a hang) |
| A session that ran out while Atlas was closed ended "now" | Closed hours counted as focus time | Ends at its planned end | `focus::tests::a_session_that_ran_out_while_closed_…`, restart e2e (15 minutes) |
| Releasing held notices was two statements | Summary count could differ from what was released | One transaction | integration: released once, none lost |
| Recap replaced by a second absence; damaged times; clock set back | Lost events; "everything" recap; stuck mark | Keep earliest unread start; unreadable = no recap; refresh a future mark | `recap::tests::*` (4) |
| Countdown kept the clock from mount time | A new 40-minute session showed 41:50 for a second | Read the clock when the session changes | `focus.test.tsx` countdown test |
| Focus bar laid out from `left: 50%` | Task title squeezed to zero width; bar covered the page header | In-flow strip at the top of the page column | e2e: title text and rendered width |
| Reminders titled "Reminder" | Summary and recap did not say which task | Name the task ("Reminder: Stretch break") | integration `the_summary_and_recap_say_which_task…`, e2e |
| Test hooks reachable only by convention | Risk of shipping test commands | `cfg(test-support/e2e)` gates; source guard; binary check in CI and release | `test-hooks-gated.test.ts`, `no-test-hooks.sh` |

The missing task title had two parts. The bar really was squeezed (layout bug, fixed). Separately,
WebKitWebDriver's visible-text heuristic leaves out spans with `overflow: hidden` even when they are
drawn, which the screenshots confirm. Such text is now checked by content and rendered width.

## Acceptance coverage

* **Entry points:** Home (15-minute preset with a label), Tasks (a task's Focus button opens the dialog
  with that task chosen), the dialog itself (all four presets present; a 40-minute custom length).
* **One session at a time; length limits:** refused by the core (e2e and unit).
* **Holding:** reminders, replies, mission updates and the briefing are held (integration); in the real
  app a reminder is held with no toast and no system notice; an approval raised mid-session arrives
  unheld and is declined (nothing written). Only the approval and the failure reach the system notifier.
* **Summary:** exactly what was held, once; elapsed minutes from recorded times.
* **Recap after a real restart:** the reply waiting for approval is marked interrupted, its approval is
  gone, the file was never written (unchanged modification time), Open shows the conversation and starts
  nothing; the Focus session completed at its planned 15 minutes with one summary; every notification
  from before the restart is kept; the to-do survived; the recap is shown once and stays dismissed.
* **Schema 6:** upgrades from every earlier schema keep settings and notifications; a retry is a no-op;
  a failed v6 rolls back to v5 with no half-made table and then succeeds; a fresh database starts at 6.
* **Production separation:** compiled production binary (`cargo build -p atlas-desktop`, no features)
  contains none of `e2e_recap_since`, `shift_back_for_test`, `e2e-away-minutes`,
  `recap_begin_minutes_ago`; the normal command `recap_get` is present as a control. The e2e binary
  (`--features e2e`) contains all four.

## Screenshots (from the final end-to-end run)

`docs/screenshots/21-focus-start.png`, `21b-focus-running.png`, `21c-focus-summary.png`,
`22-recap.png` (taken after the real relaunch). Reviewed: real app, title visible, countdown consistent
with the session (14:54 of 15:00), summary names the reminder, recap shows recorded activity only.

## Connectors used

Parallel Search (WebDriver "Get Element Text" returns rendered text only, per the W3C spec) and
Context7 (library lookup). Mobbin was not available (paid plan required). Sentry and Supabase were not
used: Atlas has no Sentry or Supabase integration (local SQLite only).
