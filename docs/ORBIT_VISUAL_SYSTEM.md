# ORBIT — Visual system

One idea in both products: **the plan orbits the AI**. Each product keeps its own identity.

## Prometheus (Solar × Cosmic)

* Centre: the existing GLSL sun, drawn at a smaller disc scale (`SolarAvatar.disc_scale = 0.42`) inside a larger
  widget so the corona fades out; a transparent vignette layer blends the square edge into the stage (`_Vignette`).
  Without OpenGL 3.3 the painted `SolarGlyph` stands in.
* New avatar states: **PLANNING** (dashed wide orbit, bodies settling one by one) and **EXECUTING** (twelve step
  marks filled from the real completed share, plus a slow amber sweep). Existing states unchanged.
* Orbits: `BORDER_STRONG` 1 px (dashed while provisional); phase labels faint, uppercase, at the top of each orbit.
* Bodies: elevated surface fill; outline colour by state (completed green, running amber, failed red, awaiting
  champagne, blocked warn, others gold/muted); high priority slightly larger; proposed = dashed outline; selection =
  thicker outline + focus ring. Every state also has a **symbol** (✓ ▶ ‖ ! ? ⧗ ⊘ × ○ ◌) and **words** in the Step
  tab and Outline — never colour alone.
* Labels point away from the sun and flip sides only to stay on the canvas.
* Dependencies: warm bronze curves bending toward the centre with arrowheads.
* Motion: only new bodies animate (0.5 s settle, staggered); the timer stops when they settle. Reduce motion: no
  settle animation, still avatar sign.

## Atlas (electric blue)

* Centre: the existing `VoiceRing` (150 px) reacting to real audio; ORBIT passes the real voice phase (processing
  while a turn or step runs).
* Orbits and bodies in SVG with Atlas tokens (`--line-2`, `--accent`, `--ok`, `--err`, `--warn`), same symbols and
  words as Prometheus for state, dashed outlines for proposed/provisional.

## Screenshots

Prometheus: `docs/screenshots/orbit/` (10 captures from the real window). Atlas: not captured (see
`ORBIT_VISUAL_QA.md`).
