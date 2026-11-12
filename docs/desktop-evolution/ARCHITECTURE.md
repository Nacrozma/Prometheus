# Prometheus desktop: architecture

## Decisions

| Decision | Choice | Why |
|---|---|---|
| UI toolkit | **Keep PyQt6** (+ the existing OpenGL orb) | Already used; native on Windows/macOS/Linux; no second runtime |
| Core | **Unchanged Python core** (`prometheus.py` and modules), called in-process | One source of truth; the terminal keeps working |
| Changes to the core | Minimal, backward compatible: data folder and workspace folder can be set by environment; the router can start unconfigured and be rebuilt | Needed so an installed app can open without a key and write somewhere it may |
| New code | `app/` package: bootstrap, platform adapters, services, UI shell | Keeps GUI code out of the core |
| Data folder | `PROMETHEUS_HOME`, else the source folder (developer installs keep working). The desktop app sets it to the platform's per-user folder (Windows: `%APPDATA%\Prometheus`) | Separates code from data |
| Workspace | `PROMETHEUS_WORKSPACE`, else the source folder (unchanged for terminal users). The desktop app uses a folder the owner picks | Installed code is read-only |
| Self-modification patches | Available only when running from a source checkout. In the packaged app the Forge says why it is unavailable | Patching bundled code would break the install |
| Credentials | OS credential store through `keyring` (Windows Credential Manager first). Loaded into the process environment at start; `.env` still honoured | Keys never in settings files or logs |
| Voice | Optional. Whisper (PyTorch) is not bundled; the app runs without it and says how to enable it | Keeps the installer small and the app launchable |
| Packaging | PyInstaller (one-folder) + Inno Setup, built on a Windows CI runner | Mature with PyQt6; Inno Setup gives a normal installer/uninstaller |

## Layers

```
app/bootstrap.py      paths, credentials → environment, single instance, logging, then the window
app/platform/         base contract + windows / macos / linux adapters (data dirs, startup, shortcuts)
app/services/         thin wrappers over the core (assistant, memory, tasks, forge, ...)
app/ui/               main window, pages, components, theme
prometheus.py & co.   the existing core, unchanged in behaviour
```

The UI never calls tools directly: everything that changes state goes through `dispatch_tool`, so the
existing permission checks, audit log and undo journal apply exactly as in the terminal.
