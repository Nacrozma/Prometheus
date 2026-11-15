# Current state

**Updated:** 2026-11-14 · **Branch:** `claude/prometheus-ai-evaluation-pxqzfr` · **Released:** 0.4.2

**Working on:** 0.5.0, Stage 7 (specialists, personality) is next. Plan: `PLAN_0.5-0.7.md`.

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
| 6 Memory quality, Trust Center | Done (tests + e2e + screenshots; `STAGE6_TEST_REPORT.md`, `docs/MEMORY.md`, `docs/TRUST_CENTER.md`) |
| 7 Specialists, personality | Not started |

## Next
Stage 7, the last 0.5.0 stage: personality depth and specialist agents (`PLAN_0.5-0.7.md` §4:
"Personality depth ✔" for 0.5.0; "Specialist agents: design + role registry" for 0.5.0, full
orchestration in 0.6.0; `ATLAS_0.5_AUDIT.md`: initiative and follow-up behaviour, voice delivery, custom
instructions stay private; specialists as bounded roles inside the existing engine with budgets and
approvals). Any new schema is v9, additive, with an upgrade test from v8 holding data (memory history and
structured activity records included). Specialists must use the same dispatcher, permissions,
revalidation and activity record as everything else, and appear in the Trust Center. Every feature gets a
screenshot and a WHATS_NEW entry. Do not publish 0.5.0 until the owner says so.

Carried over (limitations, not blockers): no OCR, no semantic search (Vault and memory are keyword
based); the Trust Center reads the activity record, so actions taken before schema 8 have only their
original kind and level; the "withheld under local-only" path and cloud-provider attribution are tested in
the core, not end-to-end (the e2e model is local); Mobbin was unavailable (paid plan).
