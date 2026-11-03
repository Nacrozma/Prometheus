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
* Costs use Anthropic list prices (snapshot 2026-10-06) and ignore cache discounts — always labelled estimates.

## OpenAI and OpenAI-compatible (`ai/openai.rs`)

* `POST {base}/chat/completions`, `stream: true`, `stream_options.include_usage`, Bearer key.
  `max_completion_tokens` for OpenAI itself, `max_tokens` for compatible servers.
* Streams text, `reasoning`/`reasoning_content` deltas where servers send them, and indexed tool-call deltas.
* `GET {base}/models` for the model list; capabilities are recorded as *unknown* (never guessed). If a model
  rejects tools, Atlas retries once without tools and says so.

## Ollama

Uses the OpenAI-compatible adapter against `http://127.0.0.1:11434/v1` with no key. Labelled **Local**
everywhere. Hardware: small models (3–8B) run on most recent laptops; 14B+ models want 16 GB+ RAM or a GPU.
Tool calling quality varies by model.

## Routing

`providers::route`: conversation override → default provider (and its default model). Unusable provider →
error with a fix, unless *cross-provider fallback* is on, in which case Atlas picks a connected alternative
and announces "Your message will be processed by X". Offline mode allows only local providers.

## Adding a provider kind

1. Implement `ChatProvider` in `core/src/ai/<name>.rs`, with wiremock tests for streaming, errors and cancellation.
2. Add a `ProviderKind` variant, a template in `ai/catalog.rs`, and a branch in `DefaultFactory::build`.
3. Add the kind to the UI schema (`src/lib/schemas.ts`).
