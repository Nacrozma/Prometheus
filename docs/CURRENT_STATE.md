# Prometheus: current state

**Updated:** 2026-11-19 · **Branch:** `claude/prometheus-ai-evaluation-pxqzfr` · **Desktop version:** 2.0.0
(released; ORBIT is on the branch, not released) · Atlas (`atlas/`) is a separate product with its own state file.

Prometheus 2.0 "Renaissance" is implemented and tested on Linux, through three passes: the Renaissance
(design system, shell, new capabilities), the experience-first redesign (a distinct environment per
screen, toasts, activity centre) and the Second Birth (the birth-of-the-sun launch, distinct avatar
states, approval cards with real diffs, memory map, grouped search, secure-storage explanation). Windows
CI builds, installs and runs the tests on every push. **Released 2026-11-17 with the owner's approval as
[prometheus-desktop-v2.0.0](https://github.com/Nacrozma/Prometheus/releases/tag/prometheus-desktop-v2.0.0)** (unsigned installer).

**ORBIT (2026-11-19, not released):** a voice-first planning space — talk with Prometheus, the plan forms as
orbits around the sun, versioned plans you edit by voice or by hand, approval, workflows mapped to real
capabilities under per-mission autonomy and the existing approval gates, restart recovery that never re-runs a step.
Code: `app/services/orbit.py`, `orbit_voice.py`, `app/ui/pages/orbit.py`. Docs: `ORBIT_*.md`. Atlas received its
own independent ORBIT in `atlas/` (authorised by the ORBIT directive).

Waiting for the owner: the first test on a physical Windows PC; decisions on new providers (paid
services) and code signing.

Read next: `ORBIT_RELEASE_READINESS.md`, `ORBIT_ARCHITECTURE_AUDIT.md`, `../CLAUDE.md` (the permanent project constitution), `SESSION_HANDOVER.md`,
`RENAISSANCE_SECOND_BIRTH_AUDIT.md`, `RENAISSANCE_PRODUCT_EXPERIENCE.md`, `RENAISSANCE_PAGE_SPECIFICATIONS.md`,
`RENAISSANCE_TEST_REPORT.md`, `RENAISSANCE_FEATURES.md`.
