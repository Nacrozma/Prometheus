# Prometheus Desktop 2.4.0 — the ORBIT universe

Released after every Windows check passed (standing owner authorisation). Unsigned installer. Earlier releases stay
published unchanged.

## ORBIT becomes a living solar command environment

* **The core**: the existing GLSL sun stays at the centre, now surrounded by a layered solar core — tilted
  orbital rings turning in different directions, an inner energy mesh, an orbiting particle field, controlled arcs,
  an outer shield, a core pulse, and an audio ring that moves with the real microphone (listening) or real playback
  (speaking). Each real state has its own visual language: idle, listening, thinking, planning, researching,
  building, running, waiting for approval (suspended, champagne), paused, adapting, success, offline, error.
* **The space**: a dark atmosphere with a faint hexagonal grid, distant points and slow energy currents, with gentle
  parallax; the sun's surround blends into it.
* **Holographic panels** — Project brief, Ideas, Files, Project plan, Next steps, Live activity, Structure,
  Operations, Approvals, Research, Open questions, Assumptions and risks. They assemble from the core, can be dragged,
  resized, collapsed, expanded (the rest of the space recedes) and hidden (their data stays; *Panels ▾* shows them
  again or resets the layout). Layout is saved per environment in the session. On small windows the extra panels
  become title bars.
* **Connections that mean something**: lines join the core to panels that have real content, ideas to the brief, the
  plan to next steps, files to the steps that wrote them, approvals to operations — with light travelling along
  them, brighter when something just happened.
* **The project journey**: OVERVIEW → IDEAS → PLAN → DESIGN → BUILD → REVIEW → COMPLETE, each ✓ done / ● current /
  ○ open from the real session (review and complete are your own marks: *Mark reviewed*, *Mark complete*). Click a
  stage to go where its work happens.
* **Four environments**: **Command** (brief, ideas, files, plan, next steps, activity), **Design** (the plan's
  orbits and dependencies with brief, plan and structure), **Operations** (the workflow constellation coloured by
  real step states, operations, approvals, next steps, files), **Intelligence** (research results, ideas, open
  questions, assumptions and risks).
* **Projects materialise**: say "Let's create a new project …" — a fresh session starts, and as Prometheus's reply
  streams, the brief, ideas, phases and tasks appear in their panels (marked "arriving…") before the plan is
  complete; a shockwave and a milestone mark the moment the project exists.
* **Files**: files written by ORBIT steps appear in Files linked to their step; attach workspace files with *+*;
  open one to preview it in the expanded panel (only files inside the workspace).
* **Entry sequence**: a point of light, the core forming, rings unfolding — the long version the first time, a short
  one afterwards; click or any key skips; off under Reduce motion or when switched off.
* **Visual experience settings** (*Visual…*): animation intensity (subtle / balanced / spectacular), particle density,
  environment depth, camera movement, cinematic entry, energy effects, ORBIT sounds and volume. Each really changes
  rendering; a frame monitor lowers quality automatically on slow machines.
* **Optional sounds**: quiet synthesised cues (entering, panels, confirmations, milestones), off by default, never
  played while Prometheus is speaking. No recorded or licensed audio assets.

Security, approvals and autonomy are unchanged: visuals never imply something ran that only was planned, and every
tool with real-world effects still asks.

## Verified
Linux: 542+ tests, window smoke test, 13 real-window screenshots (`docs/screenshots/orbit/`), a full frame measured at
about 8 ms (CPU painter, 980×700). Windows: the full test suite, packaged self-test, install/upgrade/uninstall, and the
real voice input and local speech checks in the release workflow. Not verified: a physical PC with a GPU, microphone
and speakers.
