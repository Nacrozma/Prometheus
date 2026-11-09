# ATLAS Co-Pilot: master roadmap and implementation matrix

**Baseline:** v0.2.0 plus the Phase 7 fixes (unreleased). Prepared 2026-11-07 from the actual repository, not
from earlier reports.

**Status:** awaiting the owner's authorization. Nothing below the matrix has been implemented.

## Status meanings

| Status | Meaning |
|---|---|
| **Implemented** | Working, with automated tests |
| **Partial** | Some of it works; what's missing is named |
| **Unverified** | Code exists but no real-condition test (e.g. no live keys) |
| **Missing** | Not built |
| **Blocked** | Needs something outside the code (keys, hardware, a decision) |

## 1. Implementation matrix

### Identity, design and first launch

| Capability | Status | Where / notes |
|---|---|---|
| Deep Orbit identity (navy, cyan/teal, globe emblem, typography, rail) | Implemented | `src/styles/tokens.css`, `components/Emblem.tsx`; axe-core audit in e2e |
| Prometheus solar avatar (WebGL2 port, states, reduced motion, fallback) | Implemented | `features/siblings/avatar/*`; shader matches the original line for line |
| Avatar states beyond idle/thinking/speaking/adapting/offline (connecting, receiving, engineering, running tests, awaiting approval, reporting, error, paused) | Partial | 5 render states are mapped from real link and mission state; finer states need a richer mapping, not new shaders |
| Splash / first-run onboarding | Implemented | `features/onboarding`, `App.tsx` splash |
| **Cinematic first-launch with "Created with love."** | Implemented (0.3.0) | `features/first-launch/*`; runs once (core-owned state), Skip/Esc, replay in Settings → About, still scene under reduced motion; the voice ring joins it in Stage 2 |
| **Electric-blue audio-reactive voice ring** | Implemented (0.4.0) | `features/voice/VoiceRing.tsx`, `ringShader.ts`. WebGL2, driven by the live Web Audio analyser (playback or microphone); 8 states; still under reduced motion; static fallback. Not yet part of the first-launch introduction (next step). Not yet seen on the owner's PC |

### Companion and conversation

| Capability | Status | Where / notes |
|---|---|---|
| Streaming chat, Markdown, code blocks, tables | Implemented | `features/companion/*`, `components/Markdown.tsx` |
| History, search, rename, archive, export | Implemented | `conversations.rs`, Companion list, command palette |
| Retry / regenerate | Implemented (0.3.0) | Regenerate in place for text replies (never for replies that used tools); Try again after a failure; Ctrl/⌘+Shift+Enter; Esc stops. No response branching |
| Per-conversation model / provider switch | Implemented | Companion model picker; routing tiers |
| Long-context management | Implemented | `context::fit_history`, with a notice when old turns are dropped |
| Attachments | Partial | File share via native dialog (grants); no drag-and-drop, no PDF/Office parsing |
| Personality (presets, axes, name, custom instructions) | Implemented (0.3.0) | Seven presets owned by the core; custom instructions (2000 chars, secret-checked, never sent to Prometheus) |

### Voice and desktop presence

| Capability | Status | Where / notes |
|---|---|---|
| Voice input (push-to-talk, transcription) | Implemented (0.4.0); hardware MANUAL | whisper.cpp 1.8.2 + Whisper models, on-device. Push-to-talk, transcript review/edit, cancel, single-flight, mic-loss handling. Real engines verified in CI; a real microphone only on the owner's PC |
| Voice output (TTS for responses) | Implemented (0.4.0); hardware MANUAL | sherpa-onnx 2.0.1 + Piper voices, on-device. Progressive sentence playback, Markdown-aware, stop/pause/replay/mute. Real engines verified in CI; real speakers only on the owner's PC |
| Compact window, tray, global shortcut, always-on-top | Missing | Tauri plugins exist (tray, global-shortcut); not used |
| Desktop notifications | Missing | In-app toasts only |

### Atlas Forge

| Capability | Status | Where / notes |
|---|---|---|
| Four disciplines with backend tool allowlists | Implemented | `forge/mod.rs` `Discipline::allows`; engine refuses tools that weren't offered |
| Explorer, file view, diff, terminal, tests, git, changes/revert | Implemented | `features/forge/Forge.tsx`; e2e |
| Approvals with real diffs; command policy; no shell; timeouts; secret scrub | Implemented | `forge_tools.rs`, `runner.rs` |
| Snapshot revert that refuses over newer changes | Implemented | `forge::revert_change` |
| Project creation from scratch / templates | Partial | Builder can write files into a chosen folder; no "new project" wizard |
| Discipline recommendation by Atlas | Missing | Owner chooses |
| Build/packaging button, dependency inspection view | Partial | Build command field exists; no dependency view |

### Providers, routing and costs

| Capability | Status | Where / notes |
|---|---|---|
| OpenAI, Anthropic, OpenRouter, Mistral, Cerebras, Ollama adapters | Implemented, **Unverified live** | Wire formats tested with mocks; only Anthropic's 401 path verified live |
| OS credential store; masked display; test/remove | Implemented | `credentials.rs`; Windows Credential Manager tested in CI |
| Routing modes and tiers; explained fallback; shut-down-model guard | Implemented | `providers::route_tiered`, `pricing::availability` |
| Price schedule: verified / historical seed / owner override; availability | Implemented | `pricing.rs`; audited 2026-11-07 |
| Budgets: request / mission / day / month, warn, ask or stop | Implemented | `usage.rs`; engine checks before sending |
| Actual provider-billed cost | Missing | Estimates only (no provider returns per-request billing here) |

### Prometheus sibling link

| Capability | Status | Where / notes |
|---|---|---|
| Protocol v1, pairing, HMAC, replay protection, capabilities, health, revoke | Implemented | Verified against the real adapter and the real Prometheus runtime |
| Consultation / collaborative / delegated modes | Implemented | Real runtime verified with a stand-in model; **real-model run Blocked** (keys) |
| Delegated-mission workspace and tool allowlist (Prometheus side) | Implemented (Phase 7) | `sibling_adapter.py` |
| Shared Mission Workspace (file manifests, hashes, patches) | Missing | Text context only today |
| Remote transport | Missing | See `docs/phase7/REMOTE_CONNECTIVITY_PROPOSAL.md` |

### Missions, Map and Mission Control

| Capability | Status | Where / notes |
|---|---|---|
| Ledger state machine, idempotent send, recovery, lost-contact pause | Implemented | `sibling/missions.rs` |
| Mission plan with tasks, dependencies and per-task owner | Missing | Missions have objective, mode, events and result only |
| Mission Control ownership display | Partial | Atlas tasks plus shared missions listed; no per-task owner model |
| Atlas Map with real sibling, mission and Forge nodes | Implemented | `map.rs`; link edge only while connected (tested) |

### Command Center, notifications and briefings

| Capability | Status | Where / notes |
|---|---|---|
| Home dashboard (provider, tools, memory, tasks, approvals, sibling chip) | Implemented | `features/home/Home.tsx` |
| Notification engine (priority, quiet hours, history, de-duplication) | Missing | |
| Briefings / scheduled reports | Missing | |

### Memory and knowledge

| Capability | Status | Where / notes |
|---|---|---|
| Approved memories, FTS search, pinned, project scope, export/delete | Implemented | `memory.rs`, Memory page |
| Provenance, confidence, outdated detection | Partial | Source and last-used are stored; no confidence or staleness detection |
| Knowledge Vault (documents, retrieval, citations) | Missing | No document ingestion beyond text files |

### Autonomy and workflows

| Capability | Status | Where / notes |
|---|---|---|
| Approval-first tool engine, policy classes, audit log | Implemented | `tools/*`, `policy.rs`, `approvals.rs`, `audit.rs` |
| Background monitoring / scheduling / Workflow Studio | Missing | |
| Specialist multi-agent coordination | Missing | Prometheus is a peer, not a sub-agent |
| Integrations (calendar, email, storage) | Missing | Integrations page shows them as planned; web search (Tavily) works |

### Trust, recovery, platform and quality

| Capability | Status | Where / notes |
|---|---|---|
| Diagnostics (database, credential store, providers, Forge, sibling, missions) | Implemented | Settings → Diagnostics |
| Backup / validated restore, secrets excluded | Implemented | `backup_inspect` / `restore_from`; secret scan test |
| Trust & Activity Center (one timeline of everything Atlas did) | Partial | Audit log, Mission Control and the ledger exist separately; no unified view |
| Offline mode (local providers only) | Implemented | `network.offline_mode` |
| Arabic / RTL | Missing | |
| Windows installer, upgrade and uninstall | Implemented | Verified on a Windows VM (Phase 7) |
| Stress tests (500 functional / 100 failure / endurance) | Partial | About 160 automated tests today (113 Rust, 19 Vitest, 13 e2e, 16 adapter) plus the Phase 7 reliability loop; no 24 h run |

## 2. Reuse instead of rebuilding

* **Voice ring:** reuse the `PrometheusAvatar` WebGL2 lifecycle (pause when hidden, reduced motion,
  context loss, fallback) as a shared base, with a new shader.
* **Command Center:** extend Home and Mission Control. Do not add a second dashboard.
* **Notifications:** build on the existing `atlas://changed` event bus and the audit log.
* **Trust Center:** a read-only union of `audit_events`, `tasks`, `mission_events` and `usage_records`
  (all already recorded).
* **Workflows:** reuse the task state machine, dispatcher and approvals. Do not create a second executor.
* **Desktop presence:** Tauri tray and global-shortcut plugins, with commands kept in the Rust shell.

## 3. Risks and dependencies

| Risk | Mitigation |
|---|---|
| Voice on Windows: WebView2 speech APIs differ; local speech-to-text needs a model download | Start with OS TTS (no download), make STT pluggable (local Whisper vs cloud), label clearly where audio goes |
| Audio-reactive animation needs real playback analysis | Use a Web Audio `AnalyserNode` on Atlas's own audio element; if the OS TTS can't be tapped, synthesize via a provider TTS into an audio element |
| Scope size (the master prompt is several releases of work) | Ship stage by stage; each stage independently releasable with its own tests |
| Live provider behaviour unverified | Run the live check with the owner's keys before Stage 2 |
| Real Prometheus model run unverified | Owner runs `sibling_adapter.py` with Prometheus's model configured; checklist in `REAL_PROMETHEUS_INTEGRATION.md` |
| Background autonomy and privacy | Global pause, per-job scope, no desktop capture, renewed approval after reconnect |

**Critical path:** voice output → voice ring (it reacts to real playback) → first-launch sequence (it
introduces the ring) → Companion home polish. Notifications and the Trust Center depend only on existing
events.

## 4. Stage 1: Companion foundation and the first-launch dedication (approved 2026-11-08, built for 0.3.0)

**Goal:** the experience the owner meets first, without new risky subsystems.

| Area | Item | Detail |
|---|---|---|
| Frontend | First-launch cinematic | Navy universe → particles → Atlas globe → dedication **"Created with love."** (exact text) → "Welcome. I'm Atlas. It's good to finally meet you." (configurable) → onboarding |
| Frontend | First-launch controls | Runs once (persisted), Skip, replay in Settings → About, reduced-motion static version, no network or keys needed, resumes safely if the app is closed mid-sequence. Not mentioned in onboarding beforehand |
| Frontend | Personality presets | Professional / Friendly / Analytical / Concise / Detailed / Creative / Custom, mapped onto the existing tone, verbosity and proactivity axes, plus a custom-instructions box |
| Backend | Settings | `companion.preset`, `companion.custom_instructions` (validated, length-capped, never sent to Prometheus) |
| Backend | First-launch state | `first_launch.completed_at`, `replay_requested` |
| Frontend | Conversation | Regenerate last reply; copy whole conversation; keyboard shortcuts for retry and stop |
| Tests | Vitest | Sequence state machine (skip, replay, reduced motion) |
| Tests | e2e | First launch shows the dedication exactly once; Skip works; replay works; reduced-motion path |
| Tests | Rust | Settings validation, custom instructions excluded from mission payloads |
| Docs | | `ATLAS_FIRST_LAUNCH_EXPERIENCE.md`, `ATLAS_EXPERIENCE_SPECIFICATION.md`, changelog |

**Not in Stage 1:**
* The voice ring and voice I/O (Stage 2, after a decision on speech-to-text: local download vs cloud).
* Tray, notifications, workflows, Knowledge Vault, multi-agent and remote.

**Owner's decisions (2026-11-08):**
1. Stage 1 scope approved as above.
2. The welcome line stays exactly as written ("Welcome. I'm Atlas. It's good to finally meet you."). It
   never uses the owner's name.
3. Speech recognition for Stage 2 runs **on the PC** (Whisper via whisper.cpp; no audio leaves the
   computer). Model sizes, from the whisper.cpp model list:

   | Model | Download | Note |
   |---|---|---|
   | tiny | 75 MiB | fastest, least accurate |
   | base | 142 MiB | proposed default: multilingual, fast on any recent PC |
   | small | 466 MiB | noticeably more accurate |
   | large-v3-turbo (q5_0) | 547 MiB | near-best accuracy for its size; slower on older CPUs |
   | medium | 1.5 GiB | |
   | large-v3 | 2.9 GiB | best accuracy, slowest |

   The model is downloaded on first use of voice input, with its size shown first. It is not bundled, so
   the installer stays small.

What was built is described in ATLAS_EXPERIENCE_SPECIFICATION.md and ATLAS_FIRST_LAUNCH_EXPERIENCE.md.

## 5. Later stages (summary)

| Stage | Contents |
|---|---|
| 2 | **Released in 0.4.0.** Local TTS (sherpa-onnx + Piper) → audio-reactive ring → local push-to-talk (whisper.cpp). OS TTS was rejected: its audio can't be analysed, so the ring couldn't be real. See ATLAS_VOICE_ARCHITECTURE.md. Remaining: ring in the first-launch introduction, wake word (deferred), cloud engines (deferred), owner hardware check |
| 3 | Desktop presence: tray, global shortcut, compact window, desktop notifications |
| 4 | Command Center polish, notification engine, briefing foundation |
| 5 | Memory provenance and staleness, Knowledge Vault (documents and citations) |
| 6 | Permissioned background jobs, scheduling, reminders |
| 7 | Workflow Studio and integrations |
| 8 | Specialist agents and richer Prometheus missions (plans, tasks, shared workspace with manifests and patches) |
| 9 | Remote sibling transport (proposal in `docs/phase7/`) |
| 10 | Local models, performance, endurance (24 h), final security review |
