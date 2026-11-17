# Prometheus 2.0: visual QA

Process: `tools/renaissance_screens.py` drives the real window (Xvfb, software OpenGL) at 1440×900, then
1100×720 (small laptop) and 1600×980 (large monitor), plus dialogs, avatar states, the activity centre
and a toast. Each screenshot was reviewed against the checklist below; issues were fixed and the set
recaptured.

## Checklist (applied to every screen)
Purpose clear at a glance · one obvious primary action · strong hierarchy · space used deliberately (no
blank panels) · comfortable type · nothing needlessly repeated · not overwhelming · its own composition ·
still recognisably Prometheus · the controls shown actually work.

## Before → after
| Before (first Renaissance pass) | After |
|---|---|
| Same header + bordered cards + table on almost every screen | Each screen composes its own top area; tables kept only where people compare columns (skills, patches, undo journal) |
| Home: seven equal cards incl. an audit log | Welcome + ask, then Continue / Today / Needs you / At a glance |
| Companion: three fixed columns | Reading column, toggled panels, presence bar, starters, contextual actions |
| Workspace: large blank preview until a file is picked | Overview of projects and recent changes; inspector with actions |
| Results only in tiny labels | Toasts + activity centre |

## Issues found and fixed in this pass
* Companion failed to start (panel built before the presence bar existed) — caught by the self-test.
* Empty mission shown as "Started" — caught by a new test.
* Markdown symbols (`**`, code fences) in one-line previews on Home and in the conversation list.
* "Skills_self-patches" mnemonic; robot-arm −/+ buttons rendered blank (padding, glyph).
* Earlier pass: pill colours (#RRGGBBAA read as #AARRGGBB), clipped Forge text, truncated file names.

## Second Birth pass
40 screenshots: launch phases (00a–00e), onboarding (00-1…3), every section at 1440×900, collapsed
navigation, approval card with a real diff, eleven avatar states, search, mission, activity centre,
toast, small (1100×720) and large (1600×980) windows, memory map, Settings data page.
Found and fixed: state signs and the wordmark did not appear in captures when painted inside the GL frame
(moved to transparent layers); wordmark hidden behind the corona (moved lower); skip hint inherited the
wordmark's letter spacing; search rows clipped their second line; secure-storage warning read like an
error with no way forward (now why / fix / meanwhile); temporary paths shown as identity (now ~).

## Known visual limits
Screens were checked on Linux with software OpenGL; Windows font rendering (Segoe UI Variable) and
high-DPI scaling have not been seen on a real Windows desktop. The 64 px Companion sun is checked at
260 px in `15-avatar-*.png`.
