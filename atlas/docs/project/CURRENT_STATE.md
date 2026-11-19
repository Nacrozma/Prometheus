# Current state

**Updated:** 2026-11-19 · **Branch:** `claude/prometheus-ai-evaluation-pxqzfr` · **Released:** 0.5.0 ([atlas-v0.5.0](https://github.com/Nacrozma/Prometheus/releases/tag/atlas-v0.5.0))

**ORBIT (2026-11-19, not released):** Atlas's own voice-first planning space (`core/src/orbit.rs`, schema 10 `orbit_sessions`, `orbit_*` commands, `src/features/orbit/`). Rules live in the core; tool approvals stay in the dock. Tests pass (Rust, vitest). Not yet seen in the built app and **no screenshot yet** (owner rule: add one to `docs/screenshots/` before release). Specs: `../../../docs/ORBIT_*.md`.

**Working on:** 0.5.0 is complete (all 7 stages) and awaits the owner's release decision. Not released. Plan: `PLAN_0.5-0.7.md`.

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
| 7 Specialists, personality | Done (tests + e2e incl. restart + screenshots; `STAGE7_TEST_REPORT.md`, `docs/SPECIALISTS.md`) |

## Next
0.5.0 is feature-complete. Waiting for the owner: review, then a decision on publishing 0.5.0 (version
bump, installers, release notes). Nothing is published until the owner says so. After that, 0.6.0 per
`PLAN_0.5-0.7.md` (richer specialist orchestration: parallel steps, more teams).

Carried over (limitations, not blockers): no OCR, no semantic search (Vault and memory are keyword
based); the Trust Center reads the activity record, so actions taken before schema 8 have only their
original kind and level; the "withheld under local-only" path and cloud-provider attribution are tested in
the core, not end-to-end (the e2e model is local); Mobbin was unavailable (paid plan); specialist teams are sequential only, and real model quality for
specialists is not validated by the e2e suite (scripted model).
