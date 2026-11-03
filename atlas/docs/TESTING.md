# Testing

| Suite | Command | What it covers |
|---|---|---|
| Rust core unit | `cargo test -p atlas-core --lib` | migrations (incl. rollback, newer-schema refusal), backup/restore validation, settings validation, redaction, SSE parsing (split chunks, CRLF, UTF-8), Anthropic and OpenAI adapters against wiremock (streaming, tool calls, refusal, auth errors, invalid tool JSON, cancellation, model listing), routing (no silent switching, offline mode), path confinement (traversal, absolute, symlink escapes, no overwrite), policy matrix, action-hash canonicalisation, task transitions, restart recovery, memory search/scoping/deletion, calculator, CSV/JSON |
| Rust core end-to-end | `cargo test -p atlas-core --test engine` | full turns through the real orchestrator with a scripted provider: streaming + persistence, read-only tool loop with verification, approval → execution, rejection, **consequential action requires an action-specific single-use approval**, destructive denial, invalid input/output, timeouts, cancellation, emergency stop, provider auth errors, bounded retries, memory relevance + project isolation, credentials never reaching the model/exports/diagnostics, map/registry synchronisation, interrupted-task recovery, web search with injected text |
| Desktop shell | `cargo test -p atlas-desktop` | navigation guard |
| Frontend | `pnpm test` | map layout (no overlaps, determinism), turn reducer, safe Markdown (no raw HTML, no `javascript:` links, no remote images), IPC schema validation, approval card |
| Desktop end-to-end | `tests/e2e/run.sh` | the real app over WebDriver (tauri-driver + WebKitWebDriver, Xvfb): onboarding, first conversation, read-only tool, approve, decline, stop, Mission Control, Atlas Map + inspector, memory CRUD, integrations states, theme switching |

Deterministic test doubles (`ai::mock`, `tools::builtin::test_tools`, the `e2e` feature's scripted provider) need no
API keys and incur no cost. They are compiled only for tests or the `e2e` feature.

`ATLAS_SCREENSHOTS=docs/screenshots tests/e2e/run.sh` regenerates the screenshots in the README.

Accessibility: the e2e suite injects axe-core into the real webview on Home, Companion, Mission Control, Memory,
Integrations and Settings and fails on serious or critical violations. Muted-text and light-theme status colors were
chosen from computed contrast ratios (≥ 4.5:1 on every surface).

OS credential store: `cargo test -p atlas-core os_keyring -- --ignored` (needs a running Secret Service on Linux,
Keychain on macOS, Credential Manager on Windows).

## Results for this release

See CHANGELOG.md for the counts recorded at release time.
