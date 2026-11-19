# ORBIT — Architecture audit (Phase 0)

Date: 2026-11-19 · Branch `claude/prometheus-ai-evaluation-pxqzfr` · Baseline commit `39ae728` (Prometheus Desktop 2.0.0 released).

ORBIT is built twice, independently: once in Prometheus (Python/PyQt6) and once in Atlas (Rust/Tauri/React).
They share no code, no data, no credentials and no runtime. Each section below is about one product only.

> Constitution note: the root `CLAUDE.md` says Atlas must not be changed as part of Prometheus work. The ORBIT
> directive explicitly authorises Atlas work, so the Atlas changes were made as separate Atlas work, in `atlas/`
> only, in their own commit, following Atlas's own conventions.

---

## Part A — Prometheus

### What already existed (verified in the code)

| Capability | Where | Used by ORBIT as |
|---|---|---|
| Streaming turns with tools, stop, confirmation hook | `gui_orb.PrometheusWorker` (`text_delta`, `confirmation_requested`, `provide_confirmation`, `request_stop`) | the dialogue and every “Prometheus works on it” step |
| Approval gate + approval card with diffs | `app/ui/pages/companion.ApprovalCard`, `app/services/approval.py` | tool approvals inside ORBIT steps (unchanged) |
| Forge discipline boundaries | `app/services/forge_missions.decide` | steps done by Architect/Builder/Debugger/Reconstructor |
| Conversations store | `app/services/conversations.py` | ORBIT's dialogue and each step's own conversation |
| Speech input (push-to-talk, real mic level) | `gui_orb.WhisperVoiceThread` (`audio_level_signal`, `transcription_done`) | listening; turn-taking reads the level |
| Speech output with real playback level | `gui_orb.TTSManager` (`speak`, `is_busy`, `audio_callback`) | Prometheus speaking; avatar reacts to playback |
| Solar avatar with semantic states and signs | `app/ui/solar.SolarAvatar`, `app/ui/avatar_overlay.py`, painted fallback `app/ui/sun.SolarGlyph` | the centre of the stage (not replaced) |
| Atomic JSON state, quarantine of damaged files | `state_io.py` | ORBIT session files |
| Scheduler tool | `schedule_task` via the worker | “Schedule a reminder” steps |

### Gaps found (and how ORBIT closes them)

| Gap | Resolution |
|---|---|
| No structured plan, no versions | `app/services/orbit.py`: plan model, versions with author/why, approve/restore/compare |
| No workflow / execution states | state machine with the ten required states, transitions recorded with time and detail |
| Voice was push-to-talk only, no end-of-turn detection | `app/services/orbit_voice.TurnTaker` on the real mic level; continuous mode |
| No barge-in (no echo cancellation in the audio stack) | mic is paused while Prometheus speaks; interruption is Stop speaking / Space / Esc / Talk — documented |
| No planning/executing avatar states | `PLANNING`, `EXECUTING` added (EXECUTING draws the real completed share) |
| No system-wide hotkey in Prometheus | in-app `Ctrl+Shift+O` / `Ctrl+Shift+Space` only — documented limitation |

### Risks identified

* A plan step could be mistaken for permission → steps map only to `OPERATIONS`; unknown operations fall back to an
  ordinary Prometheus turn, and every tool with real-world effects still asks (auto-approve forced off in ORBIT).
* Restart mid-step could repeat an action → recovery pauses running/awaiting steps and never re-runs them.
* Model output is untrusted → plan JSON is parsed, bounded and normalised (`normalise_plan`); loops are dropped.
* Speech leaves the computer with edge-tts → stated in the UI; muting speech keeps everything local.

---

## Part B — Atlas

### What already existed (verified in the code)

| Capability | Where | Used by ORBIT as |
|---|---|---|
| Turn engine with approvals, budgets, cancellation | `core/src/engine.rs`, `approvals.rs`, `chat_send`/`chat_cancel` | the dialogue and each “Atlas works on it” step |
| Approvals dock (global) | `src/app/ApprovalDock.tsx` | tool approvals during ORBIT steps (unchanged) |
| Voice: whisper.cpp STT, sherpa-onnx TTS, analyser level | `core/src/voice/*`, `src/features/voice/audioEngine.ts`, `src/state/voice.ts` | listening, speaking, turn-taking level |
| Electric-blue voice ring driven by real audio | `src/features/voice/VoiceRing.tsx` | the centre of the ORBIT stage (not replaced) |
| SQLite with versioned migrations and pre-migration backup | `core/src/storage` (schema 9) | schema 10 `orbit_sessions` |
| Tasks (to-dos) service | `core/src/todos.rs` | “Add to my tasks” steps |
| Specialists, missions | `specialists.rs`, sibling missions | not mapped yet (see limitations) |

### Gaps found (and how ORBIT closes them)

| Gap | Resolution |
|---|---|
| No plan/workflow model | `core/src/orbit.rs` in the trusted core; the UI can only send checked actions |
| No way to give a turn planning context without polluting the message | `TurnParams.orbit_session`: instructions + current plan added to the system prompt |
| Voice phases exist but no continuous turn-taking | `TurnTaker` (TypeScript) on `audio.level()`; listens again after speech ends |
| No ORBIT route/immersive shell | `orbit` route, rail entry, `ui.immersive` hides rail and focus bar |

### Risks identified

* The front end must not be a security boundary → approval, build, start, finish and retry are validated in Rust
  (`orbit::apply`); plans authored “by Atlas” are read by the core from stored messages (`orbit_propose`).
* Barge-in during speech would capture Atlas's own voice → microphone paused while speaking; Stop speaking/Esc.

---

## Implementation plan (as executed)

1. Prometheus: service + tests → voice turn-taking + tests → page, avatar states, shell wiring → smoke test → screenshots.
2. Atlas: core module + Rust tests → migration, engine context, commands → bridge/schemas → page, route → vitest.
3. Phase 8 reports, continuity documents, commit and push (no release).
