# Architecture

## One owner per operation

```
┌──────────────────────── React UI (untrusted presentation) ────────────────────────┐
│ features/*  ·  state (zustand)  ·  lib/bridge.ts (typed, zod-validated IPC)       │
└───────────────▲───────────────────────────────────────────────┬──────────────────┘
   change events │ "atlas://changed"         invoke(cmd, args)    │ Channel<TurnEvent>
┌───────────────┴──────────── Tauri shell (src-tauri) ──────────▼──────────────────┐
│ commands.rs: the complete IPC surface · native dialogs (Rust-side) · nav guard     │
└───────────────▲───────────────────────────────────────────────┬──────────────────┘
                │                                               │
┌───────────────┴──────────── atlas-core (trusted) ─────────────▼──────────────────┐
│ engine ─ context ─ providers/routing ─ ai/{anthropic,openai}                       │
│ tools/{registry,dispatch,builtin} ─ policy ─ approvals ─ tasks                     │
│ memory ─ projects ─ conversations ─ grants ─ workspace ─ integrations ─ usage      │
│ map ─ audit ─ redact ─ credentials (OS keyring) ─ storage (SQLite, migrations)     │
└───────────────────────────────────────────────────────────────────────────────────┘
```

* **`atlas-core`** (Rust library, no Tauri dependency) owns every privileged operation: provider calls,
  credentials, tool execution, permission decisions, approvals, persistence. It is tested headless.
* **`src-tauri`** is a thin adapter: each command validates its input and calls one core method. File
  paths that leave the workspace only ever come from native dialogs opened from Rust.
* **The UI** renders state and sends user intent. It never sees a stored key, cannot read arbitrary files,
  and cannot execute a tool directly — only ask the core to run a conversation turn.

The prompt's suggested TypeScript `core/` folders were deliberately implemented in Rust (ADR 0001): secrets,
permissions and tool execution must live in the trusted process, and one implementation avoids
cross-language duplication.

## A conversation turn (`engine.rs`)

1. Validate the message; refuse a second concurrent turn in the same conversation.
2. Check usage limits (daily requests, monthly budget).
3. **Route** (`providers::route`): conversation override → default provider → its default model. A
   different provider is used only if cross-provider fallback is enabled, and the turn says so.
4. Build the tool list: enabled, available, not denied by policy, and only if the model accepts tools.
5. Retrieve **relevant** memories (FTS5/BM25 over global + active project, plus pinned), bounded.
6. Persist the user message with a delimited `<atlas_context>` block (time, memories) exactly as sent.
7. Assemble history within a character budget derived from the model's context window.
8. Loop (≤ `max_model_steps`): stream from the provider (bounded retries for 429/5xx/overload; cancel
   at any point) → persist the assistant message with its provider-native payload → for each tool call,
   `Dispatcher::run` → persist results → continue. Every tool call gets a result, executed or not.
9. Finish the task (`Verifying` → `Completed`/`Failed`/`Cancelled`) with a verification summary.

The system prompt is stable per conversation; per-turn context rides on the user message. History is
append-only and Anthropic content blocks (including thinking signatures) are replayed verbatim.

## Tool execution (`tools/dispatch.rs`)

`run` = lookup → enabled? → available? → valid JSON? → **schema-validate input** → record step →
`policy::decide` → (Ask: create approval bound to `sha256(tool_id ‖ canonical_json(args))`, wait) →
`execute_authorized`.

`execute_authorized` is the **only** caller of `Tool::execute`. It re-validates, recomputes the hash, re-runs
the policy, and for gated classes atomically **consumes** an approved, matching, unused approval. Then:
timeout + cancellation, **output schema validation**, output size cap.

## Task state machine (`tasks.rs`)

`created → running ⇄ awaiting_approval → verifying → completed | failed`, plus `cancelled`,
`interrupted` (set at startup for anything that was active — never resumed), `recoverable`. Transitions are
checked in a transaction; terminal states are final.

## Persistence

SQLite (bundled, WAL) with ordered migrations under `PRAGMA user_version`; each migration runs in its own
transaction and an existing database is snapshotted before upgrading. Tables: settings, projects,
conversations, messages (+FTS5), memories (+FTS5), tasks, task_steps, approvals, providers (no keys),
integrations (no keys), tool_state, file_grants, usage_records, audit_events (content-free).

## Events

* Per turn: a Tauri `Channel<TurnEvent>` (ordered): started, text/reasoning deltas, tool events,
  approval_required, persisted-message markers, notices, task updates, finished.
* Global: `atlas://changed {topic, id}` — the UI refetches the affected query (`useAtlasQuery`).

## Atlas Map (`map.rs`, `features/atlas-map`)

Built on demand from the registry, provider configs, integrations, memory, projects and tasks touched in
the last 30 minutes. Edges are real relationships (routes_to, serves, orchestrates, contains, requires,
uses, runs, invoked, scopes, belongs_to); an edge is `active` only while its step is pending, awaiting
approval or running. Layout is a deterministic radial placement with collision relaxation.
