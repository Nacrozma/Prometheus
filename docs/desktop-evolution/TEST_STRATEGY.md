# Test strategy

| Layer | Where | What | Runs |
|---|---|---|---|
| Core (existing) | `tests/test_*.py` (safety, memory graph, Forge, patch gate, engineering, arm, reflection, Obsidian, GUI HUD…) | Behaviour of the unchanged core | Linux (this environment), **Windows CI** (`tests-windows` job) |
| Core changes | `tests/test_desktop_core.py` | Defaults unchanged; state in `PROMETHEUS_HOME`; tools confined to `PROMETHEUS_WORKSPACE`; router reload; unconfigured router | Linux, Windows |
| Desktop layer | `tests/test_desktop_app.py` | Path rules, credentials (fake keyring, no key echo), settings types/quarantine, single instance, data import (backup, verify, rollback, source untouched), child-Python mode, launcher run as a script, offscreen window smoke test of all 11 pages + approval gating | Linux, Windows |
| Packaged app | `.github/workflows/prometheus-desktop.yml` | PyInstaller build; no personal state in bundle; `--self-test` of the folder build; child-Python mode; silent install; installed self-test; data folder in `%APPDATA%`; upgrade over an older build with data kept and one uninstall entry; uninstall removes program, keeps data; size + SHA-256 | Windows VM (GitHub-hosted) |
| Visual | `docs/desktop-evolution/screenshots/` | Real screenshots of the running app (Xvfb, software OpenGL) | manual, this environment |

Isolation: every test that starts the app uses throwaway `PROMETHEUS_HOME`/`PROMETHEUS_WORKSPACE`
folders, in a subprocess, so the developer's real memory and sessions are never touched.

Not automated: real microphone/speaker, real tray clicks on a desktop, multi-monitor/DPI, a physical
Windows PC (see KNOWN_LIMITATIONS).
