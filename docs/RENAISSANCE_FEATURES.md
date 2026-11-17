# Prometheus 2.0: features

> The experience-first pass changed how each screen works; per-screen interaction models are in
> `RENAISSANCE_PAGE_SPECIFICATIONS.md`. New in that pass and tested: Forge mission stages from recorded
> events, Obsidian reader with backlinks, Engineering project intelligence (summary, tests found, code
> search), planner with a step checklist, reply lists saved as task steps, toasts and the activity centre.

Status words: **Implemented and tested** (automated tests or the window smoke test exercise it),
**Implemented** (in the real app and in the screenshots, no automated assertion), **Not implemented**.
Screenshots: `screenshots/renaissance/` (real window, Linux, Xvfb with software OpenGL, sample data made
through the app's own code paths by `tools/renaissance_screens.py`).

| Area | What it does | Status | Screenshot |
|---|---|---|---|
| Shell | Grouped navigation (Overview, Converse, Build, Organise, Lab, System) with icons, tooltips, collapse (Ctrl+B, remembered), Ctrl+1–9, breadcrumb, last section remembered | Implemented and tested (all 12 sections open) | 01, 13 |
| Top bar | Universal search button, provider/model pill (honest: "not used yet" until a reply), AUTO-APPROVE pill, notification bell with count | Implemented | 01 |
| Command palette (Ctrl+K) | Sections, commands, and search across conversations, memory, reminders, workspace files, audit activity; opens the result | Implemented and tested (search service) | 16 |
| Notifications | Reminders, refresh failures, reconnect results in the bell (this session); tray notification for reminders as before | Implemented | – |
| Home | Greeting, real status, quick ask, quick actions, recent conversations, reminders, current task, provider health, Engineering & Forge, memory, recent activity; Customize hides sections (remembered) | Implemented | 01 |
| Companion | Many conversations: list, search, rename, delete (confirmed), new; multiline composer (Shift+Enter); copy message / code / whole conversation; Regenerate; Retry after an error; calm status text; tool lines; approval cards (Deny default); provider shown in the composer; nothing sent when no provider | Implemented and tested (store; new/rename/delete in the window test) | 02, 14 |
| Solar avatar | Shader sun with states IDLE, THINKING, WORKING, RESEARCHING, BUILDING, SPEAKING, LISTENING, WARNING, ERROR, OFFLINE, SUCCESS from real events (tool type picks the work state); activity arc; level ring from the real TTS/microphone level; 60/30/0 fps policy; Reduce motion; painted fallback without OpenGL | Implemented | 15-* |
| Memory | Categories (facts, preferences, decisions, lessons), search without reinforcing, provenance (You / Prometheus suggested / Confirmed / Unverified), add, correct (keeps history), confirm, forget (also removed from retrieval), duplicate/conflict warning; all audited | Implemented and tested | 03 |
| Engineering | Calculators grouped by domain, results as a table with units, formula and warnings, session history, "Ask Prometheus to check this" | Implemented | 04 |
| Forge | Missions in four disciplines with enforced boundaries (Architect read-only, Reconstructor new files only, Builder/Debugger approve each step), mission history; skills and patches as before | Implemented and tested (boundaries; refusal in the window) | 05 |
| Workspace | Projects, file filter, highlighted/Markdown preview (.env, binaries, >200 KB, outside links refused), read-only Git branch/changes/commits, recent changes, reveal from search | Implemented and tested (service) | 06 |
| Reminders & tasks | Friendly times and repeats, views (upcoming/delivered/cancelled/all), cancel; current task goal, steps, status, notes via update_task_state; "Ask Prometheus to plan it" | Implemented | 07 |
| Obsidian | Unchanged behaviour, new look | Implemented (unchanged) | 08 |
| Robot arm | Simulation only, banner, unchanged behaviour, new look | Implemented (unchanged) | 09 |
| Reflection | Summary tiles, suggestions from the numbers, tool reliability, 30-day usage (floor; no prices), evaluation results in words (labelled synthetic) | Implemented and tested (suggestions) | 10 |
| Trust & safety | Tiles (approval on/off, gated tools, denied tools, chain), activity with filters and correct durations (bug fixed: it showed 0.00), where data goes, permissions, Undo the last file change (confirmed, audited) | Implemented | 11 |
| Settings | Provider connection test (model list, latency, current model offered?), choose each provider's model, backup export (.zip without keys/logs), everything that was there | Implemented and tested (export) | 12 |
| Onboarding | First launch: welcome, connect a model (key to the OS store or Ollama, test), workspace | Implemented | 00-* |

## Not implemented (and why)
* New providers (OpenAI, Anthropic, Mistral): OpenAI was removed by the owner on purpose; adding paid
  services needs the owner's approval. The router already supports OpenAI-compatible endpoints, so adding
  one is a small change once approved.
* Document intelligence (PDF/DOCX/XLSX import), research workspace with saved sources, data-analysis charts,
  user-defined workflow automation: not built in this pass; each needs new parsing dependencies or a new
  execution engine that should be designed and reviewed on its own.
* Attachments in the composer, side-by-side diffs and per-change diff approval: the core's tools do not
  expose diffs yet (edits show their arguments in the approval card).
* Global shortcut, persisted notification history, light theme.
