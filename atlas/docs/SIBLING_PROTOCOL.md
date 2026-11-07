# Sibling Protocol v1

How ATLAS Co-Pilot talks to Prometheus. They stay two independent applications with separate owners,
databases, memories and credentials. Neither needs the other to work.

| Side | Code |
|---|---|
| Atlas (client) | `atlas/core/src/sibling/{mod.rs, protocol.rs, missions.rs}` |
| Prometheus (adapter) | `sibling_adapter.py` (repository root). `prometheus.py` is not modified. |
| Tests | `tests/test_sibling_adapter.py`, `atlas/core/tests/sibling_bridge.rs` (Rust against the real adapter) |

## Transport

* HTTP/1.1 `POST http://127.0.0.1:<port>/sibling/v1`. The default port is 47653.
* The **adapter** listens on `127.0.0.1` only. **Atlas never listens.** It connects out, without a proxy,
  only to `127.0.0.1` or `localhost`. Any other address is rejected when you enter it.
* The adapter refuses a request when any of these is true:
  * the peer address is not loopback;
  * the `Host` header is not `127.0.0.1:<port>` or `localhost:<port>` (defends against DNS rebinding);
  * the `X-Sibling-Protocol: 1` header is missing (a browser cannot send it cross-origin without a
    preflight, and the adapter never answers preflights);
  * the content type is not JSON;
  * the body is larger than 1 MB.
* Remote (non-loopback) transport is **not implemented**. The envelope already carries its own
  authentication. Remote use would add TLS with pinned keys, and it must not relax the rules above.

## Envelope

Every authenticated message, in both directions:

```json
{
  "protocol": "sibling/1",
  "type": "MISSION_CREATE",
  "id": "<unique message id>",
  "in_reply_to": "<request id>",
  "sibling_id": "sib_…",
  "ts": 1700000000000,
  "nonce": "<≥16 random hex chars, single use>",
  "payload": "<JSON object, serialised as a string>",
  "mac": "<hex HMAC-SHA256>"
}
```

* `in_reply_to` appears on replies only.
* `ts` is Unix time in milliseconds.
* `payload` is a **string**, so the MAC covers exact bytes and no cross-language JSON canonicalisation is
  needed.

The MAC is computed as:

```
mac = HMAC-SHA256(secret, "sibling/1\n{type}\n{id}\n{sibling_id}\n{ts}\n{nonce}\n{payload}")
```

The receiver rejects a message if any of these is true:

* the protocol is wrong;
* the sibling is unknown or revoked;
* `ts` is more than ±60 s from its clock;
* the nonce has been seen before (it keeps a replay cache);
* the MAC does not match (compared in constant time);
* the payload is malformed.

Atlas additionally checks that `in_reply_to` matches its request and that `sibling_id` is right. A reply that
fails verification is treated as no reply.

Known-answer vectors are asserted identically on both sides:

| Function | Inputs | Output |
|---|---|---|
| `envelope_mac` | key `01×32`, `HELLO`, `m1`, `sib_x`, `1700000000000`, `n×16`, `{"a":1}` | `aa6348e5…272ced` |
| `pair_proof` | `abcde-fghjk`, `request`, `atlas-1`, `00×32` | `538a95dc…b0c62e` |
| `derive_secret` | `abcde-fghjk`, `aa×32`, `bb×32`, `sib_x` | `4f4db99e…a3bdbe` |

## Pairing (`PAIR`, the only unauthenticated message)

1. Prometheus's owner runs `python sibling_adapter.py --pair`. The adapter prints a one-time code such as
   `ABCDE-FGH23`: 10 characters, 50 bits, valid for 5 minutes, single use. Five wrong attempts invalidate it.
2. Atlas sends a `PAIR` request. The payload is `{atlas_instance_id, atlas_name, atlas_nonce, proof}`, where
   `proof = HMAC(code, "sibling/1\npair\nrequest\n{atlas_id}\n{atlas_nonce}")`.
   **The code itself is never sent.**
3. The adapter verifies the proof, assigns a `sibling_id` and replies with
   `{sibling_id, prometheus_nonce, proof, prometheus_name, protocol}`, where
   `proof = HMAC(code, "…\naccept\n{atlas_id}\n{atlas_nonce}\n{prometheus_nonce}\n{sibling_id}")`.
   Atlas verifies this proof too. If it fails, something other than the adapter that printed the code
   answered, and pairing stops.
4. Both sides derive the same secret without sending it:
   `secret = HMAC(code, "…\nsecret\n{atlas_nonce}\n{prometheus_nonce}\n{sibling_id}")`.
   * Atlas stores the secret in the OS credential store (account `sibling:<id>`).
   * The adapter stores it with `keyring`. Without `keyring` it refuses to pair unless the owner passes
     `--allow-file-secret`, which writes a user-only file.

Threat model: a local administrator who can sniff loopback traffic is out of scope, as they already control
the machine. The code is short-lived, is shown only in the owner's terminal, and its HMAC proofs are sent once.

## Message types

| Type (request → reply) | Payload | Reply |
|---|---|---|
| `HELLO` → `HELLO` | `{atlas_version}` | `{prometheus_name, prometheus_version, adapter_version, protocol}` |
| `CAPABILITIES` → `CAPABILITIES` | `{}` | `{modes, providers, tools:[{name, description, dangerous, available_to_siblings}], dangerous_tools_policy}`, **discovered from Prometheus's own `TOOLS` table and `DANGEROUS_TOOLS`** |
| `HEALTH_CHECK` → `HEALTH_CHECK` | `{}` | `{status, providers, uptime_s, active_missions}` |
| `MISSION_CREATE` → `MISSION_ACK` | `{mission_id, idempotency_key, mode, objective, context}` | `{mission_id, accepted, duplicate, state, reason?}` |
| `MISSION_STATUS` → `MISSION_STATUS` | `{mission_id, after_seq, wait_ms ≤ 20000}` | `{mission_id, state, events:[MISSION_EVENT], result: MISSION_RESULT?}` |
| `MISSION_EVENT` → `MISSION_STATUS` | `{mission_id, kind: "message"\|"complete", text}` | as above |
| `MISSION_CANCEL` → `MISSION_STATUS` | `{mission_id}` | as above |

* A `MISSION_EVENT` is `{seq, kind, text, ts}`. `kind` is one of `message`, `atlas_message`,
  `tool_request`, `tool_result` or `result`.
* A `MISSION_RESULT` is `{outcome, summary}`.
* Adapter mission states are `accepted`, `running`, `waiting_for_atlas`, `completed`, `stopped`, `failed`,
  `cancelled`, plus `interrupted` (the adapter restarted) and `unknown` (no such mission for this sibling).

**Idempotency:**

* `MISSION_CREATE` with a known `(mission_id, idempotency_key)` returns the existing mission with
  `duplicate: true` and never starts it twice.
* The adapter persists keys and terminal results, so this survives an adapter restart.
* An interrupted mission is reported as `interrupted` and is never re-run.

## Modes on the Prometheus side

* **Consultation:** one answer from Prometheus's LLM router, with no tools.
* **Collaborative:** a review conversation with no tools. Prometheus answers, then waits (`waiting_for_atlas`)
  for Atlas's next message, until Atlas sends `complete`.
* **Delegated:** Prometheus runs its own tool loop (up to 8 steps).
  * Tools in `DANGEROUS_TOOLS` are **refused**, unless the owner started the adapter with
    `--allow-dangerous`. Even then, each one still needs the owner's `y/N` via Prometheus's own
    `_confirm_tool`.
  * Each tool request and result is reported as an event.

Every mission's system prompt starts with a preface telling Prometheus that Atlas is a peer, not its operator,
and that it must never reveal keys or private memory.

## Atlas side: Mission Ledger

* States: `DRAFT → PLANNED → AWAITING_APPROVAL → RUNNING → REVIEWING → COMPLETED`, plus `PAUSED`,
  `NEEDS_USER_INPUT`, `FAILED` and `CANCELLED`.
  * Allowed transitions are enforced in `missions::MissionState::can_go`.
  * Each transition is written as an event in an append-only log.
* **Sending** is the only side effect, and it happens only after the owner approves the exact payload. That
  payload is the objective plus the context the owner typed, and nothing else.
* **Retries** first ask `MISSION_STATUS` whether the sibling already has the mission.
* **Remote events** are stored once, keyed `UNIQUE(mission, source, remote_seq)`.
* **Remote → ledger state mapping:**

  | Remote state | Ledger state |
  |---|---|
  | `running` | `RUNNING` |
  | `waiting_for_atlas` | `NEEDS_USER_INPUT` |
  | `completed` / `stopped` | `REVIEWING` (the owner accepts it; Atlas never auto-accepts) |
  | `failed` | `FAILED` |
  | `cancelled` | `CANCELLED` |
  | `interrupted` / `unknown` | `PAUSED` |

* **Restart:** nothing is re-sent automatically. Running missions resume read-only polling, and a send that
  was in flight waits for the owner.
* Background sync polls running missions every 2 s and checks sibling health every 30 s. Both are no-ops when
  nothing is paired.

## What is never sent

Atlas never sends any of these:

* API keys or credentials
* settings
* memory
* conversation history
* files

The only exception is text the owner explicitly puts in a mission's objective, context or replies, and the
"What is shared" view shows exactly that. Sibling replies are untrusted input. They can never trigger an Atlas
tool, grant a permission or change a policy.
