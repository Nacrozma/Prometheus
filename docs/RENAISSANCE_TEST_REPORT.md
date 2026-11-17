# Prometheus 2.0: test report

**Date:** 2026-11-17 · **Branch:** `claude/prometheus-ai-evaluation-pxqzfr` · **Platform:** Linux x86_64
container, Python 3.13, PyQt6 6.12 (offscreen and Xvfb with software OpenGL). Windows: the
`prometheus-desktop` workflow (tests, PyInstaller build, installer, install/upgrade/uninstall, packaged
self-test) runs on every push.

## Results (final code)

| Suite | Command | Result |
|---|---|---|
| All Python tests | `python -m pytest tests -q` | **485 passed**, 2 skipped (slow patch-gate run, needs `RUN_SLOW_TESTS=1`; keyring-absent case, a keyring is installed here) |
| New: Renaissance services | `tests/test_renaissance.py` | 18 passed (Second Birth added: approval descriptions and real diffs, including refusal cases and outside-workspace paths; memory graph only from stored entities with deterministic bounded layout; platform-specific secure-storage explanations and ~ paths; launch wordmark timing. Experience pass: experience pass added: mission stages only from recorded events and discipline suggestion; vault links, backlinks, search and boundary; project summary, test discovery and code search; Markdown-free previews, reply list detection, planner grouping). Earlier: conversations (legacy import once, titles, rename kept, search, delete, path escape refused, corrupt file quarantined), universal search (every source, hidden/dependency/outside-link files skipped, memory not reinforced), memory controls on the real core (add, duplicates, provenance, confirm, correct with supersede, forget removes text from graph/flat file/retrieval index, audit entries without memory text, chain verifies), Forge boundaries, backup export without keys/logs, workspace projects and Git, reflection suggestions |
| Window smoke test | `tests/test_desktop_app.py::TestWindowSmoke` | the real window starts offscreen; all 12 sections open without error; a dangerous tool shows an approval card and Deny reaches the worker; an Architect mission refuses a write with no card; new/rename/delete conversation; a result becomes a toast and is kept in the activity centre; the activity drawer opens; navigation selection and last section are remembered; the launch overlay starts and finishes without blocking; all eleven avatar states render; auto-approve off by default |
| Packaged self-test (source) | `python -m app --self-test=report.json` | ok: 12 pages, 32 tools, dangerous tools gated |
| Offline evaluations | `python evals/run_evals.py --quick` | ran (exit 0); synthetic |
| Windows CI | workflow `prometheus-desktop` | **runs 10, 11 and 12 passed** (12 = all Second Birth code); run 9 failed on a Windows-only path bug in project intelligence (short path names expanded by realpath), fixed in `405f1a9`; run 5: success; run 6: one test failed on Windows (it expected a backslash inside a zip entry name; zip entries always use /), fixed; later runs: see the Actions tab |

## Visual QA
See `RENAISSANCE_VISUAL_QA.md`. 40 screenshots (launch phases, avatar states, three window sizes) of the real window (`screenshots/renaissance/`), captured by `tools/renaissance_screens.py`.
Issues found and fixed during the first pass: `&` in section names shown as keyboard mnemonics ("Reminders_tasks");
status pill colours wrong (Qt reads `#RRGGBBAA` as `#AARRGGBB`); empty conversations piling up in the
list; truncated conversation titles; Workspace file names cut off; clipped text in Forge cards; checked
filter buttons not visibly selected; Home saying "Ready on ollama" when Ollama had not answered.

## Performance (measured)
Offscreen self-test start-to-exit (window, 12 pages, core load): 3.1 s, 164 MB peak resident memory (3
runs). Streamed replies are re-rendered at most 20 times per second instead of on every token. The shader
sun: 60 fps active, 30 fps when the window is inactive, stopped when hidden or minimised. Not measured: a
real GPU, long conversations on Windows.

## Not verified
* A real Windows desktop (high DPI, tray, notifications, the sun on a real GPU).
* A real model conversation: no provider key here; the Companion's worker is the HUD's, which has its own
  tests. Provider connection tests were exercised only for the "not configured / unreachable" paths.
* Voice input and output on real audio hardware.
