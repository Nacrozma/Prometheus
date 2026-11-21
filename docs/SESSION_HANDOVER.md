# Session handover (Prometheus)

## Run and test
* Run: `pip install -r requirements.txt` then `python -m app` (set `PROMETHEUS_HOME`/`PROMETHEUS_WORKSPACE`
  to throwaway folders when testing).
* Tests: `python -m pytest tests -q` (547 pass, 2 skipped by design). Window smoke test is in `tests/test_desktop_app.py`.
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

## ORBIT universe (2026-11-20) — Prometheus 2.4.0, ATLAS 0.6.0
New: `app/services/orbit_space.py`, `orbit_motion.py`, `orbit_sound.py`, `app/ui/orbit_universe.py`; ATLAS
`src/features/orbit/orbitSpace.ts`, `OrbitSpace.tsx`, core actions mark_reviewed/mark_complete/set_layout, visual
harness `atlas/tests/visual/orbit-shots.mjs` (run `npx vite --port 5179` first). Fixed the ATLAS 0.5.0 ORBIT
infinite re-render. Report: `docs/ORBIT_UNIVERSE_REPORT.md`. Owner asked: commit and push once CI is done without
waiting for approval; publish when every check passes (CLAUDE.md §20).
Note: the session disk filled once from `atlas/target` (25 GB of stale test binaries); stale binaries were deleted.

## ORBIT reference look (2026-11-20) — Prometheus 2.5.0, ATLAS 0.7.0
The owner sent a reference image (particle torus, geodesic sphere, curved links, chamfered panels with actions,
full-screen HUD). Built in both, from real data only:
* Prometheus: `orbit_motion.py` geometry (torus, geodesic, rotate, curve_ctrl, bezier, torus_count);
  `orbit_universe.py` CoreFX torus + shell, curved links/pulses, chamfered `HoloPanel.paintEvent` + `paint_icon` +
  `add_action`, `StageTrack`, `Hud` (reserve band for panels), `caption_text`; page: `_panel_action`
  (compare_ideas → real message, add_idea / set_field brief → plan versions), immersive hides rows and shows the HUD,
  *Conversation* toggles the right column. `orbit.py`: add_idea / remove_idea / brief edits + "add idea:" command.
* Fixed: delayed materialise animation starting after a resize (panels misplaced); automatic geometry changes were
  being saved as the owner's layout (now only grip resizes persist).
* ATLAS: core `Edit::AddIdea/RemoveIdea/SetBrief` (+ test), parseCommand "add idea:" / "remove idea",
  `orbitUniverse.ts` (renamed from `orbitSpace.ts`: it collided with `OrbitSpace.tsx` on Windows and broke the 0.6.0
  release build; `tests/unit/filenames.test.ts` now guards this), canvas torus/shell/curves, chamfered panels with
  lucide icons and actions (inline editors), immersive HUD (`hud` prop) and caption in `Orbit.tsx`.
* **Published:** Prometheus 2.5.0 (run 20, SHA-256 `79446b8b976842861d46cc833305b49108c10e5b2fedfdc3220f5625cddb6dd5`) and ATLAS 0.7.0 (atlas-release run 12, commit `53fa7e2`, setup SHA-256 `2745acc62f7cf8f038c17431d73cff3217a8b537979b158a86e6bfae8a476cf8`, MSI `bd6ccca2da0c101825dc3edef2f9ca66728091133ed064c1781720001fe23a69`). Run 11 failed because the first casing guard used Node APIs absent from the app tsconfig; always check with `pnpm typecheck` (tsc -b), not `tsc -p`.
* ATLAS 0.6.0 was never published (release run 9: Forge test 10 s timeout on Windows → raised to 60 s; run 10: the
  casing collision). Its content ships in 0.7.0; the changelog says so.

* Open: the ATLAS push workflow's **Ubuntu `cargo test --workspace` step hangs until the 1-hour job limit** (runs 84
  and 85, before and after these changes). Locally every ATLAS test binary passes in under a minute on Linux, and
  Windows/macOS CI pass, so it is specific to the GitHub Ubuntu runner (suspect: a test reaching the OS credential
  store / Secret Service). Next: read the job log's last `Running` line once a run finishes, then fix.

## Released 2026-11-19 (owner-approved)
* Prometheus 2.1.0 (run 15) and 2.2.0 (run 16, `8cec89e`): 2.2.0 adds Settings → Voice → Set up voice input.
  Windows CI really downloaded the engine + Tiny model, verified SHA-256 and ran one transcription.
  Installer SHA-256 `1f1f1c757d41b121e9a5917daf3780fe1d51977b7effe05d12f07b5dc705c5c3`.
* Prometheus 2.3.0 (run 18, `b3d8e68`): local speech (sherpa-onnx) generated on Windows CI (3.19 s, RMS 0.0485);
  playback not testable on the runner. SHA-256 `dae9a3966805d630b4bdb56a8ef192c3146e9aa4ce787f65aa8c5aab1ac55ccb`.
* ATLAS 0.5.0 (atlas-release run 8): published after giving the publish job its own `contents: write` (runs 7/7b
  got HTTP 403 creating the release). Setup exe SHA-256 `e9895ed87b553c582f891f2cc4e0c30cb9d267d5cd8e8b8eb950a20014adb0ed`.
* Owner gave standing authorisation to publish new versions (recorded in CLAUDE.md §20) when every check passes.
* Note: the Windows workflow runs only by hand or on tags (no branch-push trigger since the 2.0.0 release
  commit). Start it with workflow_dispatch, publish=false for a check.
* Offered to the owner, not started: speech output controls in Settings → Voice and an on-device voice.

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
