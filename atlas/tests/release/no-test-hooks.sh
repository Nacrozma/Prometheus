#!/usr/bin/env bash
# Production/test separation, checked on the compiled app (not the source): the test-only commands
# and helpers of the automated-test build must not be in a production binary. A normal command name
# is checked as a control, so an unreadable or stripped binary cannot pass by accident.
#   tests/release/no-test-hooks.sh <binary> [--expect-test-build]
set -euo pipefail
BIN="${1:?usage: no-test-hooks.sh <binary> [--expect-test-build]}"
EXPECT_TEST="${2:-}"
[[ -f "$BIN" ]] || { echo "no such binary: $BIN" >&2; exit 2; }
has() { LC_ALL=C grep -a -c -F -- "$1" "$BIN" >/dev/null 2>&1; }
has "recap_get" || { echo "FAIL: control string 'recap_get' not found; cannot judge $BIN" >&2; exit 2; }
HOOKS=(e2e_recap_since e2e_vault_allow shift_back_for_test e2e-away-minutes recap_begin_minutes_ago)
found=()
for h in "${HOOKS[@]}"; do if has "$h"; then found+=("$h"); fi; done
if [[ "$EXPECT_TEST" == "--expect-test-build" ]]; then
  [[ ${#found[@]} -gt 0 ]] || { echo "FAIL: test build has none of the test hooks (the check would not detect them)" >&2; exit 1; }
  echo "ok: test build contains test hooks: ${found[*]}"
  exit 0
fi
if [[ ${#found[@]} -gt 0 ]]; then
  echo "FAIL: production binary contains test-only hooks: ${found[*]}" >&2
  exit 1
fi
echo "ok: no test-only hooks in $BIN (control string present)"
