# Security review: Prometheus Desktop 0.1

Scope: everything added under `app/`, the packaging, and the small core changes. The core's own
safety model (policy, audit chain, undo journal, patch gate, Forge sandbox) is unchanged and was
reviewed before this work (README → Autonomy guard rails).

## Findings and how they are handled

| Area | Risk | Handling | Evidence |
|---|---|---|---|
| Tool approvals | The GUI becoming a way round the backend's checks | The UI never runs tools itself: everything goes through `dispatch_tool` (policy → audit → undo). The Companion uses the HUD's worker, whose `_confirm_tool` asks for every tool in `DANGEROUS_TOOLS`. Deny is the default button; Stop/Esc denies a pending card | `TestWindowSmoke` raises a `write_file` card and checks that a denial reaches the worker; self-test checks `write_file`, `execute_shell`, `run_code_forge`, `apply_pending_patch` are gated |
| Approval scope | Approval reused for a changed action | Each tool call is approved separately, with its exact arguments shown; nothing is remembered between calls | code: `ApprovalCard`, `PrometheusWorker._confirm_tool` |
| Auto-approve | Silent enabling | Off by default (type-checked setting, a non-bool in the file falls back to off); turning it on needs a warning dialog with **No** as default; status bar shows **AUTO-APPROVE ON**; Trust page says so. Denied tools stay denied | `TestSettings`, UI |
| Global stop | No way to halt | Stop button, Esc, tray "Stop current request", palette | UI |
| Model output as HTML | Injection into the transcript | Transcript uses `gui_markdown.render_markdown`, which escapes before formatting (existing, tested); every label is `Qt.TextFormat.PlainText`; approval arguments shown in a plain-text box | `label()`, existing `test_gui_markdown` |
| Keys | Leaking into files, logs, errors | Stored only via `keyring` (Windows Credential Manager); the settings file rejects unknown keys; errors name the provider, never the value; status shows a 4+4-character hint at most; no fallback to a plain file (Settings says so if the store is unavailable). `.env` still works and wins | `TestCredentials` (incl. an exploding backend whose message contains the key) |
| Installer contents | Bundling the developer's data or keys | The spec lists source modules and two reference files only; CI fails the build if `.env`, memory, audit, session, config or settings files appear in the bundle | workflow step "Build the app" |
| Program folder writes | State written next to the exe | Packaged app ignores its install folder for data (`bootstrap` frozen rule); CI fails if `prometheus.log` appears in the program folder | workflow, `TestPaths` |
| Workspace confinement | Tools reaching the whole disk | Workspace tools confined to `WORKSPACE_DIR`; Settings refuses the home folder or a drive root; Workspace preview refuses `.env`, binaries and paths outside the root | `test_desktop_core`, existing `test_safety` |
| Child-Python mode | Packaged exe as an interpreter (`-I script`, `-m module`) | Needed so `run_code`/Forge tests work when frozen. Runs only a file the local user names, as any Python would; no new capability. `run_code_forge` itself still needs approval | `TestChildPython`, CI child test |
| Single instance | Another user's process talking to the pipe | `QLocalServer.UserAccessOption`; the only message is "come forward" | `TestSingleInstance` |
| Data import | Losing or corrupting data | Source read-only; backup + SHA-256 verify + per-file atomic replace + rollback; runs before the core loads; never copies `.env` | `TestImport` |
| Robot arm | Simulation presented as hardware | Page is simulation-only, labelled on screen; no serial/hardware controls exist in the app | UI, screenshot 08 |
| Voice | Recording without consent | Microphone records only while Talk is switched on; audio transcribed in memory, never saved; edge-tts sends spoken text to Microsoft (stated in Settings) | Settings → Voice |
| Crash logs | Secrets in tracebacks | `desktop_crash.log` contains Python tracebacks; keys are not passed as arguments in app code, but a third-party library could include request details. Logs stay local in the data folder | KNOWN_LIMITATIONS |
| Code signing | Tampered installer | **Not signed.** Named `…-unsigned.exe`; SHA-256 published next to it in the CI artifact; SmartScreen will warn | RELEASE_CHECKLIST |

## Not changed (and therefore still true)
The core's documented limits stand: the destructive-command filter is not a sandbox; Forge skills are
strongly isolated only with Docker; undo covers the workspace file tools only; the audit chain detects
edits but cannot stop someone with full file access replacing it. The Trust page shows these.
