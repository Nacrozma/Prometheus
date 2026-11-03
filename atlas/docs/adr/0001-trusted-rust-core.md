# ADR 0001 — All privileged logic lives in a Rust core library

**Decision.** Provider calls, credentials, tool execution, permission checks, approvals, tasks, memory and storage
are implemented once, in `atlas-core` (Rust). The Tauri shell exposes narrow commands; the UI never holds secrets
or executes tools.

**Why.** Secrets and permission enforcement must live in the trusted process. Duplicating orchestration in
TypeScript would create two owners for the same operation. A Tauri-free library is testable headless.

**Consequences.** The suggested `core/*` TypeScript folders were not created. Provider SDKs for TypeScript are not
used; Rust adapters speak each provider's HTTP API (Anthropic has no official Rust SDK).
