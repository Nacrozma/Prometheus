# Changelog

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
- Documentation, ADRs, CI workflow for Linux/Windows/macOS (not yet executed).

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
