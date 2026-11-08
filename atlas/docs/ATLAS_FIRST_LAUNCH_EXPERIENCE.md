# First-launch experience

The introduction Atlas plays the first time it opens. Implemented in Stage 1 (0.3.0).

## What the owner sees

| Time (full motion) | Phase | On screen |
|---|---|---|
| 0.0 s | void | Near-black navy |
| 0.7 s | stars | Ambient stars fade in and drift slowly |
| 1.9 s | globe | The Atlas globe appears, and its satellite starts to orbit |
| 3.5 s | illuminate | The universe lights up in Deep Orbit cyan and teal; the globe glows |
| 4.7 s | dedication | **Created with love.** (about 4.3 s to read) |
| 9.0 s | welcome | Welcome. I'm Atlas. It's good to finally meet you. (about 3.8 s) |
| 12.8 s | leaving | The scene fades and the app is already there underneath |
| 13.6 s | done | Onboarding (first install) or the app (upgrade) |

**The words:**
* The dedication is exactly `Created with love.` It is not translated, personalised or logged.
* The welcome line is exactly as written and never uses the owner's name; the owner chose this.
* Both strings are constants in `src/features/first-launch/sequence.ts`, and tests check them
  character for character.

The electric-blue voice ring is not part of the introduction yet. It depends on real voice output
(Stage 2) and will be added between "illuminate" and "dedication" then.

## Rules

| Requirement | How |
|---|---|
| Runs once | The core stores `first_launch.completed_at` when the introduction ends or is skipped. `settings_update` cannot change it; only the `first_launch_complete` command can set it, once. |
| Upgrades | An installation upgraded from 0.2.x has no completion time, so the introduction plays once after the upgrade. |
| Skip | A Skip button (Tab reaches it) and Esc, at any moment. |
| Replay | Settings → About → Introduction → Replay. A replay records nothing. |
| Reduced motion | With the OS or Atlas set to reduced motion, the scene is still: no drift, scaling, fades or orbit. Only the words change, with the same reading time. Total 8 s. |
| Never blocks startup | It sits above the app, which loads normally and is inert underneath. If recording completion fails, the app opens anyway and the introduction plays next launch. |
| Closed part-way | Nothing is recorded, so it plays again from the start next time. |
| Window size and DPI | The globe scales with the window (96–220 px). The star canvas renders at the screen's pixel ratio. Text sizes use `clamp()`. |
| Hidden window | The star animation pauses while the window is hidden. |
| Offline, no keys | No network or provider is involved. |
| Privacy | The dedication never appears in notifications, diagnostics or the audit log. The audit event is `intro.completed`, with no text. |
| Accessibility | A labelled region; the words are announced through a polite live region; text that has faded out leaves the accessibility tree. |

## Code

* `src/features/first-launch/sequence.ts`: timeline, phases and the two strings (pure).
* `src/features/first-launch/FirstLaunch.tsx`: the scene, Skip, Esc, completion.
* `src/features/first-launch/Starfield.tsx`: DPR-aware star canvas, paused when hidden, static when reduced.
* `src/app/App.tsx`: decides once at startup whether to play it; makes the app inert while it shows.
* `core/src/settings.rs` (`FirstLaunchState`), `core/src/app.rs` (`complete_first_launch`, and
  `update_settings` keeping the state core-owned).

## Tests

| Test | Checks |
|---|---|
| `tests/unit/first-launch.test.tsx` | Exact strings; phase order; reading time; one line at a time; plays through and records once; Skip and Esc; replay records nothing; reduced-motion still scene; a recording failure never blocks |
| `the_introduction_is_recorded_once_and_settings_updates_cannot_reset_it` (Rust) | Idempotent completion; the UI cannot clear or forge it |
| `older_documents_with_changed_axes_load_as_custom` (Rust) | An upgraded profile has no completion time, so it plays once |
| e2e "the introduction plays once on first launch…" | Real app: the dedication is exactly as written; the welcome follows; it ends by itself; the core records it; a reload does not replay it |
| e2e "…the introduction replays as a still scene under reduced motion" | Replay from Settings → About; `data-reduced="true"`; Esc skips |

**Still needs a person:** watching it on the target Windows PC (timing, feel, text rendering at that
DPI). Automated tests check behaviour, not taste.
