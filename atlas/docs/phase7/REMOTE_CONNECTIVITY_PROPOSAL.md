# Remote sibling connectivity: readiness assessment and proposal (Phase 7, Test L)

**Status:**
* Remote connectivity is **not implemented**. Nothing in this document is built.
* Local-first remains the default.
* No listener or port was opened for this assessment.

## Where v0.2.0 stands

| Need | Today (local) | Ready for remote? |
|---|---|---|
| Transport | Plain HTTP on 127.0.0.1, adapter-side listener, Atlas never listens | **No**: needs TLS |
| Message authentication | HMAC-SHA256 over every envelope field, constant-time compare | **Yes**: the envelope is transport-independent |
| Replay protection | ±60 s timestamp + single-use nonce cache | Yes for HMAC replay; needs clock-skew handling across machines |
| Pairing | One-time 50-bit code, mutual HMAC proofs, code never sent | **No for remote**: 50 bits is safe locally (attacker needs local access) but too weak against an online or recorded-traffic attacker. Needs a PAKE or key exchange |
| Device identity | `atlas_instance_id` (random) and `sibling_id` | Partial: no keypair, so an identity can't be proven without the shared secret |
| Credential rotation | None (secret lives until revoked) | **No** |
| Revocation | Both sides; immediate effect | Yes, but remote needs revocation propagation when the peer is offline |
| Session expiry | None (per-message auth) | **No** |
| Reconnection | Read-only status reconcile, never re-sends | **Yes** (idempotency keys and the ledger are transport-independent) |
| Remote mission status | Polling | Works; long-poll is already supported (`wait_ms`) |
| User approval for remote actions | Approval before every send | Needs an explicit "this sibling is on another machine" warning |

## Proposed design (for a future phase)

1. **Keep the envelope and ledger unchanged.** Remote is a transport change, not a protocol rewrite. Bump
   to `sibling/2` only for the pairing exchange.
2. **Device identity:**
   * Each side generates an Ed25519 keypair at first run, stored in the OS credential store.
   * The public-key fingerprint is the device identity, shown as words for human comparison.
3. **Pairing:** to be designed in that phase, choosing one of:
   * SPAKE2 (PAKE) over the one-time code, so a recorded exchange can't be brute-forced offline;
   * a Noise `XX` handshake with the owner comparing short authentication strings on both screens.

   Both sides then pin each other's public keys.
4. **Transport:**
   * Mutual TLS 1.3 with pinned self-signed certificates (no public CA), or Noise over TCP.
   * The listener stays on the Prometheus side.
   * It binds to loopback by default.
   * Remote binding requires an explicit, visible owner setting naming the interface.
   * No UPnP or automatic port opening.
5. **Sessions:**
   * Short-lived session keys derived per connection.
   * HMAC session secret rotated on every reconnect, plus a maximum lifetime (for example 24 h).
   * Revocation lists exchanged on connect.
6. **Approvals:**
   * Any mission to a remote sibling shows its device fingerprint and network location before the
     owner approves.
   * Remote siblings default to Consultation only. Delegated mode requires a separate opt-in.
7. **Diagnostics:** latency, certificate fingerprints, last handshake, and clock skew. No green indicator
   without a verified handshake within the last 2 minutes (same rule as today).
8. **Firewall and exposure:**
   * Document the owner's firewall rule rather than automating it.
   * Prefer an owner-run VPN (WireGuard or Tailscale) over port forwarding.
   * Never expose the adapter to the public internet.

**Work estimate:** a dedicated phase. It needs new dependencies (TLS or Noise, Ed25519, SPAKE2) on both the
Rust and Python sides, a third-party security review, and tests on two machines.
