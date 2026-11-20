# ORBIT universe — implementation report (Prometheus 2.4.0–2.5.0, ATLAS 0.7.0)

Two independent implementations of one idea: ORBIT as a living command environment around each product's own
avatar. No code, data, credentials or runtime are shared. (No reference image reached this session; the layout
follows the written description: central core, rings, Files / Ideas / Brief / Plan / Next steps panels, stage bar.)

## Prometheus (PyQt6)
* `app/services/orbit_space.py` — stages from real state, environments, panel content (real data or an honest
  empty hint), connections only for real relationships, workspace-contained files, per-environment layout.
* `app/services/orbit_motion.py` — visual states for every real app state, settings → budgets, event effects,
  adaptive quality, particles.
* `app/services/orbit_sound.py` — optional synthesised cues; off by default; never while speaking.
* `app/ui/orbit_universe.py` — CoreFX overlay (rings, mesh, particles, arcs, shield, audio ring, shockwaves,
  connection pulses) above the existing GLSL sun; cached hex-grid background with parallax; HoloPanel (drag,
  resize, collapse, expand, hide, materialise/dissolve); StageBar; EnvBar; EntrySequence; VisualSettings; the
  Universe controller (layout, overlap avoidance, compact panels on small stages, real-event effects).
* `app/ui/pages/orbit.py` — wiring: streamed brief/ideas/plan → panels, files written by steps → Files, review /
  complete marks, "Let's create a new project", show/hide pauses the frame timer, Reduce motion stops it.
* Plans gain `brief` and `ideas`; sessions gain `files`, `reviewed`, `completed`, `environment`, `layout`
  (older sessions load unchanged).

## ATLAS (Rust + React)
* `core/src/orbit.rs` — `brief`/`ideas` in plans; `reviewed`, `completed`, `layout` in sessions (serde defaults);
  actions `mark_reviewed` (needs a completed workflow), `mark_complete` (needs review), `set_layout` (object, ≤16 KB).
* `src/features/orbit/orbitUniverse.ts` (was `orbitSpace.ts`) — stages, environments, panels, connections, layout, motion, core state
  priority, settings budgets, events between snapshots, frame monitor.
* `src/features/orbit/OrbitSpace.tsx` — one canvas loop (atmosphere, electric-blue core, connection pulses),
  paused when hidden, single still frame under reduced motion; DOM panels; stage bar; environments; entry overlay;
  visual settings; WebAudio cues.
* **Bug fixed**: ORBIT in 0.5.0 re-rendered forever once a session existed (unstable store selector). Found by the
  new harness `tests/visual/orbit-harness.html` + `orbit-shots.mjs`.

## Deferred (honest)
* True 3D (WebGL/Three.js) scenes: both products use layered 2D painting around their existing avatar renderers;
  depth comes from layering, translucency, parallax and motion. A GPU 3D layer was not added (dependency and
  performance cost without a clear gain yet).
* Specialised environments reuse existing capabilities only: Design has no new diagram editor beyond the plan
  constellation and structure panel; Intelligence shows research results from completed steps and plan
  knowledge, not a new research engine.
* Atlas: files written by steps are not tracked (Atlas tool events carry no paths); Files shows shared files.

## Tests and inspection
* Prometheus: 542+ tests pass (12 new universe tests, extended window smoke test); 13 real-window screenshots
  (`docs/screenshots/orbit/`); rendering cost about 8 ms per full frame at 980×700 (CPU painter, offscreen).
* ATLAS: 109 vitest tests (8 new), Rust core tests including the new actions; 8 harness screenshots
  (`atlas/docs/screenshots/orbit-*.png`) rendered from the real page with mocked IPC — not the built desktop app.
* Not verified: a physical PC with GPU, microphone and speakers; the Atlas page inside the built Tauri app.

## Update: the reference look (Prometheus 2.5.0, ATLAS 0.7.0)

Compared with the owner's reference image, four gaps were closed in both products:

| Reference | Prometheus 2.5.0 | ATLAS 0.7.0 |
|---|---|---|
| Dominant particle torus + geodesic sphere | Torus (budgeted by *Visual…* and the frame monitor, audio-reactive, occluded by the sun) and a turning geodesic shell; larger core | Same, electric blue, around the voice ring |
| Curved connections with light | Quadratic curves bowing away from the core, from the torus rim, pulses on the curve | Same |
| Chamfered panels with icons and actions | Painted chamfered frame, line icons, per-panel accents (Ideas violet); Compare ideas / + Add / Edit brief / + Attach | clip-path chamfer + SVG edge, lucide icons; Compare ideas / + Add / Edit brief / + Share (inline editors) |
| Full-screen HUD | Immersive: status chip, Projects / title over a curved stage track, environment menu, Conversation, settings, Exit, Talk + message, caption | Same |

Not built: generated images (no image provider is configured; nothing is faked). Screenshots:
`docs/screenshots/orbit/10-orbit-immersive-listening.png` and `atlas/docs/screenshots/orbit-08-immersive.png`.
