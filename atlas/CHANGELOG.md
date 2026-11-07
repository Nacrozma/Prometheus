# Changelog

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
