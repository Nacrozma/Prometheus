# Real Prometheus integration (Phase 7, Test C/D)

Date: 2026-11-07. Environment: Linux container (Ubuntu 24.04), Python 3.13, Rust stable.

## What "real" means here, precisely

| Layer | In this test | How |
|---|---|---|
| Atlas core (SiblingBridge, ledger, engine) | **Real** | `atlas-core` library, same code as the app |
| Sibling Protocol v1 transport and crypto | **Real** | loopback HTTP, HMAC-SHA256, nonces, timestamps |
| Prometheus adapter | **Real** | `sibling_adapter.py` with `PrometheusBackend` (not `--test-backend`) |
| Prometheus runtime | **Real** | `import prometheus` from a disposable copy of the Prometheus files: its `RotatingLLMRouter`, `SYSTEM_PROMPT`, `TOOLS` (32), `DANGEROUS_TOOLS`, `dispatch_tool`, conscience check and the real tools (e.g. `engineering_calc`) |
| Language model | **Scripted stand-in** | `atlas/core/tests/support/scripted_llm.py` answers on Ollama's port (`localhost:11434`, Prometheus's keyless route). Every reply it writes starts with `[scripted stand-in LLM]`. |

**Why the model is a stand-in:** this environment's network policy blocks every model host:
* OpenAI, OpenRouter, Mistral and Cerebras;
* Ollama's registry and Hugging Face (so no local model weights can be downloaded).

The owner declined to provide provider keys for this session. The **only missing integration point is
model inference**. Everything between Atlas and Prometheus's model call, and everything Prometheus does with
the model's tool calls, ran for real.

The test is `atlas/core/tests/real_prometheus_runtime.rs`. It is ignored by default, runs in CI on Linux,
and runs locally with:

```bash
pip install openai python-dotenv numpy
cargo test -p atlas-core --test real_prometheus_runtime -- --ignored --nocapture --test-threads=1
```

## Results

| Check | Result | Evidence (from the run) |
|---|---|---|
| Prometheus starts independently (no Atlas) | PASS | `import prometheus` in 5.5 s; `llm_router.active_providers == ["ollama"]`, 32 tools |
| Atlas discovers and pairs with the adapter | PASS | one-time code from the adapter's output; `connected: true`, `test_peer: false`, name `Prometheus` |
| Capabilities come from the real runtime | PASS | reported tool names equal `prometheus.TOOLS` names exactly (32); providers `["ollama"]` from the real router |
| Health reported accurately | PASS | `{"status":"ok","providers":["ollama"],"active_missions":0}` |
| Consultation reaches Prometheus's real router | PASS (model stubbed) | the model request's system prompt contains Prometheus's own `SYSTEM_PROMPT` plus the sibling preface; the user message contains exactly the approved question and context |
| Delegated mission runs a **real** Prometheus tool | PASS | `engineering_calc(circular_orbit, altitude_m=400000)` returned `speed_m_s: 7668.558175407055`, matching `engineering.calculate` run separately |
| Prometheus's **real** dangerous-tool gate | PASS | `execute_shell` → `{"status":"refused","reason":"dangerous tools are not available to sibling missions"}` |
| Result goes to review, not auto-accepted | PASS | ledger `RUNNING → REVIEWING` |
| Disconnect detected | PASS | after the adapter is killed: `connected: false`, `last_error` "the sibling adapter is not running" |
| Running mission not left falsely "running" | PASS (after fix) | background sync → `PAUSED`, `remote_state = unreachable` |
| Reconnection with the stored pairing | PASS | adapter restarted with the same state (file secret store, `--allow-file-secret`) → `connected: true` |
| Restart without duplicate execution | PASS | restarted adapter reports the mission `interrupted`; ledger `PAUSED`; the model received **no** new request for it |
| Revocation invalidates the old credentials | PASS | `python sibling_adapter.py --revoke <id>` while the adapter runs → Atlas's next call: "the sibling no longer accepts this pairing" |

## Defect found and fixed: sibling missions could read Prometheus's private data (critical)

**Reproduction (before the fix):** a delegated mission asked Prometheus to `read_file private_notes.txt`, a
file in Prometheus's own folder holding a canary string. The real runtime returned the file's content to
Atlas. `recall_memory` also executed; it returned nothing only because the test copy's memory was empty.

**Root cause:** the adapter offered sibling missions every tool not in `DANGEROUS_TOOLS`. Prometheus's
non-dangerous tools include ones that read or change its owner's private state:
* memory, task scratchpad and schedule;
* usage history;
* self-modification proposals;
* the network (`web_search`).

Its file tools are confined to Prometheus's own folder, which holds `memory.json`, sessions, the audit log
and notes.

**Impact:** a peer (or a prompt-injected Atlas) could have pulled Prometheus's private memory and files into
Atlas. That breaks the "no merged private memory" rule.

**Fix (adapter only; `prometheus.py` unchanged):**

* Delegated missions use an explicit allowlist: `engineering_calc`, `arm_plan`, `synthetic_council`,
  `list_skills`, `get_router_status`, and `read_file` confined to the mission workspace.
* Dangerous tools are requestable only with `--allow-dangerous`, and only `write_file`, `edit_file`,
  `execute_shell`, `run_code_forge` and `run_skill`. Each one still needs the owner's y/N in Prometheus's
  terminal. `ghost_control`, `sculpt_workspace`, `synthesize_dynamic_tool`, `apply_pending_patch` and
  `export_obsidian` are never offered.
* File paths are confined to `sibling_missions/<mission_id>/`, which is seeded with `atlas_context.md`
  (the context the owner shared).
* Disallowed tools are not offered to the model and are refused again at execution. Capabilities report
  the real policy.

**Verification after the fix (real runtime):**

| Attempt | Result |
|---|---|
| `read_file private_notes.txt` | resolves inside the workspace and is not found |
| `../../private_notes.txt` | refused (outside workspace) |
| `/etc/hostname` | refused |
| `recall_memory`, `update_memory`, `web_search` | refused |
| `read_file atlas_context.md` | succeeds |

The canary never reached Atlas, and nothing was written into Prometheus's memory. Python unit tests:
`SiblingToolPolicyTests` (4).

## What Prometheus's owner must do for a fully live run

1. Configure a model for Prometheus: a key in its `.env`, or `ollama pull llama3.2` and run `ollama serve`.
2. In the Prometheus folder: `python sibling_adapter.py --pair` (install `keyring` first, or add
   `--allow-file-secret`).
3. In Atlas: Siblings → Pair, enter the code.
4. Run one consultation and one small delegated mission in a throwaway folder, and confirm the replies are
   real model text, not `[scripted stand-in LLM]`.
