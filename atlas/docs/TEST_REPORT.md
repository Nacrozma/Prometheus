# Test report: ATLAS Co-Pilot 0.2.0

Run on Linux x86_64 (Ubuntu 24.04 container) on 2026-11-07. The CI results for Windows and macOS are listed in
the GitHub Actions run for this commit.

## Results

| Suite | Command | Result |
|---|---|---|
| Rust core, unit | `cargo test --workspace` | 80 passed, 1 ignored (OS-keyring round-trip; runs in CI on Windows) |
| Rust core, engine end-to-end | (same) | 20 passed |
| Rust, Atlas ↔ real Prometheus adapter | `cargo test -p atlas-core --test sibling_bridge` | 2 passed (spawns `sibling_adapter.py --test-backend`) |
| Rust, desktop shell | (same) | 1 passed |
| Live provider check | `cargo test -p atlas-core --test live_providers -- --ignored` | **Not run**: no provider keys available. Ignored by default. |
| Frontend | `pnpm typecheck`, `pnpm lint`, `pnpm test` | clean, clean, 19 passed |
| Desktop end-to-end (real app over WebDriver) | `tests/e2e/run.sh` | 13/13 passed, including the axe-core audit of 8 pages |
| Prometheus adapter | `python -m unittest tests.test_sibling_adapter` | 12 passed |
| Prometheus, existing suite | `pytest tests` (excluding 2 modules that need provider keys at import) | 363 passed, 36 skipped (baseline before this work: 351 passed) |
| Avatar shader in real WebGL2 | `node tests/visual/avatar-webgl.mjs` | compiled and linked; core pixel gold for idle, thinking and speaking, cobalt for adapting |

## Acceptance coverage

### Atlas independence

* Every Atlas suite runs with no sibling.
* The e2e test checks the unpaired Siblings page shows an offline avatar and nothing marked connected.
* `atlas_keeps_working_when_the_sibling_goes_away`: when the adapter is killed, Atlas shows "not connected"
  with the reason, the map drops the link edge, and sync tolerates the outage.

### Prometheus independence

* `prometheus.py`, `gui_orb.py` and every other existing Prometheus file are unmodified. The only changes on
  that side are two new files: `sibling_adapter.py` and `tests/test_sibling_adapter.py`.
* Prometheus's existing tests pass.

### Sibling connection

* Pairing works with the right code.
* A wrong code is refused and nothing is stored.
* The code is single use, and is invalidated after 5 wrong attempts.
* The adapter must prove it knows the code.
* A wrong secret, a stale timestamp, a replayed nonce and a tampered payload are each refused with 401.
* Browser-style requests (no protocol header) and foreign Host headers are refused.
* A revoked sibling is refused on both sides.
* Capabilities are discovered from the peer, and its dangerous tools are flagged.
* Known-answer vectors match between Python and Rust.

### Collaboration

* Consultation through the ledger.
* Collaborative round trip: Atlas messages, Prometheus replies, owner acceptance.
* Delegated mission, where Prometheus's own refusal of a dangerous tool is visible.
* A re-send after a lost reply is not started twice.
* Cancellation.
* A mission cannot be sent before planning and approval, or to an unpaired sibling.

### Mission ledger

* Illegal transitions are refused, and terminal states are final.
* Every transition is logged.
* Re-delivered events are stored once.
* A remote "completed" result goes to REVIEWING, never straight to COMPLETED.
* Restart recovery never re-sends.

### Forge

* Each discipline is offered only its own tools. A tool that was not offered is refused before dispatch.
* Edits need approval, and the approval card shows the real diff with context.
* A declined edit changes nothing.
* Revert restores the original exactly. It refuses when the file changed since, and refuses to undo changes
  out of order.
* Confinement: `..`, absolute paths, symlinks and `.git` are refused.
* The model command policy refuses shells, inline code, deletion, network clients and publishing.
* Commands are timed out and the process tree is killed.
* Credential-looking environment variables are removed.
* git round trip against a real repository.
* e2e: explorer → approved edit → revertible change → terminal command.

### Routing, pricing and budgets

* Tier selection is tested for each mode.
* Unusable tiers step down with a stated reason.
* An explicit conversation choice wins.
* The seed rates are present and marked unverified.
* The verified/seed conflict check is in place.
* Owner overrides win.
* Budgets: warn, ask and stop. The per-request limit uses the worst case. Mission budgets count only that
  mission. An unknown price is surfaced. The daily request limit always stops.
* The engine refuses before anything is sent or stored.

### Security

* Tests for path traversal, unapproved writes, approval replay, out-of-scope tools, sibling replay and
  tampering, revocation and secret storage are listed above.
* Secrets never appear in SQLite: provider keys and sibling secrets are tested to live only in the
  credential store.

## Not verified

* Live calls to OpenAI, Anthropic, OpenRouter, Mistral, Cerebras or Ollama. The adapters are tested against
  recorded wire formats. Run the live check with your own keys.
* The seed prices for OpenAI models, and their model ids, against OpenAI's current pricing page. They are
  labelled unverified in the app.
* A pairing against the real `PrometheusBackend` with provider keys. The protocol, adapter and Atlas side are
  exercised end to end with the adapter's test backend, but importing `prometheus.py` needs Prometheus's own
  keys, which are not available here.
* Remote (non-loopback) sibling transport, which is not implemented.
