#!/usr/bin/env bash
# Started by run.sh (inside a display): launch tauri-driver and run the suite.
set -euo pipefail
tauri-driver --port 4444 > "$WORK/driver.log" 2>&1 &
DRIVER=$!
trap 'kill $DRIVER 2>/dev/null || true' EXIT
sleep 2
node --test --test-concurrency=1 tests/e2e/app.e2e.mjs
