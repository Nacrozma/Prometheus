# Prometheus 2.0 — Renaissance audit

**Date:** 2026-11-17 · **Branch:** `claude/prometheus-ai-evaluation-pxqzfr` · **HEAD at audit:** `146e1c1`
(working tree clean, in sync with origin) · **Version at audit:** Prometheus Desktop 0.1.0 (unreleased,
installer built on CI only).

Verified against the code, not against older reports. Priorities: **P0** broken/unsafe, **P1** core
experience gap, **P2** important improvement, **P3** polish.

## 0. Ground rules found in the repository

* There is **no root `CLAUDE.md`**. The directive refers to one; none exists in the repository (only
  Atlas has its own docs). Operating rules were taken from the directive and the existing handover
  (`docs/desktop-evolution/NEXT_SESSION.md`).
* Earlier sessions kept `prometheus.py` unmodified while working on Atlas. This directive is the owner's
  explicit authorisation to work on Prometheus; core changes are still kept minimal and backward
  compatible (the terminal app and the HUD `gui_orb.py` must keep working).
* The owner removed OpenAI from the router on purpose (comment in `PROVIDER_ENDPOINTS`, 2026-10-03). It is
  **not** re-added.
* Atlas (`atlas/`) is a separate product and is not touched.

## 1. Existing features (verified)

| Area | Implementation | State |
|---|---|---|
| Core assistant | `prometheus.py` (4,789 lines): router, tool dispatcher, conscience check, memory, sessions, scheduler, Code Forge | Works (467 tests pass) |
| Providers | OpenRouter, Groq, Cerebras, Ollama (OpenAI-compatible), cooldown failover, `reload()` | Works; no connection test in the UI; Ollama listed even when not running |
| Tools | 31 tools; 9 marked dangerous (`write_file`, `edit_file`, `execute_shell`, `run_code_forge`, `ghost_control`, `sculpt_workspace`, `synthesize_dynamic_tool`, `apply_pending_patch`, `export_obsidian`) | Works, approval-gated |
| Safety | `safety.py`: Policy (stricter-only rules), hash-chained AuditLog, UndoJournal, write scopes; conscience tripwire | Works |
| Memory | `memory_graph.py`: entities, typed facts (fact, lesson, preference, decision), relations, recall, decay, supersede, archive; flat `memory.json` mirror | Works; the desktop UI is read-only |
| Reflection | `reflection.py` ToolStats (calls, failures, latency, lessons); offline evals | Works |
| Engineering | `engineering.py`: 17 calculators via `engineering_calc` | Works |
| Forge | `skill_forge.py` (learned skills, tests, rollback); `patch_gate.py` (self-patches, source checkout only) | Works |
| Obsidian | `obsidian_memory.py`: vault, inbox, export (approval-gated) | Works |
| Robot arm | `arm_sim.py` (FK/IK, limits, collisions, SVG); `arm_bridge.py`/`arm_gesture.py` (hardware, not in desktop) | Simulation works |
| Scheduler | persistent reminders/recurring jobs; desktop polls every 15 s | Works while the app runs |
| Sessions | core `save_session_record/list_sessions`; the desktop uses **one** `session.json` | Partial |
| Voice | edge-tts output (cloud, needs internet); Whisper input (not bundled) | Output works; input optional |
| Desktop app | `app/` (PyQt6, 3,044 lines): 11 pages, tray, Ctrl+K palette, single instance, OS credential store, data import, self-test, PyInstaller + Inno Setup | Works on CI VM; never seen on a real Windows desktop |
| Solar orb | `gui_orb.SolarSunWidget`: GLSL 3.3 sun (plasma, granules, sunspots, corona, prominences, starfield), 4 render modes, audio level uniform | Works with OpenGL; text-only fallback without |

## 2. What works
Everything in §1 marked "Works", backed by 467 passing tests (2 skipped on Linux) and the offscreen
self-test that opens every page.

## 3. Incomplete (P1 unless noted)
1. **Conversations:** single conversation only; no list, search, rename, delete, resume (core has sessions).
2. **No Home / command centre**; the app opens on the Companion.
3. **Memory page is read-only:** no create, edit, correct, archive; no category filter (P1).
4. **Composer is single-line**; no copy-message, retry, regenerate (P1).
5. **Palette** navigates only; no search across conversations, memory, tasks, files (P2).
6. **Workspace:** no file search, no Git status (P2).
7. **Providers:** no connection test, no model list, no health (P1); Anthropic and Mistral not available (P2).
8. **Avatar:** only 4 render modes; no OFFLINE/WORKING/RESEARCHING/BUILDING semantics; no fallback
   rendering without OpenGL (P1); always 60 fps while visible (P2).
9. **Forge disciplines (Architect/Builder/Debugger/Reconstructor) do not exist in Prometheus.** They are
   Atlas concepts. Prometheus has skills, self-patches and the Synthetic Council (5 personas). Building
   them is new work, not a redesign (P2).
10. Tasks: reminders only; no subtasks/priorities in the desktop (task state is a single goal record) (P2).
11. Onboarding: first run jumps to Settings with a status-bar line; no welcome flow (P2).
12. Export/backup: import exists, export does not (P2).

## 4. Broken
* None found in tests. Known hazards: Ollama appears "configured" without a running server (first
  message fails with a provider error; P2). Workflow run #2 of `prometheus-desktop` may still be hung (owner).

## 5. Outdated
* Visual design is a flat dark theme with hard-coded colours in pages (inline `setStyleSheet` calls);
  no semantic tokens; text-only sidebar without groups or icons (P1).
* README still describes Prometheus as terminal-first.

## 6. UX inconsistencies (P2)
* Page headers, spacing and empty states differ per page; several pages show raw JSON.
* Status messages go to the status bar only; no notification history.
* "Talk" is a disabled button when Whisper is absent rather than an explained state.

## 7. Architectural weaknesses
* `prometheus.py` is one 4,789-line module (P3: not rewritten — stable and tested; split only where needed).
* Pages talk to `Core` directly and refresh on show; no shared event bus (P3).
* Conversation rendering re-sets the whole HTML for every token (`_render`) — O(n) per delta (P2, perf).

## 8. Security concerns
* `execute_shell` uses `shell=True` in the workspace, gated by approval + conscience tripwire + policy.
  Unchanged; the desktop never auto-runs it (auto-approve is opt-in with a warning) (P2: documented).
* Generated code without Docker runs in a "best effort" subprocess (documented, not a boundary).
* Keys: OS credential store; never written to settings; `.env` honoured. OK.
* Workspace preview refuses `.env`, binaries, >200 KB, paths outside root. OK.

## 9. Performance
* Orb at 60 fps whenever visible (software GL in CI); unmeasured on real GPUs (P2).
* Full-HTML re-render per streamed token (P2).

## 10. Missing functionality (from the directive)
Universal search, Home, conversation management, memory editing, provider testing, document
intelligence (PDF/DOCX/XLSX), research workspace, workflow automation, export, notification centre,
onboarding, Forge disciplines. Each is planned below or recorded as not done.

## 11. Testing gaps
* GUI tests use stubs for most widgets; the real window is exercised by one offscreen test and the
  self-test. No screenshot regression.

## 12. Dependencies
PyQt6 6.12, PyOpenGL, openai, python-dotenv, keyring, edge-tts (optional), openai-whisper (optional,
large). No new dependency is needed for the Renaissance shell.

## Feature preservation checklist (must still work at the end)
- [ ] Terminal `python prometheus.py` and HUD `python gui_orb.py` start (tests)
- [ ] Every one of the 11 sections opens (self-test)
- [ ] Approval cards gate all 9 dangerous tools; Deny is default; Esc stops
- [ ] Streaming, Markdown (escaped), copy code
- [ ] Session persistence across restarts
- [ ] Memory recall, stats, Trust labels (unverified/verified)
- [ ] 17 engineering calculators
- [ ] Skills list + rollback; patches listed (unavailable in packaged app)
- [ ] Workspace tree + safe preview
- [ ] Reminders add/cancel/list; due reminders delivered + tray notification
- [ ] Obsidian vault + export through approval
- [ ] Arm simulation (FK/IK/limits), simulation banner
- [ ] Reflection stats + synthetic eval label
- [ ] Trust: policy table, audit tail + verify, undo
- [ ] Settings: keys in OS store, reconnect, workspace, tray, notifications, sign-in, reduced motion,
      auto-approve warning, data import
- [ ] Tray, single instance, Ctrl+K, Ctrl+N, Ctrl+,, Ctrl+Q
- [ ] Packaging spec and installer script unchanged in behaviour
