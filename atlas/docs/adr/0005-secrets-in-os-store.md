# ADR 0005 — Secrets only in the OS credential store

**Decision.** Use `keyring` 4 (Keychain, Windows Credential Manager, Secret Service). Store only a masked hint in
SQLite. No plaintext fallback.

**Why.** Keys must never appear in the database, logs, exports, prompts or the webview. **Consequences.** On Linux a
Secret Service provider must be running; if not, Atlas says so rather than storing keys insecurely.
