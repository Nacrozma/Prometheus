# Integrations

The catalog lives in `core/src/integrations.rs`. Each entry declares a category, description, capabilities,
auth type, permission scope, setup text and whether it is **implemented**. Unimplemented entries are shown as
"Planned — not available in this version" and cannot be enabled or given a key.

| Integration | Status | Notes |
|---|---|---|
| Web search (Tavily) | Implemented | `POST https://api.tavily.com/search`, Bearer key. Sends only the query. Asks before each search by default. *Test* uses one search credit. |
| Email, Calendar, Task manager, Cloud files | Planned | OAuth; sending or modifying will be `Consequential` (always asks) |
| Git repositories | Planned | Read-only first |
| Speech-to-text | Planned | Push-to-talk only; local vs cloud chosen explicitly |
| Custom HTTP tools | Planned | Untrusted, out-of-process, declared permission class |

## Adding an integration

1. Add a catalog entry (`implemented: true` only once it works).
2. Store credentials with `integrations::set_key` (OS credential store, masked hint only).
3. Expose capabilities as tools whose `requires` lists the integration id; `availability` reports
   `NeedsConfiguration` until it's set up. The map draws `tool → integration` edges automatically.
4. Implement a real `test` path and record status with `integrations::set_status`.
5. Prefer OAuth (with PKCE and loopback redirect) for services that support it; never assume an API key grants
   permission for every operation — map each operation to a permission class.
