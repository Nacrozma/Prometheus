# Next session: handover

## Where things are
* Branch `claude/prometheus-ai-evaluation-pxqzfr` (pushed). The desktop app is in `app/`; packaging in
  `packaging/`; CI in `.github/workflows/prometheus-desktop.yml`; docs and screenshots here.
* Run it from source: `pip install -r requirements.txt` (Whisper optional), then `python -m app`.
  Headless check: `python -m app.launcher --self-test=report.json` (set `PROMETHEUS_HOME` and
  `PROMETHEUS_WORKSPACE` to throwaway folders when testing, or it uses your real data).
* Tests: `python -m pytest tests -q` (466 passed, 2 skipped on Linux; also green on Windows CI).
* Atlas (`atlas/`) was not touched. Its parked Stage 3 UI work is on `claude/atlas-0.5-command-center-wip`.

## What was built (0.1.0)
Core: data folder and workspace settable by environment (defaults unchanged), router that can
start unconfigured and reload. Desktop: shell, 11 sections, tray, palette, single instance, OS
credential store, data import, packaged-app child-Python mode, self-test, Windows installer with
verified install/upgrade/uninstall on a CI VM.

## Needs the owner (cannot be done from here)
1. **Try it on a real Windows PC** (RELEASE_CHECKLIST gate 11): download the CI artifact, check the
   SHA-256, install, add a key, have a conversation, approve and deny a tool, try the tray, a
   reminder notification, Reduce motion, Start when I sign in, and voice output. Report anything odd.
2. **Decide on code signing** (a certificate is needed) and whether to publish a release.
3. Cancel workflow run #2 of `prometheus-desktop` if it is still running (it hung on a bug that is
   now fixed; it started before the auto-cancel setting existed).

## Suggested next work
* Global shortcut on Windows (`RegisterHotKey`) with conflict detection; Settings entry.
* Orb at 30 fps when the window is unfocused; measure CPU on a real GPU.
* A Sessions list (resume earlier conversations) in the Companion; the core already stores sessions.
* macOS build (see CROSS_PLATFORM_ROADMAP).
