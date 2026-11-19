# Session handover (Prometheus)

## Run and test
* Run: `pip install -r requirements.txt` then `python -m app` (set `PROMETHEUS_HOME`/`PROMETHEUS_WORKSPACE`
  to throwaway folders when testing).
* Tests: `python -m pytest tests -q` (498 pass, 2 skipped by design). Window smoke test is in `tests/test_desktop_app.py`.
* Screenshots: `xvfb-run -s "-screen 0 1600x1000x24" python tools/renaissance_screens.py docs/screenshots/renaissance [names]`.

## Done (Renaissance)
Design system, shell, Home, search, conversations, solar avatar, memory controls, Forge disciplines,
workspace, engineering, tasks, reflection, trust, provider tests, export, onboarding, docs, 24 screenshots.

## Done (experience-first pass)
UX audit; per-screen experiences (Home welcome, immersive Companion, Memory library + inspector + review,
Engineering workbench + project intelligence, Forge mission studio, Workspace explorer, Planner, Obsidian
reader, Robot arm lab, Reflection insights with charts, Trust oversight timeline, Settings rail); toasts;
activity centre; intent-based navigation; 31 screenshots at three sizes; UX specs, interaction guide,
visual QA.

## Done (Second Birth)
Launch sequence (`app/ui/launch.py`, reusing `gui_birth.py`), avatar signs per state (`app/ui/avatar_overlay.py`,
PAUSED for approvals), approval cards (`app/services/approval.py`), memory map (`app/ui/memory_map.py`,
`memory_ops.graph`), grouped search, mission diffs, secure-storage explanation (`credentials.explain_unavailable`),
~ paths, arm technical output, engineering copy; 40 screenshots; docs: SECOND_BIRTH_AUDIT, PRODUCT_EXPERIENCE,
PAGE_SPECIFICATIONS (renamed from UX_SPECIFICATIONS), MOTION_SYSTEM, LAUNCH_ANIMATION, AVATAR_SYSTEM,
ACCESSIBILITY, and updates to DESIGN_SYSTEM, VISUAL_QA, TEST_REPORT.

## Done (ORBIT, 2026-11-19)
Commits `5030ec1` (Prometheus ORBIT) and `5576fd7` (Atlas ORBIT, `atlas/` only), pushed; docs commit follows.
Prometheus: `app/services/orbit.py` (plans, versions, edits, workflow state machine, recovery, JSON store
`<data>/orbit/`), `app/services/orbit_voice.py` (turn-taking), `app/ui/pages/orbit.py` (stage, outline, transcript,
voice, workflow controls, versions), PLANNING/EXECUTING avatar states, nav + Ctrl+Shift+O / Ctrl+Shift+Space +
immersive + palette + `/orbit`, settings `orbit_*`, Companion Esc scoped to the Companion. Tests:
`tests/test_orbit.py` + smoke checks; screenshots `tools/orbit_screens.py` → `docs/screenshots/orbit/`.
Atlas: `core/src/orbit.rs` (rules in the core), schema 10, engine `orbit_session` context, 7 Tauri commands,
`src/features/orbit/*`, route/rail/immersive; Rust + vitest tests pass. Atlas page not visually checked.

## Next action (ORBIT)
1. Check the Windows workflow for the ORBIT commits and the Atlas workflow (run 80 was queued at hand-off).
2. Try ORBIT with a real provider and voice; look at the Atlas ORBIT page in the built app.
3. Then: versions as diffs / saves off the UI thread; Atlas specialist/Forge step operations; ORBIT buttons on
   Prometheus Workspace and Forge pages.

## Next action (before ORBIT)
Windows CI run 12 (commit 4fe3a1d, all Second Birth code) passed: tests, build, install, upgrade,
uninstall, packaged self-test. Released as prometheus-desktop-v2.0.0 (run 13, SHA-256 2a5a7756…faadd).
Next: act on the owner's report from their Windows PC.

## Needs the owner
1. Try it on a real Windows PC (CI artifact) — the release gate in `desktop-evolution/RELEASE_CHECKLIST.md`.
2. Decide on new providers (Anthropic, Mistral; OpenAI was removed on purpose) — paid services need approval.
3. Code signing decision. 2.0.0 is published (unsigned).

## Suggested next work
Document import (PDF/DOCX/XLSX) feeding memory and search; diff view for edit approvals; persisted
notifications; global shortcut on Windows; workflow automation designed as its own reviewed engine.
