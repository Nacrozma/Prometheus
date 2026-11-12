# Platform abstractions

Shared code talks only to `app/platform/base.py::Platform`. Adapters live beside it; `current()` picks one.

| Method | Windows (`windows.py`) | macOS (`macos.py`) | Linux (`linux.py`) |
|---|---|---|---|
| `data_dir()` | `%APPDATA%\Prometheus` | `~/Library/Application Support/Prometheus` | `$XDG_DATA_HOME/prometheus` (`~/.local/share/prometheus`) |
| `default_workspace()` | `~/Documents/Prometheus Workspace` | same | `~/Prometheus Workspace` |
| `credential_backend()` | Windows Credential Manager | macOS Keychain | Secret Service (GNOME Keyring / KWallet) |
| `launch_at_login()` / `set_launch_at_login()` | `HKCU\…\Run` value `Prometheus` | `~/Library/LaunchAgents/…plist` | `~/.config/autostart/prometheus.desktop` |
| `capabilities()` | tray, notifications, launch at login | same | same (tray depends on the desktop) |
| `validated` | build, install, upgrade and uninstall verified on a Windows CI VM; not yet on a physical PC | **not validated** | runs in CI/xvfb only |

Cross-platform by construction (no adapter needed): single instance (`QLocalServer`, a named pipe on
Windows), tray and notifications (`QSystemTrayIcon`), credential access (`keyring`), file dialogs.

Not implemented on any platform yet: a **global shortcut** (`capabilities()["global_shortcut"]` is
False and Settings does not offer one; see KNOWN_LIMITATIONS).

Adding a platform: subclass `Platform`, implement the five abstract methods, set `name`/`validated`,
add a branch in `current()`, and add a row here.
