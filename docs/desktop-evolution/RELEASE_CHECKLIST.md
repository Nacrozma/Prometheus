# Release checklist: Prometheus Desktop

A release is published **only with the owner's explicit approval**. CI builds an installer artifact;
it never creates a GitHub release.

## Gates (0.1.0 status)
| # | Gate | Status |
|---|---|---|
| 1 | Full test suite passes on Linux | ✅ 466 passed, 2 skipped (this environment) |
| 2 | Full test suite passes on Windows | ✅ `tests-windows` job (see the run linked in NEXT_SESSION) |
| 3 | PyInstaller build; no personal state or keys in the bundle | ✅ CI check |
| 4 | Packaged app self-test (all pages, gated tools, a real calculation) | ✅ CI + local Linux frozen build |
| 5 | Packaged child-Python mode (run_code / Forge tests) | ✅ CI + local |
| 6 | Silent per-user install; data in `%APPDATA%`; nothing written to the program folder | ✅ CI (Windows VM) |
| 7 | Upgrade over an older build keeps user data; one uninstall entry with the new version | ✅ CI (Windows VM) |
| 8 | Uninstall removes the program, keeps data | ✅ CI (Windows VM) |
| 9 | Installer size and SHA-256 recorded | ✅ build-report.txt in the artifact (values below) |
| 10 | Screenshots of every section | ✅ `screenshots/01–15` (Linux, software OpenGL) |
| 11 | Manual check on a physical Windows PC: window, orb on a GPU, tray, notification, start at sign-in, a real conversation with a provider key, approval card, voice output | ❌ **not done**: needs the owner |
| 12 | Code signing | ❌ not available (installer is named `-unsigned`) |
| 13 | Owner approval to publish | ❌ not given |

## Build record
| | |
|---|---|
| Version | 0.1.0 |
| Installer | `Prometheus-Setup-0.1.0-x64-unsigned.exe` |
| Size | INSTALLER_SIZE |
| SHA-256 | INSTALLER_SHA |
| Installed folder | INSTALLED_SIZE |
| Built by | workflow run CI_RUN |

## To publish (after gates 11–13)
1. Bump `app/__init__.py:__version__` and `APP_VERSION` in the workflow; push; wait for green.
2. Download the artifact; check the SHA-256.
3. With the owner's approval: create a GitHub release `prometheus-desktop-vX.Y.Z`, attach the
   installer and `SHA256SUMS.txt`, state "unsigned" and link KNOWN_LIMITATIONS.
4. Update the download link in WINDOWS_INSTALLATION.md.
