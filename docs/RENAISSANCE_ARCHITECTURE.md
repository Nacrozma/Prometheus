# Prometheus 2.0: architecture

Unchanged foundation (verified): the Python core (`prometheus.py` and its modules) is the single source of
truth, used in-process by the desktop app; the terminal (`python prometheus.py`) and the HUD
(`python gui_orb.py`) keep working. Everything that changes state goes through `dispatch_tool` (policy,
conscience check, audit log, undo journal), except the owner's own memory and undo actions in the desktop,
which call the same core objects directly and are recorded in the same hash-chained audit log.

```
app/application.py      start-up, self-test, first-run onboarding
app/ui/theme.py icons.py widgets.py      design system
app/ui/main_window.py   grouped NavBar, top bar (search, provider pill, auto-approve pill, bell), pages,
                        command palette with universal search, notifications, tray, shortcuts
app/ui/sun.py           painted sun (Home, onboarding, fallback without OpenGL)
app/ui/solar.py         shader sun for the desktop (extends gui_orb.SolarSunWidget, adds tint/dim,
                        honest overlay, frame-rate policy)
app/ui/onboarding.py    first-launch welcome
app/ui/pages/*          Home (new), Companion, Memory, Engineering, Forge, Workspace, Reminders & tasks,
                        Obsidian, Robot arm, Reflection, Trust & safety, Settings
app/services/core.py            the one door into the core (unchanged)
app/services/conversations.py   many conversations (JSON per conversation, atomic writes)
app/services/search.py          universal search across the sources the app can already read
app/services/memory_ops.py      owner memory actions: add, correct, confirm, forget (audited)
app/services/forge_missions.py  Forge disciplines and their enforced boundaries
app/services/workspace_info.py  projects, read-only Git state, recent changes
app/services/providers.py       provider connection tests and model choice
app/services/export.py          backup .zip without credentials
```

## Decisions

| Decision | Why |
|---|---|
| Keep PyQt6 and the existing GLSL sun; extend rather than replace | Stable, tested, already packaged; the sun is Prometheus's identity |
| Desktop shader variant built from the HUD shader text at runtime | Adds a state tint without changing `gui_orb.py` (HUD unchanged); if the shader text ever changes, it falls back to the original |
| Conversations as separate files; HUD `session.json` imported once (copied, never deleted) and the open conversation mirrored back | Many conversations without breaking the HUD |
| Forge disciplines enforced at the desktop approval gate | The worker cannot run a real-world tool without an answer from that gate; auto-approve is forced off during missions |
| Owner memory actions outside `dispatch_tool` | They are the owner acting, not the model; they are audited, and forgetting also removes the text from the flat memory file and the retrieval index |
| Git read with fixed argument lists, read-only commands, inside the workspace, 6 s timeout | Visibility without giving anything a shell |
| No new runtime dependency | QtSvg is part of PyQt6 |

## Data (all in the data folder; no migration of existing files)
New: `conversations/<id>.json`, `conversations/_state.json`, `forge_missions.json`; new optional keys in
`desktop_settings.json` (`nav_collapsed`, `last_section`, `home_hidden`); memory facts may carry
`confirmed: true`. Old data folders open unchanged; the HUD session becomes the first conversation.

## Core changes
`memory_graph.py`: two additive methods (`confirm`, `get_fact`). No other core file changed.
