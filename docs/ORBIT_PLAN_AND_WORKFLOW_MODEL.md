# ORBIT — Plan and workflow model

## Plan (what should happen)

`title, objective, outcome, phases[], tasks[{id, title, phase, detail, priority high|normal|low, estimate, status
proposed|confirmed, operation}], deps[{from, to}] (from finishes before to), assumptions[], questions[], risks[]`.

* Produced by the AI as one fenced ```` ```orbit-plan {json} ``` ```` block per reply (instruction in the system/context
  prompt), or by your edits. Text is bounded, ids made unique, unknown phases added, unknown operations become the
  ordinary AI turn, and any dependency that would close a loop is dropped (on load) or refused (on edit).
* While a reply streams, phase names and task titles that have fully arrived appear as **provisional** dashed
  bodies; the complete block replaces them.
* Tasks from the AI are **proposed** until you approve the version; approving confirms them.

## Versions

Every change creates a version: number, plan, author (you / Prometheus or Atlas), why, time. *Undo* and *Restore*
create a new version with the old content (history is never rewritten). *Compare* lists added/removed/renamed/
moved/re-prioritised tasks, phase order and dependency changes. A workflow records the version it came from.

## Workflow (how it will be done)

Built only from the **approved, active** version. One node per task, in dependency order (phase order otherwise).

| Operation | Prometheus runs it with | Atlas runs it with |
|---|---|---|
| assistant / atlas | a Prometheus turn in its own conversation | an Atlas turn in its own conversation |
| forge:architect/builder/debugger/reconstructor | Forge discipline prompt + `forge_missions.decide` gate | — |
| research | — | an Atlas turn told to investigate and not change anything |
| reminder / todo | the `schedule_task` tool (asks for approval like any tool) | `orbit_run_todo` → one task in Tasks |
| manual | nothing: you mark it done | nothing: you mark it done |

A node added to the canvas executes nothing; only *Start* / *Approve step* run a node, through the paths above.

## States and transitions

`draft → ready | waiting | cancelled` · `waiting → ready | cancelled | blocked` · `ready → awaiting_approval |
running | paused | cancelled | waiting` · `awaiting_approval → running | cancelled | paused | ready` ·
`running → completed | failed | paused | cancelled | awaiting_approval` · `paused → ready | cancelled` ·
`failed | blocked → ready | cancelled` · `cancelled → ready` · `completed` is final.

Side effects: completing a node makes waiting dependants ready; failing/cancelling blocks dependants; retrying
unblocks them. Workflow state is derived (completed, running, awaiting approval, paused, failed, cancelled, ready).
Every transition is appended to the node history with time and detail. Controls are enabled only when the
transition exists.
