# Prometheus

> **Looking for ATLAS Co-Pilot (the Windows desktop app)? → [How to install it](INSTALL.md)**
> (latest: **0.7.0** — [download the installer](https://github.com/Nacrozma/Prometheus/releases/download/atlas-v0.7.0/ATLAS-Co-Pilot-Setup-x64.exe) ·
> [release page](https://github.com/Nacrozma/Prometheus/releases/tag/atlas-v0.7.0)).
> Its source is in [`atlas/`](atlas/) and does not share code with Prometheus.

> **Prometheus Desktop — latest: 2.6.0** (Windows 10/11, 64-bit, unsigned):
> **[⬇ download Prometheus-Setup-2.6.0-x64-unsigned.exe](https://github.com/Nacrozma/Prometheus/releases/download/prometheus-desktop-v2.6.0/Prometheus-Setup-2.6.0-x64-unsigned.exe)**
> · [release page](https://github.com/Nacrozma/Prometheus/releases/tag/prometheus-desktop-v2.6.0)
> · SHA-256 on the release page (`SHA256SUMS.txt`)
> · [all releases](https://github.com/Nacrozma/Prometheus/releases).
> Windows will warn about an unknown publisher: check the SHA-256, then *More info → Run anyway*.
>
> | Version | What it added |
> |---|---|
> | [2.6.0](https://github.com/Nacrozma/Prometheus/releases/tag/prometheus-desktop-v2.6.0) | The **engineering laboratory**: stiffness-method structures, fatigue and machine design, design optimisation, compressible flow, nozzles, RK4 trajectories, control sandbox, arm dynamics, uncertainty, experiment records and reports; arm firmware boots disarmed (hardware still untested) |
> | [2.5.0](https://github.com/Nacrozma/Prometheus/releases/tag/prometheus-desktop-v2.5.0) | ORBIT closer to the reference: particle-torus core, curved connections, chamfered panels with real actions (Compare ideas, + Add, Edit brief), full-screen heads-up layer |
> | [2.4.0](https://github.com/Nacrozma/Prometheus/releases/tag/prometheus-desktop-v2.4.0) | The **ORBIT universe**: layered solar core, holographic panels, project journey, four environments, entry sequence, visual settings |
> | [2.3.0](https://github.com/Nacrozma/Prometheus/releases/tag/prometheus-desktop-v2.3.0) | Spoken replies with a **local voice** (on your PC, no internet) or Microsoft online; voice, speed, Test voice (Settings → Voice) |
> | [2.2.0](https://github.com/Nacrozma/Prometheus/releases/tag/prometheus-desktop-v2.2.0) | Voice input set up from inside Prometheus (whisper.cpp, on your PC) |
> | [2.1.0](https://github.com/Nacrozma/Prometheus/releases/tag/prometheus-desktop-v2.1.0) | **ORBIT**: plan out loud with Prometheus around the sun, approve, run |
> | [2.0.0](https://github.com/Nacrozma/Prometheus/releases/tag/prometheus-desktop-v2.0.0) | The Renaissance desktop app |
>
> The same Prometheus as a desktop app with
> the living solar avatar, a command centre, search across everything (Ctrl+K), many conversations, memory
> you control, Forge missions (Architect, Builder, Debugger, Reconstructor), workspace and Git, engineering,
> reminders, Obsidian, arm simulation, Reflection and Trust & safety. Start it from a checkout with
> `python -m app`. What it does: [docs/RENAISSANCE_FEATURES.md](docs/RENAISSANCE_FEATURES.md) ·
> screenshots: [docs/screenshots/renaissance](docs/screenshots/renaissance) · installing:
> [docs/desktop-evolution/WINDOWS_INSTALLATION.md](docs/desktop-evolution/WINDOWS_INSTALLATION.md).
> Not yet validated on a physical Windows PC.

> **Working on Prometheus (people and Claude Code):** start with the project constitution in
> [CLAUDE.md](CLAUDE.md), then [docs/CURRENT_STATE.md](docs/CURRENT_STATE.md) and
> [docs/SESSION_HANDOVER.md](docs/SESSION_HANDOVER.md).

A local, terminal-based AI assistant written in Python. It talks to LLM providers through an
OpenAI-compatible router, keeps persistent memory and task state in JSON files, and can call a
set of tools (files, shell, web search, scheduling, sandboxed code execution).

Everything described here is in `prometheus.py`. Anything not listed is not built.

## What's in it

- **Router:** rotates across the providers you configure (OpenRouter, Groq, Cerebras, local Ollama), with cooldown-based failover.
- **Memory & task state:** `memory.json`, `task_state.json`, and a small pure-Python vector store (`vector_store.json`).
- **Tool dispatcher:** JSON-schema tool definitions; tools with real-world side effects require operator confirmation.
- **Sessions:** conversations are saved under `sessions/` and can be resumed with `/resume`.
- **Scheduler:** persistent reminders and recurring tasks.
- **Code Forge:** runs generated Python in Docker when available, otherwise a best-effort hardened subprocess (not a real security boundary).

## Setup

```
pip install openai python-dotenv        # terminal version only
# or, for the desktop GUI as well (large: openai-whisper pulls in PyTorch):
pip install -r requirements.txt
cp .env.example .env      # then fill in at least one key, or run Ollama locally
python prometheus.py      # terminal
python gui_orb.py         # desktop HUD
python -m app             # Prometheus Desktop (the full desktop app; needs pip install keyring)
```

`.env` is git-ignored. Never commit API keys; if one is ever pasted or committed, rotate it.

## State-file safety

All reads and writes of the JSON state files go through one shared lock, and every write is
temp-file + `fsync` + `os.replace`, so a crash mid-write can't leave a truncated live file. A state
file that fails to parse is moved aside to `<name>.corrupt.<timestamp>` rather than overwritten.

Concurrency stress test (uses temporary directories, never your real state):

```
python tests/stress_state.py            # current code
python tests/stress_state.py --legacy   # simulates the old behaviour (no lock, non-atomic vector save)
```

`--legacy` is a simulation of the earlier behaviour, not the earlier code itself.

## Memory graph and Obsidian

Long-term memory is a typed knowledge graph (`memory_graph.py`, stored in `memory_graph.json`): **entities**
(people, projects, tools, topics), **facts** linked to the entities they mention, and typed **relations**
between entities. Every fact records where it was learned and how confident/important it is. Importance
fades with time unless a fact is recalled, near-duplicates are merged (facts that differ in a number or a
negation are kept apart), and weak facts are archived, never deleted. Facts from the web or imported notes
are flagged *unverified* and never appear in the prompt's standing memory section.

The model records facts with `update_memory` (passing entities and relations when it knows them) and reads
them with `recall_memory` / `memory_graph_view`; the best matches are also added to every prompt
automatically. Commands: `/graph [entity]`, `/recall <query>`.

**Obsidian.** Set `PROMETHEUS_OBSIDIAN_VAULT` (or the vault path in the GUI settings) to your vault folder,
then run `/obsidian`. Prometheus writes linked notes into `<vault>/Prometheus/` (entities, a note per day,
lessons, skills, the current task) so Obsidian's Graph View shows the map. It never writes outside that
folder; your own text below each note's generated block, and any frontmatter properties you add, survive
every export; an edit *inside* the generated block is left alone and reported. Notes dropped into
`Prometheus/Inbox/` are ingested as unverified facts. Exporting from the model needs your confirmation.

## Skills and self-modification (Skill Forge, patch gate)

**Teaching itself new skills.** Prometheus can write a new skill (a small Python module) for itself, but
nothing is installed until it has earned it (`skill_forge.py`): the code and its tests pass a static policy
gate (an allowlist of pure-computation imports; no `eval`/`open`/`getattr`/dunder tricks; no work at import
time), then the model's own tests must pass **in an isolated process** (Docker with no network and a read-only
filesystem when a Docker engine is running, otherwise a resource-limited subprocess). Accepted skills are
versioned, can be rolled back (the old version's tests are re-run first), and run through the same sandbox -
never imported into Prometheus itself. A skill whose file is edited behind the registry's back refuses to
run. Installing needs your confirmation; so does running a skill unless Docker is the sandbox. Commands:
`/skills`, `/skills rollback <name>`, `/skills off|on <name>`.

**Patching its own source.** Every `propose_code_change` is checked automatically before it is even saved,
and again before it is applied (`patch_gate.py`): it must parse, keep the functions and safety lists the rest
of the system depends on (`DANGEROUS_TOOLS`...), not be a wholesale rewrite, and the project's own test suite
must show **no new failures and no vanished tests** when run on a patched *copy* with a stripped environment
(no API keys). A rejected proposal comes back with the reasons. Applying a patch still needs your approval.
This is a net for accidents, not proof a patch is good: the suite only catches what it tests.
`PROMETHEUS_PATCH_GATE=off` disables it (an explicit operator decision).

Honest limits: the policy gate is a filter, not a security boundary; without Docker the sandbox is resource
limits only. Docker must be an *engine that answers*, not just the `docker` command being installed.

## Engineering library and the robot arm (simulation)

**`engineering.py`** - deterministic calculators exposed to Prometheus as the `engineering_calc` tool, so it
stops doing arithmetic "in its head": unit conversion, section properties, beam reactions / moment /
deflection (simply supported and cantilever, point and distributed loads), bending, torsion and plane
stress (principal stresses, von Mises), Euler buckling, 2-D pin-jointed truss member forces (method of
joints, refuses indeterminate or unstable structures; the stiffness method in `eng/` handles those), ISA
atmosphere to 20 km (1976 standard to 86 km in `eng/`), lift / stall speed /
Reynolds number, circular orbits, vis-viva, Hohmann transfers and the rocket equation. Every result
carries its formula and assumptions. `tests/test_engineering.py` checks them against textbook values
(ISA tables, the LEO-to-GEO Hohmann transfer, hand-worked trusses and beams). These are first-pass design
numbers (linear elastic, small deflection, ideal pins), not FEA or a code check.

**The arm** is a 4-joint hobby arm (yaw, shoulder, elbow, wrist) plus a gripper, built bottom-up:

| module | what it does | verified how |
| --- | --- | --- |
| `arm_sim.py` | forward kinematics, closed-form inverse kinematics (elbow up/down, leaning back over the base), joint limits that fit a 180-degree servo, floor/base keep-out, static holding torque and servo selection, smooth joint-space moves, workspace map, SVG drawing | hand-worked poses, 1,600+ random FK-to-IK round trips, torque vs. hand calculation |
| `arm_gesture.py` | hand landmarks to arm targets: validation, arming (hand must be still first), glitch rejection, smoothing + dead-band, workspace clamping, hold-then-stop when the hand is lost | synthetic hands, 2,000-frame random session |
| `arm_bridge.py` | binary serial protocol (CRC-8, resync), host-side limits, and `FirmwareSim`, a model of the firmware's slew limit, watchdog and e-stop | framing fuzz tests, safety-rule tests, end-to-end gesture-to-firmware run |
| `arduino/arm_controller/arm_controller.ino` | the firmware: boots disarmed, deliberate arm, software e-stop latch, optional fail-safe hardware e-stop loop, watchdog, clamps, slew limit | **not compiled or run on a board**; tests check its constants and safety rules against the Python model |
| `arm_demo.py` | `--synthetic` runs the whole chain in simulation; `--camera` / `--port` for webcam and real hardware (asks you to type ARM); `--dry-run` prints commands and opens no port; `--record` saves landmarks for the gesture lab | synthetic mode tested; camera and serial modes **not tested** |

`docs/arm_pose.svg` shows an IK solution inside the reachable workspace (regenerate with
`python arm_demo.py --synthetic --svg docs/`). Prometheus can plan with it through the `arm_plan` tool, which
is labelled simulation-only in every result.

Everything about the arm is **simulation until it has run on real hardware**. Link lengths, masses and servo
torques are placeholders for a typical small arm: measure yours (`arm_sim.ArmSpec`, `Masses`). Whether
MediaPipe's landmarks are steady enough to drive it is untested, and is the first thing to try.

Hardware bring-up: follow **[docs/hardware/ARM_BRINGUP.md](docs/hardware/ARM_BRINGUP.md)** (power architecture,
power budget, two-channel e-stop, step-by-step checklist with pass criteria). The firmware boots **disarmed** and
moves only after a deliberate arm; `python -m eng.hil --port <port> --servo-power-disconnected` checks the board's
protocol, arming, e-stop latch and watchdog with the servos unpowered. None of this has been run on hardware yet.

## Engineering laboratory (`eng/`)

An integrated engineering lab built on the same principles: every model states its equations, assumptions and
validity range, is checked against analytic or published references, and is available to Prometheus (the
`engineering_lab` tool) and in the desktop app (**Engineering → Engineering lab**, with plots, experiment records and
reports). What has and has not been validated, and how: **[docs/VALIDATION.md](docs/VALIDATION.md)**. The genuine
development record, including what went wrong: **[docs/ENGINEERING_JOURNAL.md](docs/ENGINEERING_JOURNAL.md)**.

| Area | Models |
|---|---|
| Robot arm | recursive Newton–Euler dynamics, trapezoidal / cubic / quintic trajectories, servo torque–speed feasibility; ISO 9283 accuracy / repeatability benchmark planner and analyser; calibration records with provenance; gesture stress lab; bench hardware-in-the-loop checks |
| Structures | direct-stiffness 2-D trusses (determinate and indeterminate, support settlement) and 2-D rigid frames (Euler–Bernoulli, distributed loads) with equilibrium and conditioning checks |
| Machine design | Kt (Inglis), notch sensitivity and Kf, Marin-corrected endurance limit, Goodman / Soderberg / Gerber, Basquin life, DE-Goodman shaft sizing, bolted joints (ISO 898-1) |
| Design | mass vs safety factor vs deflection sweeps with constraint reports and a Pareto front |
| Aerospace | U.S. Standard Atmosphere 1976 to 86 km; isentropic flow, normal and oblique shocks, Prandtl–Meyer; ideal rocket nozzle (c*, CF, thrust, Isp, sensitivities); planar 3-DOF point-mass RK4 trajectory with timestep convergence |
| Control | discrete PID / state-feedback sandbox with noise, delay, saturation, rate limits, disturbances; discrete eigenvalue and Routh–Hurwitz stability |
| Method | GUM and Monte Carlo uncertainty, Type A/B measurement statistics; experiment records with provenance hash and exact re-run; reports in Markdown, HTML, JSON, CSV and PDF; SVG plots |

Reproduce the validation plots: `python tools/eng_benchmarks.py` (writes `docs/validation/`). Screenshots of the lab:
`docs/screenshots/engineering/`. Educational and experimental engineering, not certified design; no result is a
physical measurement until an experiment record with measured data says so.

## Reflection and evaluation

Prometheus measures its own tools (`reflection.py`). Every tool call is timed and classified (success,
failure, or refused by the operator - refusals are never counted against the tool). Stats persist to
`tool_stats.json`. When a tool keeps failing the same way, a short **lesson** is written into the memory
graph (`kind="lesson"`); gate rejections of proposed skills and self-patches become lessons too. Lessons
are recalled into later prompts when relevant (labelled as notes, not instructions), and a tool that is
failing right now gets a "Tool Reliability" caution in the system prompt. Error text is reduced to a short
single-line excerpt before it is quoted anywhere, and invented tool names share one stats bucket.
`/stats` and `/lessons` show it; `get_tool_stats` lets the model look too.

`python evals/run_evals.py` (`--quick` for seconds) writes `evals/results.json`: recall quality of the
memory graph vs. the original vector store, dedupe false-merge rate, entity-extraction precision/recall,
skill-gate and patch-gate detection rates, and a state-stress run. These are **synthetic benchmarks written
by the author** (small hand-made corpora, no LLM, no network). Read them as regression guards, not as claims
of general accuracy. Current results, for example: on the 25-query recall set the graph and the old vector
store are roughly on par (both lexical; neither can match a query with no shared words, like "glowing sphere"
for "orb") - the graph's advantages are structure, decay, dedupe and provenance, which this metric does not
measure.

## Autonomy guard rails (permissions, audit log, undo)

`safety.py` wraps what Prometheus is allowed to do on its own:

- **permissions.json** (optional, operator-owned; see `permissions.example.json`) can *deny* tools outright,
  require confirmation for extra tools (`ask`), and confine `write_file`/`edit_file` to listed folders
  (`write_scopes`). It can only make things stricter - an empty or missing file never loosens a built-in
  confirmation. A malformed file is reported (`/audit`) and the built-in rules stand. The GUI's explicit
  "auto-approve" setting is the operator's own switch and still overrides confirmations.
- **audit.jsonl** records every tool call (and every declined confirmation): tool, redacted arguments, outcome,
  latency. Entries are hash-chained, so editing, deleting or reordering a line is detected by `/audit`.
  Secrets (key-named fields, common key formats) are masked and long values truncated.
- **/undo** restores the previous content of the last file changed by `write_file`/`edit_file` (or removes a
  file Prometheus created). It refuses if the file was changed again afterwards, so it never discards your edits.
- The workspace write tools cannot touch Prometheus's own modules, `permissions.json`, `audit.jsonl`,
  `skills.json`, `tool_stats.json` or the undo journal: changing those is the operator's job.

Honest limits: the audit chain *detects* tampering but a process that can rewrite the whole file can still
replace it; undo covers the two workspace file tools, not shell commands; a shell command is only a tripwire
(see Known limits).

## Desktop GUI

`gui_orb.py` is a PyQt6 + OpenGL HUD around the same core: a streaming chat console with markdown and
code blocks (copy buttons), voice in (Whisper) and out (edge-tts), a confirmation dialog before any
dangerous tool runs, and a settings dialog. Supporting modules:

- `gui_markdown.py` - markdown to Qt HTML (everything the model writes is escaped first) and speech clean-up
- `gui_birth.py` - the start-up animation timeline and shader
- `gui_config.py` - validated, atomically-saved settings (`prometheus_config.json`, git-ignored)
- `gui_session.py` - session save/load, history repair and trimming (no Qt, fully testable)

Needs an OpenGL 3.3 capable display. Settings, session and crash logs are local files and git-ignored.

## Prometheus Desktop (`app/`)

An installable desktop application around the same core (nothing in the core is duplicated: the UI
calls `dispatch_tool`, so policy, audit log and undo apply as in the terminal). Sidebar sections:
Companion (the orb, streaming chat, inline approval cards, voice where installed), Memory,
Engineering, Forge, Workspace, Reminders & tasks, Obsidian, Robot arm (simulation), Reflection,
Trust & safety, Settings. Ctrl+K command palette, tray, single instance, start at sign-in (optional).

* Data: a source checkout that already has Prometheus data keeps using it in place; the installed app
  uses `%APPDATA%\Prometheus`. Override with `PROMETHEUS_HOME` / `PROMETHEUS_WORKSPACE`.
* Keys: saved from Settings into Windows Credential Manager (via `keyring`); `.env` still works and wins.
* Auto-approve: off by default, warns before turning on, shown in the status bar while on.
* Packaging: `packaging/` (PyInstaller + Inno Setup) and `.github/workflows/prometheus-desktop.yml`,
  which builds, self-tests, installs, upgrades and uninstalls on a Windows VM and uploads an
  **unsigned** installer as a workflow artifact; a GitHub release is published only by the workflow's
  `publish` job, after every Windows check has passed.

Design, security review, tests, limits and screenshots: [`docs/desktop-evolution/`](docs/desktop-evolution/).

## Tests

```
python -m unittest discover -s tests          # everything
python tests/stress_state.py                  # concurrency stress test (see above)
python evals/run_evals.py --quick             # synthetic benchmarks (see Reflection and evaluation)
python arm_demo.py --synthetic                # the gesture-to-arm pipeline in simulation
```

The GUI tests run Qt on its offscreen platform with audio, Whisper, edge-tts and OpenGL stubbed out, so
they need no display, microphone or GPU. They cover the worker/tool loop, console escaping, settings,
session handling and shutdown. They do **not** exercise the OpenGL shaders or real audio/speech paths -
those need a real display and devices.

## Known limits

- The destructive-command filter ("Conscience") is a tripwire for a few shell patterns, not a sandbox.
- Skills run in an isolated process, but without a Docker engine that isolation is resource limits only (no network or filesystem boundary) - hence the per-run confirmation.
- The patch gate needs the project's tests to be present and runnable; without them a self-patch is refused.
- Streaming responses are not counted in the usage log.
- The GUI's shader, microphone, speaker and Whisper paths are not covered by automated tests.
- Entity extraction without a model is rule-based (capitalised phrases, wikilinks, #tags, known names): it favours precision over recall, so pass entities explicitly when you know them.
- The Obsidian export has been tested against the file layout, not against a running Obsidian: open Graph View once and check it looks right.
- The arm is simulation only: no part of the Arduino firmware, the serial transport or the webcam path has been run on real hardware by the author. The arm IK round-trip eval checks self-consistency (FK then IK); forward kinematics itself is checked against hand-worked poses.
- `engineering_calc` covers determinate, linear-elastic textbook cases. It is a first check, not a substitute for FEA, a design code, or an engineer.
