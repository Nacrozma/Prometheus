# Atlas 0.5 "Presence & Intelligence": audit and plan

**Audited:** 2026-11-10, branch `claude/prometheus-ai-evaluation-pxqzfr` at `efcb02c` (release
`atlas-v0.4.0` was built from `98f7ccd`; the two later commits touch only a test and INSTALL.md).

**Method:** read from the code and from test runs, not from earlier reports. Where a claim could not be
checked here, it says so.

## 1. Baseline

| Check | Result | Where it ran |
|---|---|---|
| Rust tests (`cargo test --workspace`) | 138 pass, 0 fail (4 need real services and are skipped) | This container, Linux |
| Frontend (typecheck, lint, Vitest) | Clean; 48 of 48 tests pass | This container |
| Prometheus-side adapter tests (pytest) | 409 pass, 36 skipped (need Prometheus hardware or optional packages) | This container |
| Desktop end-to-end (18 tests, stand-in voice engines) | 18 of 18 pass | This container; CI run 26 on Ubuntu and Windows |
| CI `atlas` run 26 (Windows, Ubuntu, macOS build; Windows and Ubuntu e2e) | All 5 jobs pass | GitHub Actions |
| Real voice engines (real downloads, real synthesis and recognition) | Pass on Windows and Ubuntu | GitHub Actions run 42626613303 |
| Installer: clean install and upgrade from 0.3.0 | Pass | GitHub Actions, Windows VM |
| Reproducible build | `pnpm install --frozen-lockfile` + committed `Cargo.lock`; release built by `atlas-release.yml` | |

**Not checked anywhere yet:**
* A real microphone, real speakers or headphones, on any machine.
* Any provider with a real paid key (only Anthropic's "invalid key" path ran live).
* Prometheus with its real model (the real runtime ran with a scripted stand-in for the model).

## 2. What 0.4.0 really contains (verified against the code)

| Area | Verified state |
|---|---|
| Voice output | sherpa-onnx 1.12.40 run as a separate process per sentence; Piper voices; replies spoken sentence by sentence; stop, pause, replay. Real engine proven in CI |
| Voice input | Push-to-talk only; whisper.cpp 1.8.2, **Windows only**; transcript lands in the message box for review |
| Capture API | `ScriptProcessorNode` (**deprecated**), `audioEngine.ts:281` |
| Device selection | Microphone: yes (Settings → Voice). **Output device: no** |
| Voice ring | WebGL2, driven by the real analyser; 8 states; still frames under reduced motion; SVG fallback; stops when hidden. **Not in the first-launch introduction** |
| Downloads | SHA-256, size cap, archive containment, per-file manifest, cancel, remove, refused offline |
| Privacy | No background listening; audio held in memory and wiped; temp WAVs deleted after each call and at start-up; audit entries hold ids only |
| Desktop presence | **None.** No tray, no global shortcut, no compact window, no OS notifications (the Tauri plugins are not installed) |
| Home | Reads real data: provider, tools, memory count, approvals, 6 recent conversations, 6 recent tasks, sibling chip. No briefing, deadlines, recap or configuration |
| "Tasks" | Records of tool-using turns (the execution history). **There is no owner-facing to-do, deadline or reminder model** |
| Memory | Owner-approved memories, full-text search, pinned, project scope, source, last-used. **No confidence, no staleness, no duplicate detection** |
| Knowledge Vault | **None.** Text files can be shared into a conversation; no PDF or Office parsing, no index |
| Proactive work | **None.** No scheduler, no background jobs |
| Specialist agents, Workflow Studio | **None** |
| Integrations | Web search (Tavily) works. Calendar, email and storage are shown as planned, not as working |
| Sibling link | Pairing, HMAC, replay protection, capabilities, three mission modes, ledger with recovery. Text context only: **no files, manifests or patches** |
| Trust | Audit log, Mission Control and the mission ledger exist as three separate views; **no single activity timeline** |
| Backup | Backup, validated restore, secrets excluded, `quick_check` in diagnostics. No scheduled backups, no guided corruption recovery |
| Platforms | Windows: full. Linux: everything except speech recognition. macOS: builds and unit tests pass in CI; no voice; never launched by a person |

## 3. Feature matrix for this evolution

**Key:** ✅ existing and verified · 🟡 existing but incomplete · 🔴 broken or unreliable · ⬜ not implemented.

No feature is currently known to be broken. "Unreliable" is used where real-world behaviour is unproven.

### Voice (Parts 2 and 3)

| Feature | Now | Planned |
|---|---|---|
| Local speech output and recognition engines | ✅ CI, real engines | Keep |
| Real microphone and speaker behaviour | 🔴 unproven | Voice check shipped in 0.4.1; **the owner's run is still open** (VOICE_HARDWARE_VALIDATION.md) |
| Maintained capture API | ✅ done in 0.4.1 (AudioWorklet; e2e-verified on WebView2 and WebKitGTK) | Keep |
| Output-device selection | ✅ done in 0.4.1 on Windows; not offered by WebKitGTK (Linux) | Keep |
| Microphone selection, speed, volume, voice choice | ✅ | Keep |
| Evidence-based default model | 🟡 base chosen from CI numbers | 0.4.1: decide from the owner's measurements |
| Audio setup wizard | ✅ done in 0.4.2 (Guided setup) | Keep |
| Sentence transitions (gaps between sentences) | 🟡 one engine start per sentence | 0.4.2: measure on real hardware first, then pre-synthesise further ahead or keep the engine warm |
| Immediate interruption without resubmitting | ✅ e2e | Keep; re-verify on hardware |
| Ring in the first-launch introduction | ✅ done in 0.4.2; moves only with real speech (e2e-verified) | Keep |
| Typed ↔ spoken handoff in one conversation | 🟡 works; the core already refuses a second request while one is running in a conversation (tested), so no duplicate can be sent | 0.5.0: handoff polish (Conversation Handoff) |
| Linux and macOS recognition | ⬜ | 0.6.0: evaluate sherpa-onnx's own Whisper runtime (one engine for both directions, all three systems) |

### Presence and Command Center (Parts 3, 4, 5)

| Feature | Now | Planned |
|---|---|---|
| Global shortcut, tray | ✅ done in 0.4.2 (off by default; not yet tried by a person) | Keep |
| Quick entry, compact floating presence | ⬜ | 0.5.0 |
| Notifications (in-app list + optional system notifications, permission in the core, de-duplication) | ✅ done in 0.4.2 | 0.5.0 adds quiet hours and Focus Mode on top |
| Command Center | 🟡 Home shows real status only | 0.5.0: extend Home (briefing, to-dos, deadlines, missions, errors; configurable) |
| Owner to-dos, deadlines, reminders | ⬜ | 0.5.0: new tables; needed by the briefing, recap and proactive work |
| Session recap | ⬜ | 0.5.0: built from recorded events since the last session; resume only with approval |
| Focus Mode | ⬜ | 0.5.0: safety and failure notices always pass through |
| Personality depth | 🟡 presets and axes | 0.5.0: initiative and follow-up behaviour, voice delivery; custom instructions stay private |

### Memory and knowledge (Part 6)

| Feature | Now | Planned |
|---|---|---|
| Review, edit, delete, export, search, project scope | ✅ | Keep |
| Provenance | 🟡 source text only | 0.5.0: link to the conversation or document |
| Confidence, staleness, duplicates | ⬜ | 0.5.0 |
| Private vs shared separation | ✅ nothing is shared with Prometheus automatically (tested) | Keep; add an explicit "shared context" class in 0.7.0 |
| Knowledge Vault | ⬜ | 0.5.0: text, Markdown, PDF, DOCX with citations. Spreadsheets in 0.6.0. Imported text is always treated as untrusted |

### Proactive, agents, workflows, integrations (Parts 7, 8, 9)

| Feature | Now | Planned |
|---|---|---|
| Scheduler with scope, frequency, limits, history, global pause | ⬜ | 0.5.0: reminders and the daily briefing only. Nothing that spends money without a limit |
| Scheduled research, recurring reports, monitoring | ⬜ | 0.6.0 |
| Specialist agents | ⬜ | 0.6.0: bounded roles inside the existing engine, budgets and approvals |
| Workflow Studio | ⬜ | 0.6.0: on the existing task state machine and approvals |
| Calendar, email, storage | ⬜ | 0.6.0: real connectors only; each needs the owner's account authorisation |

### Sibling, platform, trust (Parts 10, 11, 12)

| Feature | Now | Planned |
|---|---|---|
| Pairing, HMAC, replay protection, ledger, three modes | ✅ against the real runtime | Keep |
| File exchange, manifests, patch review | ⬜ | 0.7.0 |
| Remote link | ⬜ (proposal only) | Not before 0.7.0, and only with the full security design |
| Offline states told apart (app, internet, provider, local model, Prometheus) | 🟡 offline mode and per-provider health exist; no single clear indicator | 0.5.0 |
| Trust and Activity Center | 🟡 three separate views | 0.5.0: one read-only timeline over data already recorded |
| Scheduled backups, guided recovery | 🟡 manual backup and restore | 0.5.0 |
| Credential storage, tool allowlists, path containment, approvals | ✅ tested | Keep; re-run the security suite each release |

## 4. Technical debt and risks found

| Item | Severity | Plan |
|---|---|---|
| Voice has never run on real audio hardware | High | 0.4.1, with the owner |
| Deprecated `ScriptProcessorNode` | Medium | 0.4.1 |
| One engine process per spoken sentence (about 1.5–1.9 s each in CI) | Medium | Measure on the owner's PC, then decide (0.4.2) |
| Speech recognition is Windows-only | Medium | 0.6.0 evaluation |
| Frontend ships as one 1.1 MB script | Low | Split heavy pages when the Command Center lands |
| No owner-facing task model | Blocks 0.5.0 | First 0.5.0 item |
| No scheduler | Blocks proactive work | 0.5.0 |
| Paid providers and the real Prometheus model never run live | Medium | Needs the owner's keys; cannot be closed from here |
| Installer is not code-signed | Low | Needs a certificate (a purchase) |
| GitHub Actions use Node 20 actions (deprecation warnings) | Low | Bump action versions |

## 5. Recommended sequence

The boundaries in the directive hold after the audit, with two adjustments:
* **Owner to-dos and a scheduler move to the front of 0.5.0.** The briefing, recap, deadlines and every
  proactive feature depend on them.
* **Spreadsheets and Linux/macOS recognition move to 0.6.0.** Neither blocks anything in 0.5.0.

| Release | Contents | Depends on |
|---|---|---|
| **0.4.1** Real-world stabilisation | AudioWorklet capture; output-device choice; in-app Voice check that records device, latency and accuracy; fixes from the owner's results; default model decided from those results | **The owner's PC** for the hardware pass |
| **0.4.2** Experience completion (**released**) | Track A: ring in the introduction; audio setup wizard; tray; global shortcut; notifications. **Track B (blocked on the owner's Voice check report):** recognition accuracy, sentence-transition and playback tuning, microphone compatibility fixes, latency work, default model | Track B needs real-hardware evidence |
| **0.5.0** Presence & Intelligence | To-dos and deadlines → scheduler (reminders, daily briefing, global pause) → notification engine and Focus Mode → Command Center and session recap → quick entry → memory quality → Knowledge Vault → Trust Center → personality depth | 0.4.2 presence foundation |
| **0.6.0** Universal Companion | Workflow Studio, specialist agents, real integrations, cross-platform recognition | 0.5.0 scheduler and notification engine |
| **0.7.0** Deeper Collaboration | File exchange with manifests, patch review, mission plans; remote only if the security work is complete | Coordinated change to `sibling_adapter.py` |

**High-risk changes, handled one at a time with their own tests:**
* A scheduler that can start work without the owner present (limits, global pause, fresh approval for
  anything sensitive).
* Document parsing (untrusted input: size limits, no macros or scripts executed, prompt-injection framing).
* Global shortcut and tray (focus stealing, shortcut conflicts, OS differences).
* Any change to the sibling protocol (both sides must stay compatible with the previous version).

## 6. What cannot be done from the build environment

* **Hardware validation** (Part 2): no microphone or speakers exist here or in CI. The owner runs the
  Voice check on their PC; the report it produces is the evidence.
* **Noise, accents, speaking speed:** need real people speaking.
* **24-hour endurance on the target machine**, GPU profiling on the owner's graphics card.
* **macOS by hand:** CI builds it; nobody has launched it.
