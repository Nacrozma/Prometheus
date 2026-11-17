# Session handover (Prometheus)

## Run and test
* Run: `pip install -r requirements.txt` then `python -m app` (set `PROMETHEUS_HOME`/`PROMETHEUS_WORKSPACE`
  to throwaway folders when testing).
* Tests: `python -m pytest tests -q` (485 pass, 2 skipped by design). Window smoke test is in `tests/test_desktop_app.py`.
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

## Next action
Windows CI run 12 (commit 4fe3a1d, all Second Birth code) passed: tests, build, install, upgrade,
uninstall, packaged self-test. Next: the owner's check on a real Windows PC.

## Needs the owner
1. Try it on a real Windows PC (CI artifact) — the release gate in `desktop-evolution/RELEASE_CHECKLIST.md`.
2. Decide on new providers (Anthropic, Mistral; OpenAI was removed on purpose) — paid services need approval.
3. Release and code signing decisions. Nothing is published.

## Suggested next work
Document import (PDF/DOCX/XLSX) feeding memory and search; diff view for edit approvals; persisted
notifications; global shortcut on Windows; workflow automation designed as its own reviewed engine.
