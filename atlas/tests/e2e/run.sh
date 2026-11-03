#!/usr/bin/env bash
# Build the e2e desktop binary and run the WebDriver suite against it.
# Requires: tauri-driver (cargo install tauri-driver), WebKitWebDriver, Xvfb (Linux).
set -euo pipefail
cd "$(dirname "$0")/../.."
if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
  pnpm tauri build --debug --no-bundle --features e2e
fi
WORK=$(mktemp -d)
export HOME="$WORK/home" ATLAS_DATA_DIR="$WORK/data"
mkdir -p "$HOME/Documents"
trap 'rm -rf "$WORK"' EXIT
export WORK
if [[ -z "${DISPLAY:-}" ]]; then
  xvfb-run -a -s "-screen 0 1440x920x24" tests/e2e/inner.sh
else
  tests/e2e/inner.sh
fi
