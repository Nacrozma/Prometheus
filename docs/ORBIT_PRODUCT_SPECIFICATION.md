# ORBIT — Product specification

**ORBIT is where you think out loud with your AI and watch the plan take shape around it.** You talk; the AI asks
what it needs; a plan forms around the avatar; you change it by voice or by hand; you approve it; it becomes a
workflow of steps mapped to real capabilities; the steps run under your autonomy setting and the existing approval
gates; you see each step's real state.

Two independent implementations:

| | Prometheus | Atlas |
|---|---|---|
| Avatar at the centre | the GLSL solar sun (painted sun without OpenGL) | the electric-blue voice ring |
| Where | navigation “ORBIT” (Conversation group) | rail “ORBIT” |
| Enter | nav, `Ctrl+Shift+O`, `Ctrl+Shift+Space` (talk), palette (Open / Talk / Plan this conversation / New session), `/orbit` in Companion | rail, `Ctrl+Shift+O`; voice shortcut `Ctrl+Shift+Space` (existing) |
| Code | `app/services/orbit.py`, `orbit_voice.py`, `app/ui/pages/orbit.py` | `core/src/orbit.rs`, `src/features/orbit/*` |
| Data | `<data>/orbit/<id>.json` (atomic JSON) | SQLite `orbit_sessions` (schema 10) |

## Users and jobs

The owner, planning anything from a release to a week: “help me work out how to do X”, “change that”, “now do it”.
First thing seen: the avatar and one sentence explaining the space. Primary action: talk (or type).

## Experience modes

* **Integrated** — ORBIT inside the app shell; navigation stays.
* **Immersive** — only ORBIT (navigation/top bar/status bar hidden). Esc or *Exit immersive* returns; navigating
  elsewhere also leaves immersive mode.

## What is real (and only real)

Plans are data from Prometheus/Atlas replies or your edits; node states come only from recorded events; the avatar
shows only real states (listening = mic open, speaking = audio playing, planning = a plan is streaming, executing =
a step runs, waiting = approval needed); the level meter is the real mic/playback level; progress is the count of
completed steps.

## Not in this version (honest scope)

* Voice barge-in while the AI speaks (no echo cancellation) — interrupt with Stop speaking / Esc / Space / Talk.
* System-wide hotkey for Prometheus ORBIT (in-app shortcuts only). Atlas keeps its existing global shortcut setting.
* Atlas: specialist missions and Forge runs are not yet step operations (Atlas steps: Atlas turn, research turn,
  add to Tasks, manual).
* Prometheus: Workspace/Forge pages do not yet have their own “Plan in ORBIT” buttons (palette + `/orbit` exist).
