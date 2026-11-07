# Provider validation (Phase 7, Test B)

Date: 2026-11-07.

* **Keys:** none were available. The owner declined the credential request for this session.
* **Network policy:** reaches `api.anthropic.com`; blocks `api.openai.com`, `openrouter.ai`,
  `api.mistral.ai` and `api.cerebras.ai`.
* **Ollama:** not installable here, because model registries are blocked.

## Per provider

Legend:
* PASS = verified;
* MOCK = verified against a recorded wire format (wiremock), not the live API;
* BLOCKED = could not be tested here.

| # | Check | OpenAI | Anthropic | OpenRouter | Mistral | Cerebras | Ollama |
|---|---|---|---|---|---|---|---|
| 1 | Key entry (UI) | PASS (e2e) | PASS (e2e) | PASS (e2e) | PASS (e2e) | PASS (e2e) | n/a (no key) |
| 2 | Credential stored only in OS store | PASS | PASS | PASS | PASS | PASS | n/a |
| 3 | Masked display | PASS (`sk-ant…abcd`) | PASS | PASS | PASS | PASS | n/a |
| 4 | Connection test | MOCK | MOCK | MOCK | MOCK | MOCK | MOCK |
| 5 | Model discovery | MOCK | MOCK | MOCK | MOCK | MOCK | MOCK |
| 6 | Small real inference | BLOCKED | BLOCKED (no key) | BLOCKED | BLOCKED | BLOCKED | BLOCKED |
| 7 | Invalid credential | BLOCKED | **PASS (live)** | BLOCKED | BLOCKED | BLOCKED | n/a |
| 8 | Unavailable model | MOCK + catalog guard | MOCK | MOCK | MOCK | MOCK | MOCK |
| 9 | Timeout / rate limit | MOCK | MOCK | MOCK | MOCK | MOCK | MOCK |
| 10 | Remove key, reconnect | PASS | PASS | PASS | PASS | PASS | n/a |

**Live evidence for row 7:** `cargo test -p atlas-core --test live_providers live_invalid -- --ignored`:

```
LIVE    Anthropic: HTTP Some(401) → Auth · shown to the user: The provider rejected the API key. Check or replace it in Integrations. (invalid x-api-key)
BLOCKED OpenAI / OpenRouter / Mistral / Cerebras: not reachable from this machine
```

The made-up key was never echoed back.

**Rows 2, 3 and 10** come from unit tests that check the key never appears in SQLite, plus the Phase 7
secret scan. That scan covers the database, WAL, export, backup and diagnostics for both a provider key and
a sibling secret. On real Windows, the install test found no credential-like strings in the data folder.

## Running the live check yourself

Put keys in your shell (see `atlas/.env.example`). The app itself never reads them. Then run:

```bash
cargo test -p atlas-core --test live_providers -- --ignored --nocapture
```

The test reports each provider as PASSED, SKIPPED (no key) or a failure with the error. A provider without a
key is never reported as passed.

## Model routing

All of this is through the real engine, with a scripted provider. Test:
`routing_modes_send_the_tier_model_they_announce`.

| Mode | Expected | Result |
|---|---|---|
| Quality | Heavy tier model | PASS: provider received `heavy-model` |
| Budget | Fast tier model | PASS: `fast-model` |
| Balanced (Standard not set) | Steps to the nearest tier, reason explains | PASS: `heavy-model`, reason "Standard tier not set" |
| Manual | Default provider/model, tiers ignored | PASS: `mock-model` |
| Auto | Fast/Standard/Heavy by request | PASS (unit test `auto_mode_picks_tiers_from_the_request`) |
| Shut-down model in a tier | Skipped, reason given | PASS (`shut_down_models_are_never_routed_to`) |
| Shut-down model as default | Refused with reason and replacement | PASS |

What the UI shows (model and tier in the route chip) equals what was sent. Provider-reported tokens are
summed per served model.

**Budgets:**
* Per-request (worst case), daily, monthly and mission budgets are enforced, with warn, ask-first and stop.
  Unit tests: `budgets_warn_ask_and_stop`, `mission_budget_counts_only_that_mission`,
  `daily_request_limit_always_stops`.
* The engine refuses before anything is sent or stored: `budget_stop_refuses_before_anything_is_sent_or_stored`.

**Estimated vs actual cost:** Atlas shows **estimates** only (provider-reported tokens × the schedule).
No provider used here returns billed cost per request. That is labelled everywhere, and unknown prices stay
unknown.

## Pricing audit (sources checked 2026-11-07)

| Model | Seed rate (kept as given) | Classification | Source / note |
|---|---|---|---|
| claude-haiku-5-5 | 0.10 / 0.50 | **Verified current** (seed matches) | Anthropic pricing reference (cached 2026-10-06). Prompts > 100K tokens bill $0.50 / $2.50, not modelled |
| claude-sonnet-5-5 | 2.00 / 10.00 | **Verified current** (seed matches) | same |
| claude-opus-5-5 | 4.00 / 20.00 | **Verified current** (seed matches) | same |
| gpt-4.1-nano | 0.10 / 0.40 | **Unavailable**: shut down 2026-10-23 (replacement gpt-5.6-luna) | OpenAI deprecations page. Atlas no longer routes to it |
| gpt-5-nano | 0.05 / 0.40 | **Verified deprecated**: shutdown 2026-12-11 (replacement gpt-5.6-luna). Price not on the pricing page → historical | OpenAI deprecations page |
| gpt-4.1 | 2.00 / 8.00 | **Verified deprecated**: shutdown 2027-01-14 (replacement gpt-6-luna). Price not on the pricing page → historical | OpenAI deprecations page |
| gpt-5.4 | 2.50 / 15.00 | **Unverified**: not on OpenAI's pricing or deprecation pages | not found |
| gpt-5.5 | 5.00 / 30.00 | **Unverified**: not on OpenAI's pricing or deprecation pages | not found |

**Verified current OpenAI models**, added as separate verified rows (standard rates, contexts under 272K):

| Model | Input / Output per 1M tokens |
|---|---|
| gpt-6-astra | 10.00 / 50.00 |
| gpt-6.1-sol | 2.00 / 10.00 |
| gpt-6.1-terra | 1.00 / 5.00 |
| gpt-6-luna | 0.10 / 0.50 |

The seed rows were not changed. A rate you enter in Settings still wins over every source.
