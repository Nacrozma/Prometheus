# ADR 0003 — Predictable routing, no silent provider switching

**Decision.** Route by conversation override, then the default provider and its default model. Capabilities from
the provider's model list gate tools, reasoning summaries and effort. Switching provider requires an explicit
setting and is announced in the conversation.

**Why.** Changing provider changes who processes the user's data. **Consequences.** A failing default provider
produces an actionable error instead of a quiet fallback.
