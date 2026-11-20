# Prometheus Desktop 2.5.0 — ORBIT, closer to the reference

Released after every Windows check passed (standing owner authorisation). Unsigned installer. Earlier releases stay
published unchanged.

This release takes ORBIT toward the reference design the owner shared: a dominant core, curved connections,
chamfered holographic panels with real actions, and a full-screen heads-up layer. Everything shown is still real
data or an honest empty hint.

## The core

* **Particle torus**: a dense ring of luminous dust around the sun, seen at a tilt. It turns with the real state's
  ring speed, its tube swells with the real microphone level (listening) or playback level (speaking), and the sun
  hides the particles behind it.
* **Geodesic shell**: a slowly turning wireframe sphere around the sun, brighter while Prometheus is thinking or
  building.
* The core is larger on the stage; the orbital rings now sit outside the torus (1–3, by intensity).
* Particle budgets follow *Visual…* (density, intensity) and the frame monitor, as before.

## Connections

* Lines are **curves** that bow away from the core, leave from the torus rim, end in a small node on the panel, and
  carry their light pulses along the curve. They still exist only for real relationships.

## Panels

* **Chamfered holographic frames** (cut corners, a faint accent wash behind the title, accent brackets on the cut
  corners), a **line icon** per panel and a per-panel accent: solar gold, amber and champagne; Ideas in soft violet
  (possibilities rather than commitments); risks in warm red.
* **Real actions** at the foot of panels:
  * Ideas — **Compare ideas** sends a real message asking Prometheus to compare the plan's ideas (needs two or more);
    **+ Add** adds your own idea as a new plan version (undo restores the previous one).
  * Project brief — **Edit brief** writes or changes the brief (new plan version).
  * Files — **+ Attach** a workspace file.
* Ideas can also be added and removed by voice or typing: "add idea: …", and through the plan editor.

## Immersive ORBIT

*Immersive* now fills the window with the universe and a heads-up layer:

* top left: a **status chip** with the real state and the current stage;
* top centre: **Projects / ‹project›** over a **curved stage track** (Overview → Complete), each dot done / current /
  open from the real session; click a dot (or arrow keys + Enter) to go where that stage's work happens;
* top right: environment menu, **Conversation** (slides the conversation in beside the stage), visual settings, Exit;
* bottom left: **Talk** and a message field;
* bottom centre: a **caption** of the latest real line (Prometheus's streaming reply, what you said, or ORBIT's notes).

The workflow row (Approve plan, Build workflow, Start …) stays visible in immersive mode.

## Fixes

* Panels no longer land in the wrong place after switching environments while the window resizes (a delayed
  appear-animation could start after the resize had settled the panel).
* Automatic layout changes (title-bar chips on small windows, overlap avoidance) are no longer saved as if you had
  resized the panel yourself; only a resize with the grip is remembered.

## Verified

* `python -m pytest tests -q`: 547 passed, 2 skipped (Linux), plus the window smoke test with new immersive HUD checks.
* Real-window screenshots under xvfb: `docs/screenshots/orbit/` (00–12).
* The Windows build, packaged self-test, install / upgrade with data kept / uninstall, and the real voice engines
  run in the release workflow; this release is published only if they pass.

## Not verified

* Not yet run on a physical Windows PC by the owner; the denser core has only been rendered under xvfb (software
  rendering). On a slow machine the frame monitor lowers the particle budget automatically.
* Image generation from the reference design is not included: Prometheus has no image provider configured, and ORBIT
  does not fake one.
