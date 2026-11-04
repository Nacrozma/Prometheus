#!/usr/bin/env bash
# Started by run.sh: launch tauri-driver and run the suite.
set -euo pipefail
ARGS=(--port 4444)
if [[ -n "${MSEDGEDRIVER:-}" ]]; then ARGS+=(--native-driver "$MSEDGEDRIVER"); fi
tauri-driver "${ARGS[@]}" > "$WORK/driver.log" 2>&1 &
DRIVER=$!
trap 'kill $DRIVER 2>/dev/null || true; cat "$WORK/driver.log" | tail -20 >&2 || true' EXIT
sleep 3
node --test --test-concurrency=1 tests/e2e/app.e2e.mjs
