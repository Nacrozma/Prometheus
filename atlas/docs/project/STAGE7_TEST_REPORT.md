# Stage 7 test report: personality depth, specialists and orchestration

**Date:** 2026-11-15 · **Branch:** `claude/prometheus-ai-evaluation-pxqzfr` · **Platform:** Linux x86_64
container (Xvfb, WebKitWebDriver). Windows and macOS: CI on push, not run here. **Not released.**
Design: `docs/SPECIALISTS.md`.

## Results (all on the final code)

| Suite | Command | Result |
|---|---|---|
| Rust core, unit | `cargo test -p atlas-core` (lib) | 131 passed, 1 ignored (OS keyring). New: specialist registry/result validation/suggestion 3, personality layering 1 |
| Rust core, integration | (same, `tests/*.rs`) | 102 passed: **specialists 9** (new), engine 31, vault 13, trust 8, focus 8, scheduler 8, voice 9, todos 7, sibling bridge 6, briefing 3 |
| Rust core, ignored by design | (same) | 6: live providers 2, real Prometheus runtime 1, real voice engines 1, opt-in Vault fixture check 1, OS keyring 1 |
| Rust desktop shell | `cargo test -p atlas-desktop` | 2 passed |
| Clippy `-D warnings` | core all targets; shell all targets with `--features e2e` | clean |
| Frontend | `tsc`, `eslint src tests`, `vitest run` | clean, clean, **92 passed** (18 files; 88 before + 4 Specialists/Trust tests) |
| End-to-end, main phase | `tests/e2e/run.sh` → `app.e2e.mjs` | **27 of 27** (26 before + the specialists test; the accessibility audit now includes the Specialists page) |
| End-to-end, restart phase | `restart.e2e.mjs` | **1 of 1** (now also: mission history survives; a mission running at close is interrupted, not resumed) |
| Production/test separation | `tests/release/no-test-hooks.sh` | production debug binary: none of the 5 test hooks; e2e binary: all 5 |

Totals: Rust 235 passed, 0 failed. Frontend 92. End-to-end 28 of 28.

## What the tests cover

| Requirement | Test |
|---|---|
| Layered personality; identity and rules fixed across presets; adaptation; voice line only with voice output | `identity_and_rules_stay_fixed_while_style_and_adaptation_vary` |
| Sequential workflow, results passed forward as data, attribution, audit | core `a_two_specialist_workflow_passes_results_forward…`; e2e step 1–2 (Planner → Project Coordinator, "built on the earlier result") |
| Malformed output: one repair, then `invalid_output`, mission `partial` | core |
| Tool outside the allowlist refused and recorded | core (`specialist.tool_refused`) |
| Writes ask the owner; declined → nothing written; no self-approval | core |
| Least context: memories only for specialists that declare them, none with memory off | core |
| Cancellation stops the running specialist and starts no further one | core and e2e (step 4) |
| Budgets, specialist switches, Settings switch, validation (unknown, duplicate, Forge project required) | core; e2e (switched-off specialist refused) |
| Atlas consults a specialist in a conversation; a simple question does not | core; e2e step 3 |
| Restart: running missions interrupted; schema 8 → 9 upgrade with data | core; restart phase |
| Trust Center records every specialist step without content | e2e step 6 (no objective text in the log); Trust sentences unit test |
| UI shows only backend states (awaiting approval from the task, not guessed) | `tests/unit/specialists.test.tsx` |

## Automated, simulated, not validated

* **Automated, real code:** the core (orchestrator, dispatcher, approvals, policy, budgets, audit), SQLite,
  the UI in the real webview.
* **Simulated:** the model. The scripted e2e model returns a valid specialist result for any specialist
  prompt (and waits for cancellation when the objective says "slowly"), and calls `specialist.consult` for
  "Ask your specialists to …". Core tests use the mock provider with scripted replies.
* **Not validated:** the quality of real models acting as specialists; cloud providers end-to-end; Engineer
  and Security Reviewer end-to-end with a real Forge project (covered in the core); Windows and macOS.

## Defects found during this stage

| Defect | Fix | Test |
|---|---|---|
| Cancelling a mission recorded the running specialist as **failed** when the model honoured the cancellation before the orchestrator noticed it (found by the e2e test) | The cancellation branch is checked first and a cancelled token always means "cancelled by you" | core cancellation test now asserts the running step; e2e step 4 |
| A command name clashed with the sibling mission commands | Renamed to `specialist_mission_*` | shell build |
| A frontend type name (`Mission`) clashed with sibling missions | Renamed `SpecialistMission` | typecheck |
| "1 projects" in a step's context line | Singular/plural | screenshot 26b |

## Security checks

* Specialists run through the same dispatcher with the live settings: approvals, gates, offline mode and
  grants apply unchanged; switches and budgets are rechecked before each model call.
* The tool list a specialist sees is its allowlist ∩ registered ∩ enabled ∩ available; anything else is
  refused and recorded.
* No objective, prompt, result or document text in the activity record (e2e).
* Earlier results and passages are quoted as data; the prompt says to ignore instructions inside them.

## Connectors

Mobbin: unavailable (paid plan). No new libraries were needed. Sentry and Supabase: not used.
