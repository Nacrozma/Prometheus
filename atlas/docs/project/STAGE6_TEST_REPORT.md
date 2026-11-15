# Stage 6 test report: memory quality and the Trust Center

**Date:** 2026-11-15 · **Branch:** `claude/prometheus-ai-evaluation-pxqzfr` · **Platform:** Linux x86_64
container (Xvfb, WebKitWebDriver). Windows and macOS: CI on push, not run here. **Not released.**
Design: `docs/MEMORY.md`, `docs/TRUST_CENTER.md`.

## Results (all on the final code)

| Suite | Command | Result |
|---|---|---|
| Rust core, unit | `cargo test -p atlas-core` (lib) | 127 passed, 1 ignored (OS keyring; Windows CI). New: memory lifecycle 3 (duplicates and conflicts, corrections/supersession/outdated/review, budget), audit 1, Trust Center 1 |
| Rust core, integration | (same, `tests/*.rs`) | 93 passed: **trust 8** (new), vault 13, engine 31, focus 8, scheduler 8, briefing 3, sibling bridge 6, todos 7, voice 9 |
| Rust core, ignored by design | (same) | 6: live providers 2, real Prometheus runtime 1, real voice engines 1, opt-in Vault fixture check 1, OS keyring 1 |
| Rust desktop shell | `cargo test -p atlas-desktop` | 2 passed |
| Clippy `-D warnings` | core all targets; shell all targets with `--features e2e` | clean |
| Frontend | `pnpm typecheck`, `pnpm lint`, `vitest run` | clean, clean, **88 passed** (17 files; 82 before + 6 Trust Center and Memory tests) |
| End-to-end, main phase | `tests/e2e/run.sh` → `app.e2e.mjs` | **26 of 26** (25 before + the Memory and Trust Center test; the accessibility audit now includes the Trust Center) |
| End-to-end, restart phase | `restart.e2e.mjs` | **1 of 1** (now also checks memories and the activity record after relaunch) |
| Production/test separation | `tests/release/no-test-hooks.sh` | production debug binary: none of the 5 test hooks; e2e binary: all 5 |

Totals: Rust 222 passed, 0 failed. Frontend 88. End-to-end 27 of 27.

## The directive's end-to-end flow (§13)

| # | Step | Where |
|---|---|---|
| 1 | Create a useful memory | e2e: Atlas proposes, the owner approves in the conversation |
| 2 | Retrieve it later | e2e: a new conversation; the scripted model answers only from the memories it was given |
| 3–4 | Correct it; the corrected one is used | e2e: Memory page edit; history shows "Corrected" with the old wording; the next answer uses the new text |
| 5–6 | Remove it; no longer retrieved | e2e |
| 7–8 | Disable memory creation; none created | e2e: switched off in the Trust Center; the next proposal is refused by the core (no approval, nothing saved) |
| 9–10 | Import a Vault document; in the Trust Center | e2e: `vault.import` (by you) |
| 11–12 | Document question; transmission recorded | e2e: `vault.passages` with the document name, provider, model, stayed on this computer |
| 13–14 | Revoke a permission; the core refuses | e2e (memory suggestions); core: offline mode turned on while an approval waited stops the action; a gate tightened applies to the very next action |
| 15–16 | Restart; memory and activity persist | restart phase |

## Automated, simulated, not validated

* **Automated, real code:** the core (engine, dispatcher, approvals, policy, memory, audit), SQLite, the UI
  in the real webview.
* **Simulated:** the model (scripted: proposes memories when asked, answers only from the memories and
  passages in its request); `test.fetch` (a test-only tool that stands in for an internet tool, compiled only
  with test support).
* **Not validated end-to-end:** cloud providers (the e2e model is local, so "left this computer" is false
  there; the true case is covered by `test.fetch` in the core tests and by `provider.request` using
  `ProviderKind::is_local`), Windows and macOS.

## Defects found during this stage

| Defect | Fix | Test |
|---|---|---|
| Permissions were decided from the settings captured when the turn started: a gate tightened mid-turn, or offline mode turned on while an approval waited, did not apply to that turn | Decide from the live settings at request and execution time, and again after the approval | `a_permission_revoked_while_an_approval_waits…`, `the_next_action_follows_the_settings…` |
| Duplicate detection (new code) used search terms, which drop numbers and short words: "room 12" and "room 14" would collide | Compare every word | memory unit test |
| Owner-started Vault actions were recorded as Atlas's | Recorded with actor "user" | screenshot 25b |

## Performance (measured, debug build)

5,000 audit events written in 346 ms; one filtered timeline page in 0.45 ms; a memory search over 2,000
memories in 13 ms (`scale_thousands_of_events_and_memories_stay_fast`). The UI loads the timeline 40
events at a time.

## Security checks

* No secret in the activity log (redaction test); no message, memory or document text in it (core and e2e).
* The window cannot authorize: controls call validated commands; the dispatcher enforces at execution.
* Memories are labelled as overridable, never instructions; a document cannot create a memory (the tool
  description forbids it, and every proposal needs the owner's approval).
* The activity log is read-only from the Trust Center; clearing it is itself recorded.

## Connectors

Mobbin: unavailable (paid plan). No new libraries were needed, so Context7 and Parallel Search were not
used this stage. Sentry and Supabase: not used; Atlas has neither.
