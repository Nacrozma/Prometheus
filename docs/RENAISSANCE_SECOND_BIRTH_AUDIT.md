# Prometheus Renaissance — Second Birth: audit

**Date:** 2026-11-17 · **Branch:** `claude/prometheus-ai-evaluation-pxqzfr` · **Baseline:** commit `d768999`
(constitution installed), 481 tests passing, Windows CI run 9 failing on one Windows-only path bug.
Baseline evidence: the 31 screenshots in `screenshots/renaissance/` at that commit, and the source that
produced each (map below).

## Screen → source → data → tests

| Screen | Source | Data | Tests before this pass |
|---|---|---|---|
| Launch | none (splash pixmap only) | — | — |
| Home | `app/ui/pages/home.py` | conversations, scheduler, task record, patches, tool stats, memory stats, missions | window smoke test (opens) |
| Companion | `app/ui/pages/companion.py`, `gui_orb.PrometheusWorker` | `ConversationStore`, router | smoke: approval gate, conversations |
| Avatar | `app/ui/solar.py` (+ `gui_orb.SolarSunWidget`), `app/ui/sun.py` | worker events, TTS/mic level | none |
| Approval card | `companion.ApprovalCard` | tool name + raw JSON | smoke: card shown, Deny reaches the worker |
| Memory | `pages/memory.py`, `services/memory_ops.py` | memory graph | service tests |
| Engineering | `pages/engineering.py`, `services/project_intel.py` | `engineering.py`, workspace | service tests |
| Forge | `pages/forge.py`, `services/forge_missions.py` | mission log, conversations | boundaries, stages |
| Workspace | `pages/workspace.py`, `services/workspace_info.py` | workspace folder, Git | service tests |
| Tasks | `pages/tasks.py` | scheduler, task record | grouping |
| Obsidian | `pages/obsidian.py`, `services/vault_reader.py` | the vault | service tests |
| Robot arm | `pages/arm.py` | `arm_sim` | core arm tests |
| Reflection | `pages/reflection.py` | tool stats, usage log, evals | suggestions |
| Trust | `pages/trust.py` | policy, audit log, undo journal | — |
| Settings | `pages/settings.py`, `credentials.py`, `services/providers.py` | settings, OS credential store | export test |
| Search | `main_window.CommandPalette`, `services/search.py` | all of the above | search test |

## Findings (highest impact first) and what this pass did

| # | Finding | Decision | Status |
|---|---|---|---|
| 1 | No launch moment at all: a static splash | Reuse the HUD's tested star-birth timeline and shader (`gui_birth.py`) full-window, add the wordmark and a fade into Home | Implemented, tested |
| 2 | Avatar states nearly identical in the screenshots | A sign per state (shape, not only colour) + stronger tints; new PAUSED state for "waiting for your approval" | Implemented, tested |
| 3 | Approval card = warning + raw JSON | Plain-language title, why (Prometheus's own words before the call), what, real diff/content, affects / undo / your data / if you deny, arguments on request, equal-weight buttons | Implemented, tested |
| 4 | Memory has a graph but showed only lists | Interactive map from stored entities and relations | Implemented, tested |
| 5 | Search results a flat list | Grouped by kind, matches highlighted, guidance when empty | Implemented |
| 6 | Mission view lacked the changes themselves | Diffs from the mission's recorded tool arguments | Implemented |
| 7 | Secure-storage warning confusing | Platform-specific why / how to fix / meanwhile; never a plain-file fallback | Implemented, tested |
| 8 | Temporary paths shown as the workspace | Paths shown with ~ for the home folder | Implemented, tested |
| 9 | Robot arm JSON earlier dominated | Kept as a collapsible "technical output" | Implemented |
| 10 | Windows CI: project paths wrong (short names expanded) | `realpath` the project before relative paths | Fixed, test passes on Linux; Windows result pending at time of writing |

## Feature preservation checklist (verified at the end)
All items of `RENAISSANCE_AUDIT.md`'s checklist, plus: conversations (new/rename/delete), Forge boundaries,
toasts and activity centre, memory controls, planner, Obsidian reader, project intelligence — covered by
`tests/test_renaissance.py` and the window smoke test; the self-test opens all 12 sections.

## Not done in this pass (honest list)
* Physical Windows desktop check (font rendering, high DPI, GPU) — needs the owner's PC.
* New providers (Anthropic, Mistral) — needs the owner's decision (paid services).
* Obsidian export history — the core keeps no export history to show.
* Editing files inside Workspace — viewing only (the file tools write through approvals).
