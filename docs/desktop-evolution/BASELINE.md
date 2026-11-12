# Prometheus desktop evolution: baseline

**Recorded:** 2026-11-12 · **Branch:** `claude/prometheus-ai-evaluation-pxqzfr` · **Commit:** `2846dc7`
**Working tree:** clean (Atlas work in progress was parked on `claude/atlas-0.5-command-center-wip`
before this mission started; nothing under `atlas/` is changed by this mission).

## Environment where the baseline ran

Linux container, Python 3.13.18. Installed for the run: openai 3.46, python-dotenv, numpy 2.5, Pillow,
PyQt6 6.12, PyOpenGL, sounddevice (with PortAudio), soundfile, edge-tts, psutil, keyring, pytest 9.2.
**Not installed:** openai-whisper / PyTorch (the GUI tests use stubs from `tests/_gui_stubs.py`),
pyautogui, opencv, mediapipe, pyserial.

## Test results (before any change)

| Run | Result |
|---|---|
| `pytest tests` without PyQt6 | 409 passed, 36 skipped (GUI tests skip) |
| `QT_QPA_PLATFORM=offscreen pytest tests` with the GUI stack | **443 passed, 2 skipped** |

The two skips: the slow patch-gate run against the real project (`RUN_SLOW_TESTS=1`), and a sibling
adapter test that needs *no* keyring module.

## What exists (from the source, not the README)

| Area | Implementation | Notes |
|---|---|---|
| Entry points | `prometheus.py` (terminal REPL, `main()`), `gui_orb.py` (PyQt6 HUD) | The GUI imports the core module directly |
| Providers | `PROVIDER_ENDPOINTS`: OpenRouter, Groq, Cerebras, Ollama (local). `RotatingLLMRouter` ranks by priority then cost, 60 s cooldown failover | Keys from environment / `.env` only |
| Tools | 32 tools in `_RAW_TOOL_SPECS`, one `dispatch_tool` | `DANGEROUS_TOOLS` (9 names + policy + unsandboxed skills) need confirmation |
| Safety | `safety.py`: `Policy` (permissions.json, stricter-only), hash-chained `AuditLog`, `UndoJournal` | Applied inside `dispatch_tool` |
| Memory | `memory.json`, `VectorRAGStore` (pure Python), `memory_graph.py` (entities, facts, provenance, lessons) | |
| Scheduler | `SchedulerEngine` (`schedule.json`), tick thread marks jobs due; delivered at the next turn | Starts a thread **at import** |
| Engineering | `engineering.py` (sections, beams, stress, buckling, truss, ISA, aero, orbital) | Exposed as the `engineering_calc` tool |
| Forge | `run_code_forge`, `synthesize_dynamic_tool`, `skill_forge.py` (skills with gates, versions, rollback), `patch_gate.py` + `propose_code_change` / `apply_pending_patch` | Patches target the Prometheus source itself |
| Obsidian | `obsidian_memory.py` mirror, writes only under the vault's Prometheus folder | |
| Robot arm | `arm_sim.py` (kinematics), `arm_gesture.py`, `arm_bridge.py` (serial), Arduino firmware | Documented as simulation-only until hardware is validated |
| Reflection | `reflection.py` `ToolStats`, lessons from rejections; `evals/run_evals.py` | |
| Sibling link | `sibling_adapter.py` (Atlas pairing, HMAC) | Uses the OS keyring when available |
| GUI | `gui_orb.py` (2245 lines): OpenGL `SolarSunWidget`, birth animation (`gui_birth.py`), Whisper input, edge-tts output, streaming worker, settings dialog | One window, no navigation |
| Packaging | **None** for Prometheus (no installer, no build workflow) | The four GitHub workflows are Atlas's |

## Facts that shape the desktop design

1. **Without any key the core still imports**, with only local Ollama assumed (it needs no key); requests
   then fail at the first turn if Ollama is not running. The router is built once at import, so keys
   added later need a restart. (Corrected 2026-11-12 after testing: an earlier draft of this file said
   import fails, which only happens if no provider client can be constructed at all.)
2. **All personal data lives in the source folder** (`BASE_DIR`): memory, sessions, audit log,
   permissions, skills, schedule, GUI settings. An installed copy in Program Files cannot write there.
3. **The workspace tools (`write_file`, `edit_file`, `execute_shell`) are confined to the source
   folder** too: the workspace *is* the Prometheus repository.
4. **The GUI imports Whisper (PyTorch) unconditionally**, so voice is a hard dependency of the GUI and
   the install would be several gigabytes.
5. Import has side effects: logging to `prometheus.log` in the source folder, creating folders, starting
   the scheduler thread.

## Known security limitations (as documented in the code, unchanged)

The destructive-command filter is not a sandbox; skills without Docker are resource-limited only; the
patch gate is not proof a patch is safe; undo covers files changed by the workspace tools, not shell
side effects; the audit hash chain detects edits but not replacement of the whole file.
