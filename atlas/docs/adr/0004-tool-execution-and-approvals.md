# ADR 0004 — One execution gate; approvals bound to the exact action

**Decision.** `Dispatcher::execute_authorized` is the only caller of `Tool::execute`. Gated classes require an
approval whose stored hash equals `sha256(tool_id ‖ canonical_json(args))`, consumed atomically (single use).
Consequential always asks and destructive is always denied, regardless of settings.

**Why.** Enforcement must not depend on the model following instructions, and approvals must not be reusable or
transferable to changed arguments. **Consequences.** Retrying a write requires a new approval; Mission Control only
re-runs read-only, offline steps.
