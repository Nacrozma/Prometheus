# Phase 7 changelog (unreleased, after 0.2.0)

## Security and integrity fixes

* **Critical:** sibling missions can no longer read or change Prometheus's private data.
  * Delegated missions now use an explicit tool allowlist.
  * File tools are confined to `sibling_missions/<mission_id>/` (seeded with `atlas_context.md`).
  * Disallowed tools are neither offered nor executed.
  * Capabilities report the real policy.
  * The change is adapter-only (`sibling_adapter.py`); `prometheus.py` is unchanged.
* **Lost contact:** a mission whose sibling becomes unreachable is paused with a reason instead of staying
  "running". When the sibling is reachable again, Atlas checks status read-only and never re-sends.
* **Forge test results** are no longer at risk of being stale right after an edit
  (`PYTHONDONTWRITEBYTECODE=1`).
* **Routing** never sends to a model its vendor has shut down, and explains the skip.
* **Windows adapter output:** the adapter writes UTF-8 when its output goes to a pipe or file. Before,
  `--pair` crashed on Windows if output was redirected, because the code page could not encode `→`.

## Pricing

* Audited against vendor pages on 2026-11-07.
* Added verified current OpenAI rates, with source and date.
* The historical seed rates are kept exactly as supplied.
* Each model records its availability (current, deprecated, unavailable or unknown), shown in Settings →
  Usage & budgets.

## Tests added

| Test | What it checks |
|---|---|
| `atlas/core/tests/real_prometheus_runtime.rs` | Real Prometheus runtime; scripted model stand-in |
| `.github/workflows/atlas-install-test.yml` | Published installers on a Windows VM: install, launch, data, restart, uninstall, upgrade |
| `live_invalid_keys_are_rejected_and_classified` | Live provider endpoints, key-free |
| `routing_modes_send_the_tier_model_they_announce` | The routed model is the model the provider receives |
| `shut_down_models_are_never_routed_to` | Routing skips shut-down models |
| `audit_classification_as_of_2026_11_07` | Pricing audit classification |
| `forge_debugger_reproduces_fixes_with_approval_and_proves_the_fix` | Debugger profile |
| `forge_reconstructor_adds_files_but_cannot_edit_or_overwrite` | Reconstructor profile |
| `atlas_restart_during_a_mission_resumes_without_resending` | Restart recovery |
| `consulting_prometheus_needs_approval_and_shares_only_the_approved_text` | Consultation approval and data sharing |
| `repeated_pairing_consultations_and_cancellations_stay_stable` | Reliability loop |
| `secrets_never_reach_the_database_exports_or_backups` | Secret scan |
| `lost_contact_pauses_instead_of_claiming_running` | Ledger behaviour on lost contact |
| `SiblingToolPolicyTests` (4, Python) | Sibling tool policy |
| `sibling_bridge.rs` harness (all 6 tests) | Now runs under the Windows code page on every OS, and fails instead of skipping |

## CI

* Linux CI now runs the real-Prometheus-runtime test.
* The adapter tests and the cross-language tests run on Linux, Windows and macOS.
* **Correction:** before this phase, the cross-language tests silently skipped on Windows CI (finding S7).
  They now run there, and a missing interpreter or a failed adapter start fails the job.
* `cargo clippy --all-targets -D warnings` is clean. Clippy is not part of CI.

## Not released

No new installer has been published. The release decision is in ACCEPTANCE_TEST_REPORT.md.
