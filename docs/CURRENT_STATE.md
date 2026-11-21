# Prometheus: current state

**Updated:** 2026-11-21 · **Branch:** `claude/prometheus-ai-evaluation-pxqzfr` · **Desktop version:** 2.6.0
(published under the owner's standing release authorisation once every Windows check passes) · Atlas (`atlas/`) is a separate product with its own state file (ATLAS 0.7.0 published 2026-11-21).

Prometheus 2.0 "Renaissance" is implemented and tested on Linux, through three passes: the Renaissance
(design system, shell, new capabilities), the experience-first redesign (a distinct environment per
screen, toasts, activity centre) and the Second Birth (the birth-of-the-sun launch, distinct avatar
states, approval cards with real diffs, memory map, grouped search, secure-storage explanation). Windows
CI builds, installs and runs the tests on every push. **Released 2026-11-17 with the owner's approval as
[prometheus-desktop-v2.0.0](https://github.com/Nacrozma/Prometheus/releases/tag/prometheus-desktop-v2.0.0)** (unsigned installer).

**2.6.0 (2026-11-21):** the engineering laboratory (`eng/`, Engineering → Engineering lab, `engineering_lab` tool):
stiffness-method structures, machine design, design optimisation, 1976 atmosphere to 86 km, compressible flow, nozzles,
RK4 3-DOF trajectories, control sandbox, arm dynamics, uncertainty, experiment records, reports. Arm firmware boots
disarmed with an optional hardware e-stop loop; bench HIL harness; bring-up procedure. **No hardware test has been
done**: see `VALIDATION.md` (status of every model) and `ENGINEERING_JOURNAL.md`. [Published](https://github.com/Nacrozma/Prometheus/releases/tag/prometheus-desktop-v2.6.0) (commit `c140050`); installer SHA-256 `6e18bc6e6fbba8b86e646c684e321e60f397005b9563bf81ade668cce36ea45d`.

**2.5.0 (2026-11-20):** ORBIT closer to the owner's reference image — particle-torus core with a geodesic shell, curved connections, chamfered panels with real actions (Compare ideas, + Add, Edit brief), full-screen heads-up layer in immersive mode; see `RELEASE_NOTES_2.5.0.md`. [Published](https://github.com/Nacrozma/Prometheus/releases/tag/prometheus-desktop-v2.5.0) (run 20); installer SHA-256 `79446b8b976842861d46cc833305b49108c10e5b2fedfdc3220f5625cddb6dd5`.

**2.4.0 (2026-11-20, [published](https://github.com/Nacrozma/Prometheus/releases/tag/prometheus-desktop-v2.4.0), SHA-256 `c30f115c3e5cd5f82403da4c590e7ac9a5c0533524f276fa7837c2691ed80b5f`):** the ORBIT universe (layered solar core, holographic panels, project journey, four environments); see `ORBIT_UNIVERSE_REPORT.md`.

**2.3.0 (2026-11-19):** [spoken replies with a local voice](https://github.com/Nacrozma/Prometheus/releases/tag/prometheus-desktop-v2.3.0), one shared speech service; see `VOICE_EXPERIENCE_REPORT.md`.

**Releases 2026-11-19 (owner-approved):** [2.1.0](https://github.com/Nacrozma/Prometheus/releases/tag/prometheus-desktop-v2.1.0) (ORBIT) and
[2.2.0](https://github.com/Nacrozma/Prometheus/releases/tag/prometheus-desktop-v2.2.0) (voice input set up in Settings → Voice: whisper.cpp + model,
SHA-256 verified; `app/services/local_stt.py`, `app/ui/voice_setup.py`). 2.2.0 installer SHA-256
`1f1f1c757d41b121e9a5917daf3780fe1d51977b7effe05d12f07b5dc705c5c3`. Speech output is still online edge-tts.

**ORBIT:** a voice-first planning space — talk with Prometheus, the plan forms as
orbits around the sun, versioned plans you edit by voice or by hand, approval, workflows mapped to real
capabilities under per-mission autonomy and the existing approval gates, restart recovery that never re-runs a step.
Code: `app/services/orbit.py`, `orbit_voice.py`, `app/ui/pages/orbit.py`. Docs: `ORBIT_*.md`. Atlas received its
own independent ORBIT in `atlas/` (authorised by the ORBIT directive).

Waiting for the owner: the first test on a physical Windows PC; decisions on new providers (paid
services) and code signing.

Read next: `ORBIT_RELEASE_READINESS.md`, `ORBIT_ARCHITECTURE_AUDIT.md`, `../CLAUDE.md` (the permanent project constitution), `SESSION_HANDOVER.md`,
`RENAISSANCE_SECOND_BIRTH_AUDIT.md`, `RENAISSANCE_PRODUCT_EXPERIENCE.md`, `RENAISSANCE_PAGE_SPECIFICATIONS.md`,
`RENAISSANCE_TEST_REPORT.md`, `RENAISSANCE_FEATURES.md`.
