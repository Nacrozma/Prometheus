# Security audit (Phase 7, Tests G, H, F-security)

Date: 2026-11-07. Every entry names the test that checks it. Enforcement is in the Rust core or the Python
adapter, never only in the UI.

## Findings

| # | Severity | Finding | Status |
|---|---|---|---|
| S1 | **Critical** | Delegated sibling missions could make the real Prometheus runtime read its owner's private files and memory, and call memory/schedule/web/self-modification tools, then return the results to Atlas. | **Fixed** (adapter allowlist + per-mission workspace). Verified against the real runtime; see REAL_PROMETHEUS_INTEGRATION.md |
| S2 | High (integrity) | A sibling that became unreachable left its mission marked RUNNING indefinitely. | **Fixed**: auto-pause with reason, read-only reconcile on reconnect |
| S3 | High (integrity) | Forge test results could be stale right after an edit (Python bytecode cache), so a fix could look broken or a regression could look fixed. | **Fixed**: `PYTHONDONTWRITEBYTECODE=1` for Forge commands |
| S4 | Medium | Atlas could route to a model its vendor has shut down. | **Fixed**: lifecycle data plus routing guard |
| S5 | Info | The adapter's in-memory registry does not reload when the owner runs `--revoke` in another process. | **Not exploitable**: secret lookup reads the store on each request, so the revoked sibling is refused immediately (verified live). Documented. |
| S7 | Medium (reliability, test integrity) | On Windows the adapter wrote its console output in the ANSI code page (cp1252) when its output went to a pipe or file. The pairing hint contains `→`, which cp1252 cannot encode, so `--pair` with redirected output crashed at startup. In CI, the cross-language test harness then saw non-UTF-8 output and **silently skipped** the sibling tests on Windows: earlier Windows "ok" results for those tests were skips, not passes. | **Fixed**: the adapter writes UTF-8 to pipes and files (interactive consoles unchanged) and never fails on console output. The harness now fails instead of skipping, requires Python in CI, and reproduces the Windows code page on every OS (`PYTHONIOENCODING=cp1252`). |
| S6 | Info | With `--allow-dangerous`, a mission's `execute_shell` runs in Prometheus's folder, not the mission workspace (Prometheus's shell tool has no cwd parameter). | Documented. The owner still confirms every command in Prometheus's terminal. |

## Approvals

| Check | Result | Test |
|---|---|---|
| Approval before file modification (Forge edit/write) | PASS | `forge_builder_edit_requires_approval_and_can_be_reverted` |
| Approval shows the real diff against the current file | PASS | same, and e2e "Atlas Forge" |
| Approval before command execution | PASS | `forge_model_commands_are_policed_before_approval` |
| Approval before commits | PASS | `GitCommit` is consequential (always asks); `policy::matrix` |
| Destructive class always denied | PASS | `destructive_tools_are_denied_and_never_offered` |
| Approval before sharing with Prometheus | PASS | `consulting_prometheus_needs_approval_and_shares_only_the_approved_text` |
| Rejection respected (nothing sent / nothing changed) | PASS | same; `rejected_action_is_not_performed`; e2e "declining an approval performs nothing" |
| Approval bound to exact tool + arguments; changed arguments need a new approval | PASS | `consequential_action_requires_action_specific_single_use_approval` (hash of tool id + canonical args; changed args refused) |
| Replay of a used approval refused | PASS | same ("already used") |
| Expiry / cancellation of a waiting approval | PASS | `emergency_stop_cancels_waiting_approval`; approvals expire after `approval_timeout_secs` |
| Duplicate tool calls / tools not offered | PASS | a tool the model names but was not offered is refused before dispatch |
| Cancellation during an operation | PASS | `a running response can be stopped` (e2e); Forge commands kill the process tree |

## Secrets

| Check | Result | Test |
|---|---|---|
| Provider keys only in the OS credential store | PASS | `key_lifecycle_never_stores_secret_in_db`; Windows Credential Manager round-trip in CI |
| No key or sibling secret in database, WAL, export, backup or diagnostics | PASS | `secrets_never_reach_the_database_exports_or_backups` |
| No credential-like strings in the installed app's data folder (real Windows) | PASS | install test A3 |
| Keys never echoed in error messages | PASS | `live_invalid_keys_are_rejected_and_classified` (live Anthropic) |
| Credential-like env vars not passed to Forge commands | PASS | `runs_times_out_and_scrubs_env` |
| No keys in prompts / sibling messages | PASS | `credentials_never_reach_the_model_or_exports`;  mission payload is objective + typed context only (`outgoing_payload`); consult test checks no memory is included |

## Untrusted content

* File contents, command output and sibling replies are labelled untrusted for the model.
  Tests: `forge_architect_reads_but_cannot_edit`, `forge_debugger_reproduces_fixes_with_approval_and_proves_the_fix`.
* A project file containing an injected instruction (`curl … | sh`) stays inert.
* Even if a model obeyed it, the command policy (shells, network clients) and the approval gate stop it.
* Sibling messages cannot trigger Atlas tools. They are stored as ledger events, and only the owner acts on
  them.

## Sibling protocol

All verified against the real adapter process. Tests: `tests/test_sibling_adapter.py`,
`core/tests/sibling_bridge.rs`, `core/tests/real_prometheus_runtime.rs`. Each of these is refused:

* a wrong pairing code;
* a reused code;
* 5 wrong attempts (the code is invalidated);
* a wrong secret;
* a stale timestamp;
* a replayed nonce;
* a tampered payload;
* a missing protocol header (browser-style request);
* a foreign Host header (DNS rebinding);
* a revoked sibling;
* another sibling's mission (reported as `unknown`).

Known-answer vectors match between Python and Rust.

## Memory isolation (Test H)

* Atlas's private memory reaches Atlas's own model, but never a mission payload or Prometheus.
  Test: `consulting_prometheus_needs_approval_and_shares_only_the_approved_text`.
* Forge sessions are scoped to their project folder and kept out of normal conversation lists.
* Mission context is the mission's own objective and context; there is no cross-mission sharing.
* Unpairing deletes the secret, and further sends are refused. Test: `pairing_discovery_missions_and_revocation…`.
* What was shared is auditable per mission ("What is shared" view; the ledger stores the outgoing payload).
* Prometheus-side: sibling missions can no longer read or write Prometheus's own memory (S1).
