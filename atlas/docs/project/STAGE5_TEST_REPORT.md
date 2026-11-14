# Stage 5 test report: the Knowledge Vault

**Date:** 2026-11-14 · **Branch:** `claude/prometheus-ai-evaluation-pxqzfr` · **Platform:** Linux x86_64
container (Xvfb, WebKitWebDriver). Windows and macOS: CI on push, not run here. **Not released.**
Design and behaviour: `docs/KNOWLEDGE_VAULT.md`.

## Results

| Suite | Command | Result |
|---|---|---|
| Rust core, unit | `cargo test -p atlas-core` (lib) | 122 passed, 1 ignored (OS keyring; Windows CI). Vault: 12 (extraction 5, chunking 3, query quoting, delimiter neutralizing, citation checks and local-only 4) |
| Rust core, integration | (same, `tests/*.rs`) | 85 passed, **vault 13**, briefing 3, engine 31, focus 8, scheduler 8, sibling bridge 6, todos 7, voice 9 |
| Rust core, ignored by design | (same) | 5: live providers 2, real Prometheus runtime 1, real voice engines 1, opt-in fixture check 1 (`ATLAS_VAULT_FIXTURES`, run by hand: all e2e fixtures read as expected) |
| Rust desktop shell | `cargo test -p atlas-desktop` | 2 passed |
| Clippy `-D warnings` | core and shell, all targets, with and without `--features e2e` | clean |
| Frontend | `pnpm typecheck`, `pnpm lint`, `vitest run` | clean, clean, **82 passed** (16 files; 75 before, + 7 Vault and citation tests) |
| End-to-end, main phase | `tests/e2e/run.sh` → `app.e2e.mjs` | **25 of 25** (24 before + the Knowledge Vault test; the accessibility audit now includes the Vault page) |
| End-to-end, restart phase | `restart.e2e.mjs` | **1 of 1** (now also checks the Vault and stored citations after relaunch) |
| Production/test separation | `tests/release/no-test-hooks.sh` | production debug binary: none of the 5 test hooks (incl. new `e2e_vault_allow`); e2e binary: all 5 |

Totals: Rust 209 passed, 0 failed. Frontend 82. End-to-end 26 of 26. All runs on the final code except
one change after the end-to-end run: singular/plural wording in the Vault page (unit tests rerun, 82/82).

## Automated, simulated, not validated

* **Automated, real code:** extraction of real files in all four formats (built by the Rust tests with
  `lopdf`/`zip`, and by `tests/e2e/make_vault_fixtures.py` for the app), SQLite FTS5, the worker thread,
  the engine and its prompts, the UI in the real webview.
* **Simulated:** the model (scripted: answers from the first passage it is given and cites it; it never
  follows passage text); the native file picker in e2e (the test build allows fixture paths; the
  production build has no such hook, checked on the binary).
* **Not validated end-to-end:** the "held back under local-only" path, because the e2e and core-test
  models count as local. It is covered by `passages_allowed` unit tests, the tool's refusal test with a
  non-local context, and the engine code path shared with them. Real cloud providers, Windows and macOS,
  very large real-world PDFs.

## Acceptance criteria (directive §19)

| # | Criterion | Evidence |
|---|---|---|
| 1–4 | TXT, Markdown, PDF, DOCX import | `all_four_formats_are_extracted…`, e2e |
| 5 | Asynchronous processing | worker thread; e2e waits for statuses; `processing_left_unfinished_is_resumed…` |
| 6–7 | Indexing, search | FTS rows = passages; phrase/keyword/title/type/document search; e2e search |
| 8 | Project scope enforced | `project_scope_is_enforced_by_the_core`; e2e (project document unused until moved) |
| 9 | Local-only as documented | unit + tool tests (see above) |
| 10–11 | Answers from passages, real locations | `a_question_gets_the_right_passages…` (page 2); e2e citation opens page 2 |
| 12 | Unsupported claims handled | unknown markers flagged (core + UI tests); prompt rules; no passages for unrelated questions |
| 13 | Removal cleans the index | `a_changed_original…removal_cleans_up`; e2e |
| 14 | Re-index without duplication | same test (twice), e2e |
| 15 | Prompt injection | all four formats (`injected_instructions…`), obedient model still needs approval, e2e memo |
| 16–17 | v7 from v6, data kept | `upgrading_a_v6_database…`, `every_earlier_schema_upgrades…` |
| 18–21 | Frontend, Rust, e2e, regressions | tables above (Stage 1–4 e2e tests all pass) |
| 22–23 | Docs, limitations | `docs/KNOWLEDGE_VAULT.md` §10 |

## Defects found during this stage

| Defect | Fix | Regression test |
|---|---|---|
| PDF lines positioned with `Td`/`Tm` ran together ("staffingThe"), making words unsearchable (lopdf breaks lines only at `T*`/`ET`) | `T*` added before each vertical move before extraction | format test: "report introduction" |
| e2e scripted model matched intents against passage text, so a document saying "create a note" changed its behaviour | intents use the question only; passages answered last | restart setup test passes |
| Reader scroll called `scrollIntoView` unguarded | optional call | Vault unit test |

## Performance (measured, debug build)

683 KB of text → 600 passages, imported and indexed in 141 ms; one search over them 16 ms
(`text_in_other_encodings_and_large_documents`, printed with `--nocapture`). Memory was not profiled.

## Connectors

Parallel Search: compared Rust PDF libraries (lopdf, pdf-extract, pdf_oxide, unpdf: licences, encryption,
bounded decompression). Context7: library lookup. Mobbin: unavailable (paid plan). Sentry and Supabase:
not used; Atlas has neither (local SQLite).
