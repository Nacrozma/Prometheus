# The solar avatar

Code: `app/ui/solar.py` (shader sun, desktop variant of the HUD shader with tint and dim), `app/ui/sun.py`
(painted sun), `app/ui/avatar_overlay.py` (the sign per state, shared by both). Screenshots `15-avatar-*`.

| State | Real event that sets it | Sign | Sun |
|---|---|---|---|
| IDLE | nothing running | none | warm, quiet |
| THINKING | the worker starts a turn / resumes after tools | two tilted orbits with travelling bodies | active surface |
| RESEARCHING | a reading tool runs (read_file, web_search, recall_memory…) | orbit + radar sweep | cooler tint |
| WORKING | another tool runs | rotating dashed ring | warmer |
| BUILDING | a building tool runs (write/edit, run code, skills, patches) | six turning blocks | hotter, more energy |
| ADAPTING | defined, not triggered by the desktop today (no real adaptation event is surfaced) | counter-rotating arcs | cobalt blend |
| LISTENING | voice input recording (only if Whisper is installed) | inward rings scaled by the real mic level | cooler, attentive |
| SPEAKING | speech playback | outward strokes scaled by the real playback level | bright |
| PAUSED | an approval card is waiting for you | still ring with two gaps | lowered energy |
| OFFLINE | no provider configured | dotted grey ring | dimmed, desaturated |
| ERROR | the model request failed | broken ring, slow pulse | restrained red tint |
| SUCCESS | a turn finished | one soft ring | brighter, then back to idle |

Every state is also given in words next to the avatar (and as its accessible description). Transitions
ease tint, dim and energy every frame, so an interrupted transition continues from where it was. Under
Reduce motion the sun and signs are drawn still. Frame rate: 60 fps active window, 30 fps inactive, stopped
when hidden/minimised. The sign is drawn on a transparent layer above the shader (painting inside the GL
frame is not reliably composited on all drivers).
