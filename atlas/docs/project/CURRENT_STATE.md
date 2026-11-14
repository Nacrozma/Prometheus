# Current state

**Updated:** 2026-11-14 · **Branch:** `claude/prometheus-ai-evaluation-pxqzfr` · **Released:** 0.4.2

**Working on:** 0.5.0, Stage 6 (memory quality, Trust Center) is next. Plan: `PLAN_0.5-0.7.md`.

## Standing rules from the owner
* Every new feature gets a screenshot in `docs/screenshots/` and `docs/WHATS_NEW_SCREENSHOTS.md`.
* Do not publish a release until the owner says so. Pushing commits to the branch is fine.
* Do not change voice recognition defaults or tune latency without a Voice check report.
* Atlas and Prometheus stay separate projects; `prometheus.py` is not modified.
* The welcome line never uses the owner's name. The dedication is exactly "Created with love."

## Stage status (0.5.0)
| Stage | Status |
|---|---|
| 1 Tasks | Done (tests + e2e + screenshots) |
| 2 Scheduler, reminders | Done (tests + e2e + screenshots) |
| 3 Command Center, briefing | Done (tests + e2e + screenshots) |
| 4 Focus Mode, recap | Done (tests + e2e incl. restart + screenshots; `STAGE4_TEST_REPORT.md`) |
| 5 Knowledge Vault | Done (tests + e2e + screenshots; `STAGE5_TEST_REPORT.md`, `docs/KNOWLEDGE_VAULT.md`) |
| 6 Memory quality, Trust Center | Not started |
| 7 Specialists, personality | Not started |

## Next
Stage 6: memory quality and the Trust Center (`PLAN_0.5-0.7.md`; `ATLAS_0.5_AUDIT.md`). Migration v8 =
memory quality, additive, with an upgrade test from v7 holding data (Vault documents and sources
included). The Trust Center should present what is already recorded in the activity log, including the
Knowledge Vault's `vault.import`, `vault.indexed`, `vault.failed`, `vault.reindex`, `vault.move`,
`vault.remove` and `vault.passages` (with whether passages were sent and whether the model was local),
plus file access, approvals and the global pause. Every feature gets a screenshot and a WHATS_NEW entry.

Carried over from stage 5 (limitations, not blockers; see `docs/KNOWLEDGE_VAULT.md` §10): no OCR, no
semantic search, protected PDFs with a password cannot be opened, the reader shows extracted text only.
The "held back under local-only" path is covered by unit and core tests, not end-to-end (the e2e model
runs locally). Mobbin was unavailable for design research (paid plan).
