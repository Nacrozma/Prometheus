# Prometheus 2.0: interaction guide

## Keyboard
| Keys | Where | Does |
|---|---|---|
| Ctrl+K | anywhere | Search everything / commands (↑ ↓ to move, Enter to open, Esc to close) |
| Ctrl+1 … Ctrl+9 | anywhere | Go to the first nine sections in navigation order |
| Ctrl+B | anywhere | Collapse or expand the navigation (remembered) |
| Ctrl+N | anywhere | New conversation |
| Ctrl+, | anywhere | Settings |
| Ctrl+Q | anywhere | Quit |
| Esc | Companion | Stop the current reply (a pending approval is denied) |
| Enter / Shift+Enter | Companion composer | Send / new line |
| Enter | Planner quick-add | Moves from "Remind me to…" to "in 2h", then adds |
| Enter | Engineering form, code search | Calculate / search |
| Arrow keys, Page Up/Down | Robot arm sliders | Move a joint by 1° / 10° |
| Tab / Shift+Tab | everywhere | Focus moves through controls; focus is shown with a champagne outline |

## Feedback rules
* Every action that changes something ends with a toast: **Done** (finished), **Working** (acknowledged,
  continues in the background, e.g. a mission started), **Attention** (needs you), **Problem** (failed,
  with the reason). Status is never shown by colour alone: icons and words go with it.
* Toasts and reminders are kept in the activity centre for the session.
* Harmless, reversible actions do not ask for confirmation (cancel a reminder, tick a step). Forgetting a
  memory, deleting a conversation and Undo ask first. Tools with real-world effects always show an
  approval card with the exact arguments; Deny is the default.

## Motion
The sun moves only to show state and real audio; Reduce motion stills it. Toasts fade in 220 ms (no
fade with Reduce motion). No page transitions slow navigation.

## Panels and preferences that are remembered
Navigation collapsed, last section, Home sections, Companion conversation list and context panel.
