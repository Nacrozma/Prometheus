#!/usr/bin/env bash
# Started by run.sh: launch tauri-driver and run the suite.
set -euo pipefail
ARGS=(--port 4444)
if [[ -n "${MSEDGEDRIVER:-}" ]]; then ARGS+=(--native-driver "$MSEDGEDRIVER"); fi
# Stand-in voice downloads, served on loopback only, for the app's real download/verify path.
PY=""
for c in python3 python; do if "$c" --version >/dev/null 2>&1; then PY=$c; break; fi; done
[[ -n "$PY" ]] || { echo "Python is needed to serve the voice test files" >&2; exit 1; }
VOICE_PORT=47631
export ATLAS_E2E_VOICE_DIR="$WORK/voice-fixtures"
"$PY" tests/e2e/make_voice_fixtures.py "$ATLAS_E2E_VOICE_DIR" "$VOICE_PORT" > "$WORK/voice-fixtures.json"
export ATLAS_E2E_VOICE_FIXTURES="$WORK/voice-fixtures.json"
"$PY" -m http.server "$VOICE_PORT" --bind 127.0.0.1 --directory "$ATLAS_E2E_VOICE_DIR" > "$WORK/voice-http.log" 2>&1 &
HTTP=$!
tauri-driver "${ARGS[@]}" > "$WORK/driver.log" 2>&1 &
DRIVER=$!
trap 'kill $DRIVER $HTTP 2>/dev/null || true; echo "--- tauri-driver log (tail) ---"; tail -40 "$WORK/driver.log" || true' EXIT
sleep 3
node --test --test-concurrency=1 tests/e2e/app.e2e.mjs
# Restart phase: the same app relaunched on the same data folder (see restart.e2e.mjs).
node --test --test-concurrency=1 tests/e2e/restart.e2e.mjs
