# Release and packaging

## Build

```bash
cd atlas
pnpm install
pnpm tauri build                       # all bundle formats for the current OS
pnpm tauri build --bundles deb,appimage  # Linux
```

Artifacts land in `target/release/bundle/<format>/`.

| Platform | Formats | Status |
|---|---|---|
| Linux x86_64 | `.deb`, `.AppImage` | Built in this environment (see CHANGELOG for results) |
| Windows x64 | `.msi`, NSIS `.exe` | Configured, **not yet built** — use the CI workflow or build on Windows |
| macOS (Apple silicon / Intel) | `.app`, `.dmg` | Configured, **not yet built** — build on macOS |

`.github/workflows/atlas.yml` runs checks and unsigned builds on all three; it has not been executed yet.

## Signing (required for a smooth install, not yet done)

* **macOS:** an Apple Developer ID Application certificate and notarization credentials
  (`APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD`, `APPLE_SIGNING_IDENTITY`, `APPLE_ID`, `APPLE_PASSWORD`,
  `APPLE_TEAM_ID`). Unsigned builds require right-click → Open the first time.
* **Windows:** an Authenticode code-signing certificate (OV/EV) configured via `bundle.windows.certificateThumbprint`
  or a signing command. Unsigned installers trigger SmartScreen warnings.
* **Linux:** optional; distribute checksums alongside packages.

No API keys are ever embedded in a build: keys are entered at runtime and stored in the OS credential store.

## Versioning

Bump `version` in `package.json`, `src-tauri/tauri.conf.json` and `Cargo.toml` (`workspace.package`) together,
and add a CHANGELOG entry.

## Updates

This version has **no auto-updater**. Users install a newer package over the old one; the data folder (database,
settings) is kept and migrated on first start (a snapshot is written before migrating). A future version can add
`tauri-plugin-updater` with a signed update manifest — that requires an update signing keypair and a hosting
location for the manifest.

## Release checklist

1. `pnpm check` (typecheck, lint, unit tests, Rust tests) and `tests/e2e/run.sh` pass.
2. Bump versions, update CHANGELOG.
3. Build on each target OS; install and smoke-test (first-run, a conversation with a real provider, one approval).
4. Sign/notarize where credentials exist; otherwise label builds unsigned.
5. Publish artifacts with SHA-256 checksums.
