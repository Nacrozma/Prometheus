# ORBIT — Autonomy and approvals

Autonomy decides **whether a step may start without your go-ahead**. It never changes the tool approval gate:
every tool with real-world effects asks, every time, in every mode.

| Mode | Steps that start on their own | Steps that wait for *Approve step* |
|---|---|---|
| Approval-first (default) | none | all |
| Balanced | thinking, reading/research, organising (reminders, tasks) | anything that changes files (Forge Builder/Debugger/Reconstructor) |
| Advanced | the kinds you tick (think, read, organise, change) | the rest |
| any | — | **manual** steps always (you do them) |

Set per session (per mission); the default for new sessions is remembered. Changing it updates the workflow too.

## Layers of approval (Prometheus)

1. Plan approval — nothing can be built from an unapproved version.
2. Step go-ahead — per autonomy.
3. Forge discipline gate — Architect read-only, Reconstructor new files only (refusals audited).
4. Tool approval card — what, why, affected paths, undo, data leaving the computer, diff; Approve/Deny equal weight.
   Auto-approve is **forced off** for ORBIT turns.

## Layers of approval (Atlas)

1. Plan approval and 2. step go-ahead — enforced in `atlas_core::orbit::apply` (the UI cannot skip them).
3. Atlas's existing approvals system and dock for every gated tool call; ORBIT records *awaiting approval* on the
   step while the dock waits.

## Never

* A plan or canvas node is never permission to act.
* Nothing irreversible runs unasked; restarts never repeat a step.
* No secrets are put into plans, prompts built by ORBIT or logs (plans hold only text you or the AI wrote).
