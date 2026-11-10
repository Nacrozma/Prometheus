# Changelog

## 0.4.1 — 2026-11-10

Voice groundwork for testing on real hardware. **A real microphone and real speakers have still not
been tested by anyone**; the Voice check below is how the owner does that
(docs/VOICE_HARDWARE_VALIDATION.md).

### Added
- **Voice check** (Settings → Voice): tests your real speakers and microphone and records what Atlas
  measured.
  - Speakers: time to first sound, and what you heard.
  - Microphone: read a set sentence under chosen conditions; shows what was recognised, the share of
    words right, speech length, recognition time and input level.
  - **Copy report** gives the results with the PC, devices and models. No audio is kept or sent.
- **Output device choice** (Settings → Voice → Play through), where the system lets apps choose
  (Windows). If the chosen device disappears, Atlas falls back to the system default.

### Changed
- **Microphone capture uses an audio worklet**, replacing the deprecated ScriptProcessor. The old path
  remains only as a fallback for web views without worklet support. End-to-end tests confirm the
  worklet is what runs on Windows (WebView2) and Linux (WebKitGTK).
- Microphone and speaker ids are validated in the core.

### Not changed
- The default recognition model stays "base" until real measurements exist.

## 0.4.0 — 2026-11-09 (released: atlas-v0.4.0)

### Added
- **Voice, entirely on this computer:** no speech service, no API key; works offline once the files
  are downloaded.
  - **Speech output:** sherpa-onnx 1.12.40 running Piper voices (pinned to 1.x: 2.0 removed the espeak-ng phonemizer Piper voices need).
    - Alba (UK English, CC BY 4.0) is the default. Lessac (also a light version), Ryan and Kareem
      (Arabic) are optional.
    - Replies are read aloud as they stream, a sentence at a time; code and tables are announced, not
      read.
    - Speed, volume, pause, stop, replay and mute.
  - **Speech recognition:** whisper.cpp 1.8.2 with Whisper tiny, base (the starting recommendation),
    small or large-v3 turbo.
    - Push-to-talk (microphone button or Ctrl/⌘+Shift+Space); Esc cancels.
    - The transcript lands in the message box to edit, or is sent automatically if you choose.
  - **The electric-blue voice ring:** an original circular waveform driven by the real playback or
    microphone signal, with idle, listening, processing, speaking, paused, interrupted, error and
    offline states. It is still under reduced motion and has a static fallback.
  - **Settings → Voice:**
    - downloads with sizes and licences shown first, real progress, cancel, checksum verification and
      Verify/Remove;
    - microphone choice and test;
    - a hardware report with a model recommendation;
    - an on-device benchmark;
    - privacy commitments.
  - **The Voice page** is now the voice hub. A "Speak" action is added to replies.
- **Security:** downloads only from a pinned list with publisher checksums. Unpacking is contained (no
  `..`, absolute paths or links). Engines run as separate processes without a shell. Temporary audio
  is deleted after each call. Nothing is logged, nothing goes to Prometheus, and offline mode blocks
  downloads.

## 0.3.0 — 2026-11-08

### Added
- **First-launch introduction:**
  - A deep-navy universe, ambient stars and the Atlas globe, then the creator's dedication and Atlas's
    first words.
  - Plays once, including once after upgrading from 0.2.x.
  - Skip or Esc at any moment; replay from Settings → About.
  - A still version under reduced motion.
  - Works offline and never blocks startup.
  - Details: `docs/ATLAS_FIRST_LAUNCH_EXPERIENCE.md`.
- **Personality presets:**
  - Professional, Friendly, Analytical, Concise, Detailed, Creative and Custom, in Settings → Companion
    and onboarding.
  - Presets set tone, length and initiative; adjusting those by hand makes the personality Custom.
- **Custom instructions:**
  - Up to 2000 characters, refused if they look like a key.
  - Only Atlas's own model receives them, below its safety rules. They are never sent to Prometheus.
- **Regenerate:**
  - Replaces the last text reply in place (Ctrl/⌘+Shift+Enter), or tries again after a failed request.
  - A reply that used tools is never regenerated, so no action can repeat; "Ask again" is offered instead.
- **Copy conversation** as Markdown from the conversation menu.
- **Esc stops** a running reply.

### Fixed (Phase 7 acceptance testing; see `docs/phase7/`)
- **Critical:** sibling missions could read or change Prometheus's private files and memory.
  * The fix is in `sibling_adapter.py`: an allowlist of tools plus a per-mission workspace.
  * Update the adapter on the Prometheus side.
- A mission whose sibling became unreachable stayed "running". It is now paused with a reason, and its
  status is checked read-only on reconnect.
- Forge test runs could report stale results right after an edit (Python bytecode cache).
- Routing could pick a model its vendor has shut down. Prices now show each model's availability.
- On Windows, the adapter crashed with `--pair` when its output was redirected (code-page encoding).

## 0.2.0 — 2026-11-07

### Added
- **Atlas Forge:** engineering on a project folder you choose.
  - Explorer, session, file, diff, terminal, tests, git and changes panels.
  - Architect, Builder, Debugger and Reconstructor disciplines, each with its own tools.
  - Edits, writes, commands and commits are approved one at a time and show the real diff or argv.
  - Commands run without a shell, with a policy for model requests, time limits, process-tree kill and
    scrubbed credentials.
  - Every change is snapshotted and can be reverted while the file is unchanged.
- **Providers:** OpenRouter, Mistral and Cerebras, each with its own key placeholder.
- **Model routing:** Fast / Standard / Heavy tiers with Auto, Budget, Balanced, Quality and Manual modes.
- **Pricing:** a schedule that keeps verified rates, unverified seed rates and your own prices apart.
- **Budgets:** per request, mission, day and month, with a warning threshold and stop or ask-first.
- **Prometheus sibling link (Sibling Protocol v1):**
  - The minimal Prometheus-side adapter (`sibling_adapter.py`) listens on loopback only.
  - Pairing uses a one-time code and authenticated, replay-protected messages.
  - The secret is stored in the OS credential store.
  - Capabilities are discovered, not assumed.
  - Revocation and diagnostics are included.
- **Mission Ledger:** consultation, collaborative (default) and delegated missions, with a state machine
  enforced in the core, idempotent sending, honest restart recovery, and a visible collaboration timeline.
  The `sibling.consult` tool lets Atlas consult Prometheus, with approval.
- **Prometheus's solar avatar:** a WebGL2 port of his SolarSunWidget shader with unchanged shading code,
  shown in Siblings, Companion, Home, Mission Control and the Map. Atlas's own emblem and theme are unchanged.
- **Atlas Map:** Forge project, paired-sibling and mission nodes. The link edge is drawn only while a verified
  connection exists.
- Onboarding step for Forge, costs and siblings. Diagnostics for Forge, the sibling link and missions.
  `.env.example`, and an opt-in live provider check.

### Changed
- Tools the model was not offered in a conversation are refused before execution.
- Approval cards for Forge edits show a diff against the file as it is now.
- The rail adds Atlas Forge (Ctrl+4) and Siblings. Mission Control is now Ctrl+5, Projects Ctrl+6, Memory
  Ctrl+7, Files Ctrl+8 and Integrations Ctrl+9. Voice has no shortcut.
- Database schema v3 (migrations from v1 are automatic, with a backup made first).

### Fixed
- Accessible name of the rail's approval badge, and contrast of approval badges on the tinted card header.
- Tool names with underscores, such as `forge.edit_file`, now display correctly.

### Known limitations
- Live provider APIs were not called during development (no keys). Run the live check with your own keys.
- The OpenAI seed prices and model ids are unverified and labelled so.
- The sibling link is local only; remote transport is not implemented.
- The Prometheus side was tested with the adapter's test backend, not with Prometheus's own models.
- The avatar's star-birth intro is a short scale-in, not the original full intro.
- Installers are unsigned.

See `docs/TEST_REPORT.md` for exactly what was run.

## 0.1.0 — 2026-11-03

First release of ATLAS Co-Pilot.

### Added
- Trusted Rust core (`atlas-core`): Anthropic (Messages API 2026-10-21) and OpenAI-compatible streaming adapters
  (OpenAI, OpenRouter/Groq-style services, Ollama), capability-aware routing with no silent provider switching,
  OS-keyring credentials, SQLite storage with migrations, backup/restore with validation.
- Tool engine: schema-validated registry of 15 built-in tools; a single execution gate; permission policy
  (read-only / local-write / consequential / destructive); approvals bound to tool + argument hash and
  consumed once; timeouts, cancellation, output validation, verification of file writes.
- Bounded task state machine with Mission Control history; restart recovery marks unfinished tasks interrupted.
- Memory (FTS5, project-scoped, explained retrieval), projects with instructions, conversation search, exports.
- Desktop app (Tauri 2 + React 19): first-run wizard, Home, Companion with streaming and inline approvals,
  live Atlas Map, Mission Control, Projects, Memory, Files, Integrations, Voice (honest availability), Settings
  (12 sections), command palette, keyboard shortcuts, emergency stop, dark and light themes, reduced motion.
- Documentation, ADRs, and a CI workflow for Linux, Windows and macOS (checks, desktop e2e, installers).

### Verified for this release (Linux x86_64, Ubuntu 24.04)
- `cargo test --workspace`: 65 passed (48 core unit, 16 core end-to-end, 1 shell); plus 1 OS-keyring round-trip
  test run against GNOME Keyring (Secret Service).
- `pnpm typecheck`, `pnpm lint`: clean. `pnpm test` (Vitest): 15 passed.
- `tests/e2e/run.sh` (real desktop app over WebDriver): 11 passed, in two consecutive runs, including an axe-core
  audit of six pages with no violations.
- `pnpm tauri build --bundles deb,appimage`: produced `ATLAS Co-Pilot_0.1.0_amd64.deb` (9.6 MiB) and
  `.AppImage` (83.9 MiB); the `.deb` was installed with `dpkg` and launched.

### Windows (verified in CI on windows-latest, run 6)
- Unit, core and frontend tests; Windows Credential Manager round-trip; launch smoke test (app running after 15 s);
  desktop e2e 11/11 including the axe-core audit; NSIS `.exe` and `.msi` installers built.
- Windows hardening: portable file names (no device names such as `CON`/`NUL`), keys capped below the Credential
  Manager limit, embedded WebView2 bootstrapper, per-user install, title bar follows the app theme.

### Known limitations
- Live provider APIs were not exercised in development (no keys available); adapters are tested against mock
  servers replaying each API's wire format.
- macOS builds and unit tests pass in CI but the app has not been run interactively there. Installers are unsigned.
- No PDF/Office parsing, no speech-to-text, no auto-update; external integrations other than web search are planned.
