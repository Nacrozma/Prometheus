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
- Synthesized tools run inside the main process; they need operator confirmation, but they are not sandboxed.
- Streaming responses are not counted in the usage log.
- The GUI's shader, microphone, speaker and Whisper paths are not covered by automated tests.
