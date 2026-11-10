# Desktop presence (0.4.2)

Tray icon, a global "summon" shortcut and notifications. All of it is optional: Atlas works fully with
every item here turned off.

## Defaults

| Setting | Default | Why |
|---|---|---|
| Tray icon | On | Harmless: an icon with Open, Talk and Quit |
| Keep running when the window is closed | **Off** | Closing the window quits Atlas, as before |
| Global shortcut | **Off** (Ctrl+Alt+Space once enabled) | A system-wide shortcut is never taken without being asked |
| Start listening when summoned | Off | The microphone never turns on by surprise |
| System notifications | **Off** | Atlas's own list (the bell) always works; the system's is opt-in |
| Only when Atlas isn't in front | On | No pop-ups about what is already on screen |
| Show what it's about | Off | Notifications can appear on a lock screen, so the default wording is generic |

Upgrading from 0.4.1 changes nothing except that the tray icon appears.

## Who decides what

| Part | Owns |
|---|---|
| Core (`core/src/desktop.rs`) | The settings; shortcut validation; whether a notification may reach the system; de-duplication; the stored list; redaction of secrets |
| Shell (`src-tauri/src/presence.rs`) | Carrying it out: tray icon, registering the one shortcut, showing a system notification the core allowed |
| Window (`src/features/desktop/*`) | Settings → Desktop, the bell, reacting to a summon |

The window has **no** access to the tray, shortcut or notification plugins: `capabilities/default.json`
grants none of them, and an end-to-end test confirms a direct call is refused. Every change goes through
`settings_update`, which the core validates.

## Global shortcut

* **One shortcut, at most.** Changing it releases the old one first; saving unrelated settings never
  registers it twice; turning it off or quitting releases it.
* **Validation (core):** needs Ctrl, Alt or the Windows key; letters and digits need two modifiers (so
  Ctrl+C can never be captured); combinations the system uses (Alt+F4, Alt+Tab, Win+L, …) and Atlas's own
  push-to-talk (Ctrl+Shift+Space) are refused.
* **Conflicts:** if another app already holds it, nothing is registered and Settings → Desktop says so.
* **What it does:** brings the window forward, opens the Companion and puts the caret in the message
  box. With "Start listening when summoned" on and voice set up, it starts push-to-talk instead.
* **Focus:** Atlas takes focus only here, from the tray, or when started a second time. Nothing else
  raises the window. A summon never interrupts the introduction.

## Tray

* Left click: open Atlas. Menu: **Open Atlas**, **Talk to Atlas**, **Quit Atlas**.
* "Keep running when the window is closed" hides the window instead of quitting, and only while the tray
  icon is on (there must be a way back). Quit from the tray menu.
* A second launch returns to the running Atlas (Windows, macOS), so there is never a second copy sharing
  the database.

## Notifications

| Raised for | In Atlas's list | By the system (if enabled) |
|---|---|---|
| An approval Atlas is waiting for | Always; cleared when decided | When allowed and Atlas isn't in front |
| A reply that finished | Only if you were away | Same |
| A reply that failed | Only if you were away | Same |
| A mission that needs you, is ready for review, failed or lost contact | Always | When allowed |

* **No duplicates:** the same event is not repeated while its notice is unread. The list keeps the
  latest 200.
* **Privacy:** titles are fixed wording. The conversation or mission title is shown by the system only
  with "Show what it's about" on. API keys and tokens are redacted before anything is stored.
* **Audit:** turning on system notifications, the global shortcut or keep-running is written to the
  audit log.
* Opening a conversation clears the notices about it.

## Platform limits

| | Windows 10/11 | Linux | macOS |
|---|---|---|---|
| Tray icon | Yes | Needs AppIndicator support; stock GNOME hides it | Built, **not tested by a person** |
| Global shortcut | Yes | X11: yes. **Wayland: no** (the system forbids it; Atlas says so) | Built, not tested by a person |
| System notifications | Yes (from the installed app) | Needs a notification service | Built, not tested by a person |
| Second launch returns to the first | Yes | **No** (a second window opens) | Yes |

## What was tested, and how

| Check | How | Real or simulated |
|---|---|---|
| Shortcut rules, normalisation, reserved combinations | Rust unit tests | Real code, no desktop |
| One shortcut at a time, no duplicates, conflict reporting | Rust unit test with a stand-in registrar | **Simulated** conflict |
| Shortcut registers, changes and is released in the running app | End-to-end, Linux (X11 under Xvfb) and Windows CI | Real registration on CI machines |
| Notification permission, de-duplication, generic wording, redaction | Rust tests with a recording shell | Real core, simulated system |
| Bell, settings page, wizard, summon handling | Vitest + end-to-end | Real UI; test builds record system notifications instead of showing them |
| Window cannot call the plugins directly | End-to-end | Real |
| **A real notification appearing on a real desktop** | — | **Not tested** |
| **Pressing the real shortcut from another app** | — | **Not tested** (CI has no second app to press from) |
| **Tray icon seen and clicked** | — | **Not tested** (CI has no visible tray) |

The last three need a person at a PC. See the checklist in INSTALL.md, step 7.
