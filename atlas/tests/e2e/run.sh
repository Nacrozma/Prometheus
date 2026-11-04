#!/usr/bin/env bash
# Build the e2e desktop binary and run the WebDriver suite against it.
# Linux: needs tauri-driver, WebKitWebDriver and Xvfb.
# Windows (Git Bash): needs tauri-driver and msedgedriver.exe matching the WebView2 runtime, given in $MSEDGEDRIVER.
set -euo pipefail
cd "$(dirname "$0")/../.."
if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
  pnpm tauri build --debug --no-bundle --features e2e
fi
WORK=$(mktemp -d)
export WORK ATLAS_DATA_DIR="$WORK/data"
trap 'rm -rf "$WORK"' EXIT
case "$(uname -s)" in
  Linux)
    # Isolate the Documents/home folder the app uses for its default workspace.
    export HOME="$WORK/home"; mkdir -p "$HOME/Documents"
    if [[ -z "${DISPLAY:-}" ]]; then
      exec xvfb-run -a -s "-screen 0 1440x920x24" tests/e2e/inner.sh
    fi
    ;;
esac
tests/e2e/inner.sh
