# Prometheus

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

## Desktop GUI

`gui_orb.py` is a PyQt6 + OpenGL HUD around the same core: a streaming chat console with markdown and
code blocks (copy buttons), voice in (Whisper) and out (edge-tts), a confirmation dialog before any
dangerous tool runs, and a settings dialog. Supporting modules:

- `gui_markdown.py` - markdown to Qt HTML (everything the model writes is escaped first) and speech clean-up
- `gui_birth.py` - the start-up animation timeline and shader
- `gui_config.py` - validated, atomically-saved settings (`prometheus_config.json`, git-ignored)
- `gui_session.py` - session save/load, history repair and trimming (no Qt, fully testable)

Needs an OpenGL 3.3 capable display. Settings, session and crash logs are local files and git-ignored.

## Tests

```
python -m unittest discover -s tests          # everything
python tests/stress_state.py                  # concurrency stress test (see above)
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
