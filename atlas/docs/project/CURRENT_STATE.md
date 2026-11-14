# Current state

**Updated:** 2026-11-12 · **Branch:** `claude/prometheus-ai-evaluation-pxqzfr` · **Released:** 0.4.2

**Working on:** 0.5.0, Stage 4 (Focus Mode, session recap). Plan: `PLAN_0.5-0.7.md`.

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
| 4 Focus Mode, recap | In progress |
| 5 Knowledge Vault | Not started |
| 6 Memory quality, Trust Center | Not started |
| 7 Specialists, personality | Not started |

## Next
Stage 4: Focus Mode (a timed session, optionally on one task; holds non-urgent notifications and shows
them when it ends; approvals, failures and safety notices always pass through; respects the global
pause) and the session recap ("while you were away": reminders delivered or missed, replies and
missions that finished, tasks completed, approvals waiting, built from recorded events since the last
session; nothing resumes without the owner's approval). Migration v6 = focus sessions + recap marker.
