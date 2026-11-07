# AI providers

All providers implement `ChatProvider` (`core/src/ai/mod.rs`): `list_models` and `stream_chat` with a
cancellation token and a streaming event sink. Errors are normalised to `ProviderErrorKind`
(auth, rate_limited, unavailable, bad_request, not_found, timeout, cancelled, network, decode, server,
overloaded) and redacted.

## Anthropic (`ai/anthropic.rs`)

* Raw HTTP to `POST /v1/messages` with `stream: true` (there is no official Rust SDK), `anthropic-version:
  2026-10-21`, key in `x-api-key`. No sampling parameters (rejected on this API version).
* Parses `message_start`, `content_block_start/delta/stop` (`text_delta`, `thinking_delta`,
  `signature_delta`, `input_json_delta`), `message_delta`, `message_stop`, `error`.
* **Replay:** assistant content blocks — including thinking blocks and signatures — are stored and sent back
  verbatim, keeping history append-only.
* Reasoning summaries (`thinking: {type: "adaptive", display: "summarized"}`) and `output_config.effort` are sent
  only when `/v1/models` reports the model supports them.
* Tools are sent with `eager_input_streaming: true`; every input is validated against its schema before use, and
  truncated JSON becomes an `INVALID_JSON` error rather than a partial call.
* `stop_reason: "refusal"` is surfaced as a notice; `max_tokens` stops tool execution.
* **Refusal fallback** (Settings → Models, on by default): for `claude-fable-5-1`, `claude-opus-5-5`,
  `claude-opus-5` and `claude-sonnet-5-5`, sends `fallbacks: "default"` with the `server-side-fallback-2026-07-01`
  beta header so Anthropic can re-run a declined request on its recommended model. When that happens, a
  `fallback` block appears and Atlas shows a notice; blocks before it are echoed per Anthropic's rules.
* Prompt caching: top-level `cache_control: {type: "ephemeral"}`; the system prompt is kept stable per conversation.
* Costs use Anthropic list prices (verified against Anthropic's pricing reference, 2026-10-06) and ignore cache
  discounts. They are always labelled estimates.

## OpenAI and OpenAI-compatible (`ai/openai.rs`)

* `POST {base}/chat/completions`, `stream: true`, `stream_options.include_usage`, Bearer key.
  `max_completion_tokens` for OpenAI itself, `max_tokens` for compatible servers.
* Streams text, `reasoning`/`reasoning_content` deltas where servers send them, and indexed tool-call deltas.
* `GET {base}/models` for the model list; capabilities are recorded as *unknown* (never guessed). If a model
  rejects tools, Atlas retries once without tools and says so.

## OpenRouter, Mistral, Cerebras

These are first-class provider kinds that use the same OpenAI Chat Completions adapter. Each has its own template,
base URL and key placeholder ("Paste your OpenRouter API key", and so on).

* OpenRouter (`https://openrouter.ai/api/v1`): sends an `X-Title: ATLAS Co-Pilot` attribution header. Model ids
  are vendor-prefixed (`anthropic/…`, `openai/…`).
* Mistral (`https://api.mistral.ai/v1`): `stream_options` is not sent, because Mistral rejects unknown fields.
  Tool-call ids are mapped deterministically to Mistral's required 9-character form, so a history that started
  with another provider still matches calls to results.
* Cerebras (`https://api.cerebras.ai/v1`): `stream_options` is not sent.

None of these, nor OpenAI or Anthropic, have been called live during development, because no keys were
available. To check them with your own keys, see `atlas/.env.example` and run:

```bash
cargo test -p atlas-core --test live_providers -- --ignored --nocapture
```

Providers without a key are reported as **SKIPPED**, never as passed.

## Ollama

Uses the OpenAI-compatible adapter against `http://127.0.0.1:11434/v1` with no key. Labelled **Local**
everywhere. Hardware: small models (3–8B) run on most recent laptops; 14B+ models want 16 GB+ RAM or a GPU.
Tool calling quality varies by model.

## Routing

`providers::route_tiered`, configured in Settings → Model routing.

* **Modes:**
  * **Auto** picks a tier per request. Short everyday text → Fast. Long engineering text, or the Architect,
    Debugger and Reconstructor disciplines → Heavy. Everything else → Standard.
  * **Budget**, **Balanced** and **Quality** always use Fast, Standard and Heavy respectively.
  * **Manual** always uses your default provider and model.
* **Tiers:** Fast, Standard and Heavy. Each is a provider you configured plus a model id.
* **A model chosen in the conversation always wins.**
* **Unusable tier:** if a tier's provider has no key, is disabled, failed authentication, or is a cloud
  provider while offline mode is on, Atlas steps to the nearest configured tier, then to your default. The
  reply's route chip and tooltip say which model was used and why.
* **Default provider:** if that is unusable too, Atlas shows an error with a fix. It only switches to another
  provider if *cross-provider fallback* is on, and then it announces "Your message will be processed by X".

## Pricing and budgets

`core/src/pricing.rs` keeps three sources apart. Every estimate records which one it used, in
`usage_records.price_status`.

| Source | Meaning |
|---|---|
| **verified** | Anthropic list prices, checked against Anthropic's pricing reference on 2026-10-06. |
| **unverified seed** | The rates supplied with the product brief: GPT-4.1 Nano 0.10/0.40, GPT-5 Nano 0.05/0.40, GPT-5.4 2.50/15.00, GPT-4.1 2.00/8.00, GPT-5.5 5.00/30.00 (USD per million tokens, input/output). The brief's Anthropic seed rows match the verified ones, and a test fails if they ever disagree. These rates have **not** been checked against OpenAI's pricing page, and the model ids are as given in the brief. |
| **your price** | Rates you enter in Settings → Usage & budgets. They win for that model id on any provider. |

* Routers (OpenRouter and other OpenAI-compatible services) are priced only when the model id names its vendor.
* Mistral and Cerebras models have **unknown** cost until you enter a price. Atlas never guesses.

Budgets (Settings → Usage & budgets):

* Limits: per request, per mission, per day and per month (in USD), a warning percentage, and a daily request
  limit.
* The per-request check uses a worst-case estimate: the prompt plus the full output allowance.
* When a limit would be exceeded, **Ask first** holds the message and lets you send it once anyway, while
  **Stop** refuses it. Budgets are checked before anything is sent or stored, and again before each later
  model step of a task.
* An unknown or unverified price, while budgets are set, produces a visible warning.

## Adding a provider kind

1. Implement `ChatProvider` in `core/src/ai/<name>.rs`, with wiremock tests for streaming, errors and cancellation.
2. Add a `ProviderKind` variant, a template in `ai/catalog.rs`, and a branch in `DefaultFactory::build`.
3. Add the kind to the UI schema (`src/lib/schemas.ts`).
