# Current state

**Updated:** 2026-11-14 · **Branch:** `claude/prometheus-ai-evaluation-pxqzfr` · **Released:** 0.4.2

**Working on:** 0.5.0, Stage 5 (Knowledge Vault) is next. Plan: `PLAN_0.5-0.7.md`.

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
| 5 Knowledge Vault | Not started |
| 6 Memory quality, Trust Center | Not started |
| 7 Specialists, personality | Not started |

## Next
Stage 5: Knowledge Vault (`PLAN_0.5-0.7.md` §4, §6, §7; `ATLAS_0.5_AUDIT.md`). Scope for 0.5.0:
import TXT, Markdown, PDF and DOCX into a local vault; full-text search; passages retrieved into a
turn with citations (file, page or heading). Spreadsheets (XLSX, CSV) are 0.6.0, not this stage.
Migration v7 = Knowledge Vault, additive, with an upgrade test from v6 holding data (Focus sessions and
held notifications included). Rules from the plan: imported text is untrusted data, stored and
retrieved as quoted material with a fixed warning, never executed; size and page limits; passages go to
a cloud model only inside a turn the owner started, with a local-only setting; queries are scoped by
project, with a cross-project retrieval test. Every feature gets a screenshot and a WHATS_NEW entry.
Start by checking which PDF and DOCX parsers are already in the dependency tree before adding any.

Carried over (not blockers): run the full e2e suite on Windows CI for Stage 4 (it runs on push);
Mobbin was unavailable for design research (paid plan).
