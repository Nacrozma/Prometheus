# Phase 7 acceptance test report

**Date:** 2026-11-07
**Branch:** `claude/prometheus-ai-evaluation-pxqzfr`
**Release under test:** ATLAS Co-Pilot 0.2.0
* Tag `atlas-v0.2.0`, commit `1ad604d`.
* Installer sha256 `85fbda3b…0711108`.

**Environments:**
* Linux container: Ubuntu 24.04, Rust stable, Node 22, Python 3.13.
* GitHub Actions: Windows Server 2025, macOS and Ubuntu runners.
* Network policy in the container: reaches `api.anthropic.com`; blocks OpenAI, OpenRouter, Mistral, Cerebras, the Ollama registry and Hugging Face.
* No provider keys were provided. The owner declined the credential request.

**Result categories:** PASS, FAIL, BLOCKED, MANUAL TEST REQUIRED, NOT IMPLEMENTED, NOT APPLICABLE.
* A row shows more than one category when parts of an area differ.
* No BLOCKED, MANUAL or NOT IMPLEMENTED item was counted as PASS.

## 1. Summary

| Area | Result | Evidence | Outstanding work |
|---|---|---|---|
| Installation | **PASS** on a real Windows VM; visual review MANUAL TEST REQUIRED | `atlas-install-test.yml` run 42371543862 against the **published** installers. Checks: install, launch, database v3, restart, settings persist, no credential strings, uninstall keeps data, 0.1.0→0.2.0 upgrade with backup | Owner looks at the installed app on the target Windows 10/11 PC |
| Providers | Key handling **PASS**; connection, discovery, timeouts and rate limits tested against mocks only; live inference **BLOCKED**; live invalid-key **PASS** (Anthropic only) | PROVIDER_VALIDATION.md; `live_invalid_keys_are_rejected_and_classified` (live 401 → "rejected the API key", key not echoed) | Run `live_providers` with real keys (§7) |
| Model routing | **PASS** (real engine, scripted provider) | `routing_modes_send_the_tier_model_they_announce`, `shut_down_models_are_never_routed_to`, budget tests; pricing audit against vendor pages | Pricing for gpt-5.4 and gpt-5.5 stays unverified (not listed by OpenAI) |
| Prometheus adapter | **PASS** (real adapter process, Linux, macOS and now Windows) | `tests/test_sibling_adapter.py` (16), `core/tests/sibling_bridge.rs` (6). Windows had been silently skipping these; fixed in this phase, see S7 | none |
| Actual Prometheus runtime | **PASS** for the real runtime, tools, router and gates. Inference by Prometheus's own model **BLOCKED** (scripted stand-in on Ollama's port) | `core/tests/real_prometheus_runtime.rs`; REAL_PROMETHEUS_INTEGRATION.md | Run once with Prometheus's own key or a local Ollama model (§7) |
| Consultation | Approval, exact sharing and attribution **PASS**; an answer written by Prometheus's own model **BLOCKED** | `consulting_prometheus_needs_approval_and_shares_only_the_approved_text`; real-runtime consultation (system prompt is Prometheus's own) | Same live run as above |
| Collaborative engineering | Ledger flow (plan → approve → send → Prometheus works → REVIEWING → owner decides) **PASS**. Structured multi-task plan and code-change transfer for review **NOT IMPLEMENTED** | `test_collaborative_mission_round_trips_messages`; real runtime `RUNNING → REVIEWING` (never auto-accepted) | Shared Mission Workspace (manifest, hashes, patches); structured plans |
| Delegated engineering | **PASS** | Real runtime: workspace confinement, private files never leaked (7 attempts), dangerous tools refused, rejected approval sends nothing, cancellation, no duplicate execution after restart | With `--allow-dangerous`, `execute_shell` runs in Prometheus's folder (S6, documented) |
| Mission ledger | **PASS**; a wall-clock mission timeout is **NOT IMPLEMENTED** (8-step limit instead) | `state_machine_is_enforced_in_the_backend`, `ingest_is_idempotent_and_maps_remote_states`, `lost_contact_pauses_instead_of_claiming_running`, `atlas_restart_during_a_mission_resumes_without_resending`, real-runtime disconnect and restart | Interrupting a single long tool call on Prometheus's side |
| Atlas Forge | **PASS** (all four profiles, backend-enforced) | `forge_architect_reads_but_cannot_edit`, `forge_builder_edit_requires_approval_and_can_be_reverted`, `forge_debugger_reproduces_fixes_with_approval_and_proves_the_fix`, `forge_reconstructor_adds_files_but_cannot_edit_or_overwrite`, path, symlink and command-policy unit tests; e2e "Atlas Forge" | Forge's real-model quality needs live keys |
| Security and approvals | **PASS** after fixes S1 (critical), S2, S3, S4, S7 | SECURITY_AUDIT.md | none open above Info |
| Memory isolation | **PASS** | Private memory reaches Atlas's model but never a mission (consult test). The real runtime cannot read Prometheus's memory (S1 fix) | none |
| Atlas Map | **PASS** (real state only); visual review on the target PC MANUAL TEST REQUIRED | e2e "the Atlas Map renders nodes from live state"; map assertions in `sibling_bridge.rs` (Prometheus node only while paired) | Owner's visual check |
| Existing features | **PASS**. Voice input, spoken responses and OS notifications are **NOT IMPLEMENTED** | e2e 13/13, Vitest 19, Rust engine 23. Voice/notification audit in KNOWN_LIMITATIONS.md | Voice and notifications are master-roadmap Stage 2 and Stage 4 |
| Recovery and reliability | **PASS** for the loops run. A 24 h endurance run is **NOT IMPLEMENTED** | `repeated_pairing_consultations_and_cancellations_stay_stable`: 5 pair/unpair cycles, 25 consultations (avg 6 ms), 25 send+cancel, adapter RSS 25396→26464 kB, 1 thread | Endurance programme (master roadmap) |
| Remote readiness | **NOT IMPLEMENTED** (assessment only; no port opened) | REMOTE_CONNECTIVITY_PROPOSAL.md | Dedicated phase with a security review |

## 2. Release decision

**READY WITH LIMITATIONS.** Not published.

Why it qualifies:
* The critical workflows work.
* The one critical security defect (S1) is fixed and verified against the real Prometheus runtime.
* No finding above Info is open.
* The regression suites pass.

Why it is not READY:
* Live provider inference is unverified.
* Inference by Prometheus's own model is unverified.
* Nobody has looked at the release build on the target PC.

These three need the owner's keys or machine; §7 lists the steps.

What a release would contain:
* **Atlas 0.2.1:**
  * lost-contact pause;
  * shut-down-model routing guard;
  * Forge bytecode fix;
  * pricing availability shown in Settings.
* **Prometheus side:** the updated `sibling_adapter.py`, with the S1 and S7 fixes.
  * The adapter lives in the Prometheus repository, not in the Atlas installer.
  * Anyone running the 0.2.0 adapter should update it, whether or not Atlas is updated.

The release checklist is in §8. Nothing will be tagged or published without your go-ahead.

## 3. Baseline

### What the 0.2.0 report claimed vs what Phase 7 established

| Claim in 0.2.0 report | Phase 7 finding |
|---|---|
| Cross-language sibling test passed on 3 OSes | **Partly false:** on Windows the test silently skipped (S7). Linux and macOS ran it for real. Fixed; Windows now runs it. |
| Real Prometheus model execution not tested | Still true for the model. The rest of the real runtime is now tested (§4 C). |
| Live provider calls not verified | Still true, except the live invalid-key check (Anthropic). |
| Some OpenAI IDs and prices unverified | Audited. gpt-4.1-nano is shut down, gpt-5-nano and gpt-4.1 are deprecated, and gpt-5.4 and gpt-5.5 are not listed. Seeds are kept as historical. |
| Prometheus core untouched | **Confirmed:** `prometheus.py`, `gui_orb.py` and `safety.py` are byte-identical to tag `atlas-pre-evolution`. |

### Evidence level per capability

| Level | Capabilities |
|---|---|
| Implemented | Everything in the summary table except rows marked NOT IMPLEMENTED |
| Unit-tested | State machine, policy matrix, approvals binding, pricing/lifecycle, routing, path/symlink containment, command policy, HMAC envelope, migrations |
| Mock-tested (wiremock / scripted provider) | Provider wire formats, retries, timeouts, rate limits, engine tool loop, routing, budgets |
| Adapter-level integration (real adapter process, test backend) | Pairing, auth, replay, revocation, missions, cancellation, consultation approval, restart recovery, reliability loop, secret scan |
| Actual Prometheus runtime (model stubbed) | Capability discovery, consultation routing, real tool execution, dangerous-tool gate, workspace confinement, disconnect, restart without re-run, revocation |
| Real Windows VM | Install, launch, data, restart, uninstall, upgrade, credential store round-trip, e2e UI (WebDriver) |
| Live external service | Anthropic rejecting an invalid key |
| Manually verified by a person | None in this phase (no access to the owner's PC) |

### Test counts: historical vs now

| Suite | 0.2.0 report | Now | Why it differs |
|---|---|---|---|
| Atlas Rust | 67 passed, 1 ignored | 113 passed, 3 ignored | Phase 1–7 tests added (lib 83, engine 23, sibling bridge 6, shell 1). Two of the ignored tests were run explicitly and passed (`real_prometheus_runtime`, `live_invalid_keys…`). The third needs paid keys. |
| Atlas Vitest | 15 | 19 | Avatar tests added |
| E2E | 13 | 13 (Linux and Windows) | unchanged |
| Prometheus pytest | 363 | 409 passed, 36 skipped | Prometheus's Python dependencies are installed here, so more test modules import. Also 4 new adapter policy tests. No test was removed. |

## 4. Tests

Each entry gives the objective, method, type, result, evidence and limits.
* Unless stated otherwise, tests are automated.
* "Test backend" means the adapter's labelled deterministic backend.
* "Real runtime" means `import prometheus` with Prometheus's real tools and router.

### A. Clean installation
* **Objective:** the published 0.2.0 installer works on Windows without exposing credentials or destroying data.
* **Environment:** GitHub-hosted Windows Server 2025 VM. Installers downloaded from the release, checksums verified.
* **Method:** `.github/workflows/atlas-install-test.yml`. Real installer (NSIS, silent), real app launch.
* **Result:**

  | Step | Result |
  |---|---|
  | A1 fresh install, launch, database, relaunch | PASS (database v3, `quick_check ok`, 37 MB) |
  | A2 settings persist across restart | PASS |
  | A3 no credential-like strings in the data folder | PASS |
  | A4 uninstall keeps user data | PASS |
  | A5 upgrade 0.1.0→0.2.0 | PASS (marker row kept, `atlas.pre-v3.bak` written) |

  The OS credential store round-trip (Windows Credential Manager) passes in `atlas.yml` on Windows.
  The first-run onboarding passes in e2e on Windows.
* **Limits:**
  * This is a server SKU, not Windows 10/11 desktop.
  * Nobody looked at the screen: MANUAL TEST REQUIRED.
  * The installer is unsigned, so SmartScreen warns.

### B. Providers, routing, pricing
* **Objective:** each provider works independently of the sibling; routing sends what it announces;
  prices are honest.
* **Method:**
  * Unit and wiremock tests.
  * The real engine with a scripted provider.
  * A key-free live call per provider.
  * A pricing audit against vendor pages (2026-11-07).
* **Result:** see PROVIDER_VALIDATION.md for the 10×6 matrix.
  * Key storage, masking and removal: PASS.
  * Connection, discovery, unavailable model, timeouts and rate limits: tested against mocks only.
  * Small real inference: **BLOCKED** for all six providers (no keys; four hosts blocked; Ollama models not downloadable).
  * Invalid key: PASS live for Anthropic, BLOCKED for the others.
  * Routing modes, tiers, fallback reasons, availability guard, token accounting and budgets: PASS.
  * Estimated vs actual cost: Atlas shows estimates only, labelled as such.
* **Defects fixed:** S4, routing to shut-down models.

### C. Real Prometheus pairing
* **Test 1, adapter level (real adapter process, test backend):**
  * PASS for: pairing code, mutual proofs, wrong/reused code, 5-attempt lockout, wrong secret,
    stale timestamp, replayed nonce, tampered payload, missing protocol header, foreign Host, revocation,
    and cross-sibling isolation.
  * Python and Rust known-answer vectors match.
  * Evidence: `tests/test_sibling_adapter.py`, `core/tests/sibling_bridge.rs`.
* **Test 2, actual runtime:**
  * PASS for: independent start, discovery, capabilities equal to `prometheus.TOOLS` (32), health,
    disconnect detected, reconnect with the stored pairing, restart without re-execution, revocation
    while running.
  * Model inference was a scripted stand-in. Every reply is tagged `[scripted stand-in LLM]`.
  * Evidence: REAL_PROMETHEUS_INTEGRATION.md, `core/tests/real_prometheus_runtime.rs`.
* **Missing integration point:** a live model for Prometheus. The adapter calls Prometheus's real router,
  which is configured for Ollama on `localhost:11434` with no key.
* **Prometheus-side changes:** `sibling_adapter.py` only (S1, S7). `prometheus.py` is unchanged.

### D. Collaboration modes
* **Consultation:**
  * PASS:
    * the approval preview shows the exact question and context;
    * a rejection sends nothing and creates no mission;
    * only the approved text is sent;
    * Atlas's private memory reaches its own model but not Prometheus;
    * the reply is attributed and marked untrusted;
    * it is stored in the ledger.
  * The answer from Prometheus's own model: BLOCKED.
* **Collaborative engineering:**
  * PASS:
    * a mission is created in Collaborative mode;
    * it awaits approval;
    * it is sent once;
    * Prometheus runs real tools in its mission folder;
    * the result goes to REVIEWING;
    * the owner accepts or rejects it, and Atlas never auto-accepts.
  * NOT IMPLEMENTED:
    * a structured multi-task plan with task allocation;
    * transfer of Prometheus's file changes (manifest, hashes, patches), so Atlas cannot diff
      Prometheus's code changes itself.

    Atlas reviews Prometheus's reported result and events.
* **Delegated engineering:**
  * PASS on the real runtime:
    * file tools are confined to `sibling_missions/<id>/`;
    * traversal and absolute paths are refused;
    * memory, web and self-modification tools are neither offered nor run;
    * dangerous tools are refused without `--allow-dangerous`;
    * the private canary file never appears in any reply.
  * Cancellation and single delivery: PASS at adapter level.
  * Duplicate execution after restart: PASS on the real runtime.

### E. Mission ledger and recovery
* **States and transitions:** PASS.
  * All 10 states.
  * Terminal states are final.
  * Invalid transitions are refused in the backend: `state_machine_is_enforced_in_the_backend`.
* **Failure scenarios:**

  | # | Scenario | Result | Evidence |
  |---|---|---|---|
  | 1 | Prometheus disconnects | PASS (after fix S2) | real runtime → PAUSED/unreachable |
  | 2 | Atlas restarts | PASS | `atlas_restart_during_a_mission_resumes_without_resending` |
  | 3 | Prometheus restarts | PASS | real runtime → `interrupted`, PAUSED, no re-run |
  | 4 | Timeout | PASS for the step limit (8 steps → `stopped` → REVIEWING, never COMPLETED); wall-clock timeout NOT IMPLEMENTED | `ingest_is_idempotent_and_maps_remote_states` (mapping) |
  | 5 | Tool fails | PASS | refused tool returns `status: refused` and the mission continues; Forge failing tests are reported (debugger test) |
  | 6 | Approval rejected | PASS | consult test; e2e "declining an approval performs nothing" |
  | 7 | User cancels | PASS | `test_delegated_mission_refuses_dangerous_tools_and_can_be_cancelled`, reliability loop |
  | 8 | Unexpected result | PASS | `open_rejects_tampering_staleness_and_wrong_request`; unknown remote state → PAUSED |
  | 9 | Message received twice | PASS | nonce replay refused; idempotent create (`test_consultation_mission_and_idempotent_create`); idempotent ingest |

* **Partial vs full completion:** the ledger keeps them apart. `stopped` and `completed` both go to
  REVIEWING with the remote summary, and only the owner marks COMPLETED.

### F. Atlas Forge
* **Profiles (real engine, scripted model, real files and processes):**

  | Profile | Result | What was checked |
  |---|---|---|
  | Architect | PASS | reads, cannot edit |
  | Builder | PASS | creates and edits with an exact diff and approval; revert restores |
  | Debugger | PASS | reproduces the failing test, fixes it after approval, proves the fix |
  | Reconstructor | PASS | adds files; editing or overwriting existing files refused |

* **Security:** PASS. All of these are enforced in Rust:
  * path containment and traversal;
  * symlink escape;
  * command policy (no shells, no network clients);
  * tool allowlist per profile;
  * a tool not offered is refused;
  * environment scrubbing;
  * prompt-injection inertness.
* **Defect fixed:** S3, stale Python bytecode after an edit.
* **Limits:** answer quality with a real model needs live keys.

### G. Approvals and security
PASS. See SECURITY_AUDIT.md for the full table:
* approvals are bound to the tool plus a hash of the canonical arguments;
* changed arguments need a new approval;
* a used approval cannot be replayed;
* approvals expire;
* emergency stop cancels waiting approvals;
* destructive actions are always denied.

The secret scan covers the database, WAL, export, backup and diagnostics.

### H. Memory isolation
PASS:
* private memory never enters a mission payload;
* Forge sessions are scoped to their project;
* there is no cross-mission context;
* unpairing stops sharing;
* sharing is auditable per mission;
* Prometheus's own memory is not reachable by sibling missions (S1 fix).

### I. Atlas Map and visual identity
* **Map:** PASS.
  * Nodes come from live state.
  * The Prometheus node appears only when paired and changes state when disconnected (asserted in
    `sibling_bridge.rs`).
  * No decorative events.
* **Avatar:** PASS in Vitest.
  * GLSL validity.
  * State mapping matches Prometheus's `SolarSunWidget`.
  * Static fallback without WebGL2.
  * Never shows "connected" when offline.
* **Reduced motion:** implemented in CSS and in the avatar. No automated test: MANUAL TEST REQUIRED.
* **Identity on the target PC:** MANUAL TEST REQUIRED.

### J. Existing features
* PASS: e2e 13/13 on Linux and Windows. The suite covers:
  * onboarding;
  * tools with and without approval;
  * stop;
  * Mission Control;
  * Map;
  * memory;
  * integrations and settings persistence;
  * Forge;
  * Siblings;
  * home;
  * an axe-core accessibility audit.
* PASS in the engine: diagnostics, backup and restore.
* NOT IMPLEMENTED:
  * voice input;
  * spoken responses (only a "test voice" button exists);
  * OS notifications (Atlas shows in-app notices only).

### K. Reliability
* PASS: the reliability loop measured (Linux):
  * 5 pair/unpair cycles;
  * 25 consultations, average 6 ms;
  * 25 send-and-cancel;
  * nothing left RUNNING;
  * 0 active missions on the sibling afterwards;
  * adapter RSS 25396→26464 kB;
  * 1 adapter thread.
* Other checks:
  * restart recovery;
  * lost-contact pause;
  * the Windows VM relaunch.
* NOT IMPLEMENTED: a 24 h endurance run and 50-restart cycles.

### L. Remote readiness
* NOT IMPLEMENTED by design. No listener or port was opened.
* The proposal is in REMOTE_CONNECTIVITY_PROPOSAL.md.

## 5. Defects found and fixed in Phase 7

| # | Severity | Defect | Commit |
|---|---|---|---|
| S1 | Critical | Sibling missions could read and change Prometheus's private files and memory | `85f126d` |
| S2 | High | Missions stayed RUNNING after the sibling vanished | `85f126d` |
| S3 | High | Forge test results could be stale after an edit (bytecode cache) | `3a75816` |
| S4 | Medium | Routing could pick a shut-down model | `3a75816` |
| S7 | Medium | Windows: adapter crashed with redirected output, and the cross-language tests silently skipped on Windows CI | this phase's final commit |

Each fix has a regression test, listed in PHASE_7_CHANGELOG.md.

## 6. Final regression (local, current code)

| Suite | Result |
|---|---|
| Rust lib | 83 passed, 1 ignored |
| Rust engine | 23 passed |
| Rust sibling bridge (Windows code page reproduced) | 6 passed |
| Rust desktop shell | 1 passed |
| `real_prometheus_runtime` (ignored, run explicitly) | 1 passed |
| `live_invalid_keys…` (ignored, run explicitly) | 1 passed |
| Clippy (`--all-targets -D warnings`) | clean |
| Vitest | 19 passed |
| Typecheck, lint | clean |
| E2E (Linux) | 13/13 |
| Prometheus pytest (full) | 409 passed, 36 skipped |
| Adapter tests | 16 passed |

**CI:**
* Run 15 (commit `3a75816`): green on Linux and macOS. **Failed on Windows** in `sibling_bridge`. That
  failure exposed S7.
* Run 16 (run id 42373736417, commit `0429366`): **all 5 jobs green.**
  * build on ubuntu-24.04, windows-latest and macos-latest;
  * e2e on ubuntu-24.04 and windows-latest.
* What run 16 shows:
  * Windows `sibling_bridge`: 6 passed in 4.6 s with no adapter traceback, so these are real runs, not
    skips.
  * Windows Rust lib: 81 passed, 1 ignored. Linux has 83; the two extra tests are Unix-only.
  * Windows Credential Manager round-trip: passed.
  * Linux "Atlas with the real Prometheus runtime": passed.
  * Installers built on all three OSes.

## 7. Manual steps for the owner

1. **Live providers:** run this with your keys exported (each call costs a fraction of a cent):
   ```bash
   cd atlas && cargo test -p atlas-core --test live_providers -- --ignored --nocapture
   ```
   Or, in the app: Integrations → add a key → Test connection → send one short message.
2. **Prometheus with its own model:**
   * Start Ollama with `llama3.2`, or set one of Prometheus's provider keys.
   * Run `python sibling_adapter.py --pair` and pair from Atlas → Siblings.
   * Ask one consultation, then create a Delegated mission ("use engineering_calc for a 400 km circular orbit").
   * Check that the reply is not tagged `[scripted stand-in LLM]`.
3. **Target PC review:**
   * Install the build and walk through Home, Chat, Mission Control, Map, Siblings and Forge.
   * Switch off "Animation effects" in Windows Settings → Accessibility → Visual effects (reduced motion) and confirm that the globe and the avatar stop animating.
4. **Prometheus side:** pull the updated `sibling_adapter.py` (S1 and S7 fixes) before pairing again.

## 8. Release checklist (prepared, not executed)

- [ ] Owner completes §7 steps 1–3 and reports results
- [ ] Bump `atlas/package.json`, `src-tauri/tauri.conf.json` and `Cargo.toml` to 0.2.1; update CHANGELOG.md from PHASE_7_CHANGELOG.md
- [ ] CI green on all OSes for the release commit
- [ ] Run `atlas-release.yml` (workflow_dispatch) → draft release with the installer and checksums
- [ ] Run `atlas-install-test.yml` against the draft's installers
- [ ] Update INSTALL.md size and checksum
- [ ] Owner authorizes publishing
