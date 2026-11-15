# Trust Center

What Atlas did, what it sent and where, and what it may do, built only from what Atlas recorded on this
computer. Added in 0.5.0 (stage 6, schema 8). Not released yet.

**Principles:** the Trust Center reads records; it never starts an operation and nothing it reads can.
Every permission it shows is one the core enforces at the moment an action runs; changing one goes
through the ordinary validated commands (settings, providers, grants). Nothing in it is sent anywhere.

## 1. The activity record (`audit_events`)

One table, existing since schema 1, extended in schema 8. Every row:

| Field | Meaning |
|---|---|
| id, ts | order and time (keyset pagination uses id) |
| kind | the specific event, e.g. `vault.passages` |
| category | knowledge, memory, tools, forge, providers, approvals, sibling, background, voice, settings, trust, system (derived from kind; old rows classified by the migration) |
| actor | user, atlas (on its own), assistant (the model, through a tool), sibling |
| resource | what it touched, by id or name (a tool, a document id, a conversation id, a mission) |
| project_id | when the event belongs to a project |
| provider, model | who processed it, when a model was involved |
| left_device | true when data went off this computer (a cloud model, an internet tool) |
| approval | requested, approved, declined, expired, cancelled, not_needed |
| outcome | ok, warning, failed, denied, cancelled |
| reversible | when known |
| op_key | stable key for retried operations (a tool step is recorded once) |
| detail | counts, ids, labels: redacted, never message, document or memory text, prompts or keys |

At most 50,000 rows are kept (oldest dropped); *Retention → audit days* can delete sooner. Clearing the
history (typed confirmation) is itself recorded. Export writes the record (content-free) to a JSON file the
owner chooses.

### What is recorded

| Area | Events |
|---|---|
| Models | `provider.request` for every request: provider, model, whether it left the computer, tokens as the provider reported them, cost as Atlas's estimate (flagged `cost_is_estimate`), duration, result |
| Knowledge Vault | `vault.import`, `vault.indexed`, `vault.failed`, `vault.reindex`, `vault.move`, `vault.remove`, `vault.passages` (which documents, how many passages, provider and model, whether it left the computer), `vault.passages_withheld` (local-only) |
| Memory | `memory.used` (ids, provider, model, left device), `memory.created` (by the owner, or by Atlas with approval), `memory.corrected`, `memory.updated`, `memory.confirmed`, `memory.outdated`, `memory.restored`, `memory.replaced`, `memory.deleted`, `memory.deleted_all` |
| Tools and files | `tool.step` for every tool run (tool, approval state, outcome, whether it used the internet), `approval.requested`, `approval.decided`, `approval.consumed`, `file.granted`, `tool.toggled`, `tool.not_offered` |
| Forge | `forge.project_added`, `forge.command`, `forge.commit`, `forge.reverted`, `forge.runs_interrupted` |
| Prometheus | `sibling.paired`, `sibling.revoked`, `mission.send`, `mission.contact_lost`, `missions.recovered` |
| Background | `scheduler.ran`, `scheduler.recovered`, `focus.start`, `focus.end`, `todo.deleted`, `tasks.recovered` |
| Settings and providers | `settings.updated`, `desktop.permission_changed`, `provider.added`, `provider.deleted`, `provider.tested`, `credential.stored`, `credential.removed`, `backup.created`, `backup.restored` |
| Trust Center | `trust.exported`, `trust.history_cleared` |

Notifications are not duplicated as events; their underlying operations are.

## 2. The page

* **Summary (7 days):** recorded activity, what was sent off this computer, problems, what is running now.
* **Running and waiting:** replying conversations, approvals waiting (with a link), scheduler (waiting,
  next, missed), Knowledge Vault processing and failures, missions, Forge commands, interrupted tasks.
* **Where your messages go:** every provider, local or cloud, default, requests (30 days), tokens as
  reported, estimated cost (labelled as an estimate; local models cost nothing; unpriced requests
  counted), last use; the default model, cross-provider fallback, offline mode.
* **What Atlas may do:** every enforced permission with what it allows, its state, its component, when it
  was last used, and a control.
* **Activity:** the timeline in plain sentences, filtered by area, by "left this computer", by problems,
  or by words (event, provider, model, item; never content), 40 at a time with "show older". Each event
  opens to its details.

## 3. Permissions shown, and where they are enforced

| Permission | Control | Enforced in |
|---|---|---|
| Changes on this computer (`permissions.local_write`) | Ask / Allow | `policy::decide_tool` in the dispatcher |
| Tools that use the internet (`permissions.network_tools`) | Ask / Allow | same |
| Changes to your task list (`permissions.planner`) | Ask / Allow | same (deleting a task always asks) |
| Offline mode (`network.offline_mode`) | switch | provider routing and the dispatcher |
| Memory in conversations, memory suggestions | switches | engine; `memory.save` availability and execution |
| Knowledge Vault in conversations, local-only | switches | engine; `vault.search` |
| Background activity (`schedule.paused`) | switch | scheduler |
| System notifications, global shortcut, voice | switches | notification centre, desktop shell, voice service |
| Each model provider | enable / disable | provider routing |
| Each folder granted outside the workspace | revoke | file grants |
| Paired siblings, enabled integrations | link to their page | sibling bridge, integration tools |

Destructive tool actions are always refused and consequential ones always ask; those are not settings.

**Revalidation:** the dispatcher decides from the settings as they are when the action runs (not as they
were when the turn started), and decides again after an approval arrives. A permission revoked while an
approval was waiting still stops the action (tested). The window cannot authorize anything: the UI only
calls the validated commands.

## 4. Schema 8

Additive; the database is copied to `atlas.pre-v8.bak` before upgrading.

* `memories`: `status` (checked), `confirmed_at` (filled from `created_at` for existing memories),
  `review_after`, `superseded_by`, `conversation_id`; index on status.
* `memory_history`: per-memory history, deleted with the memory.
* `audit_events`: the fields in §1; existing rows classified by kind and level; indexes on
  (category, id) and a unique partial index on `op_key`.

Tested: upgrade from v7 with memories, events and Vault documents kept and the memory index still
working; a retry is a no-op; upgrades from every earlier version (`every_earlier_schema_upgrades…`);
interrupted upgrades roll back (existing transactional runner).

## 5. Privacy

Everything above stays on this computer. Records hold names, counts and outcomes. Document titles appear
in `vault.passages` (the owner's own file names); tool names and provider names appear as resources.
What can leave the computer is decided elsewhere and recorded here: messages (with attached memories and
passages) to a cloud model the owner configured, and queries to internet tools the owner allowed.

Measured (debug build): 5,000 events written in 346 ms; one filtered page in 0.45 ms (`core/tests/trust.rs`).
