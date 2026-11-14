# Test status

| Date | Commit | Rust | Frontend | Python | End-to-end | CI | Install/upgrade |
|---|---|---|---|---|---|---|---|
| 2026-11-14 | 0.5.0 stage 5 (unreleased) | 209 pass | 82 pass | not run | 26 of 26 (25 + restart 1) | on push | Schema 1–6 → 7 tested |
| 2026-11-14 | 0.5.0 stage 4 (unreleased) | 184 pass | 75 pass | not run | 25 of 25 (24 + restart 1) | on push | Schema 1–5 → 6 tested |
| 2026-11-11 | 2d6697d (0.4.2) | 143 pass | 61 pass | 409 pass | 19 of 19 | 5 of 5 green | Pass from 0.4.1 and 0.3.0 |

**Run locally:** `cargo test --workspace -j 3`, `pnpm typecheck && pnpm lint && pnpm test`,
`SKIP_BUILD=1 bash tests/e2e/run.sh` (after `pnpm tauri build --debug --no-bundle --features e2e`;
runs the main suite, then the restart phase). Production check: `tests/release/no-test-hooks.sh <binary>`.
Use `CARGO_INCREMENTAL=0` and `-j 3`: the build machine restarts under heavier load.
