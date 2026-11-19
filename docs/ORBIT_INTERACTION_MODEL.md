# ORBIT — Interaction model

## Layout (both products)

* **Top bar** — session picker, New session, session menu (rename/archive/delete, voice options in Prometheus),
  Autonomy selector, Outline/Orbit view toggle, Immersive.
* **Stage (left)** — phases are concentric orbits around the avatar; each phase name sits at the top of its orbit;
  tasks are bodies on their phase's orbit; dependencies are arcs with arrowheads. Under it: the workflow line
  (state, steps done) and only the workflow buttons that can act now.
* **Side panel (right)** — tabs *Conversation* (state line, transcript, level meter, Talk, Continuous, Stop speaking,
  End conversation, composer), *Step* (selected task: state with symbol and words, phase, priority, done by, waits for,
  result, history, edit controls, tool approval card in Prometheus), *Versions* (history, compare, restore, activity).

## Direct manipulation (stage)

| Input | Effect |
|---|---|
| Click a task | select (Step tab shows it) |
| Double-click / Enter | open in Step tab |
| Drag a task onto another orbit | move it to that phase (a new plan version) |
| Drag empty space | pan (Prometheus) |
| Wheel, `+`/`-`, `0` | zoom, reset |
| Arrow keys | previous / next task |
| Delete | remove the selected task (Undo restores) |
| Space (Prometheus canvas) | stop speaking, otherwise start/finish talking |

The **Outline** view lists the same plan phase by phase with status symbols and words — the accessible alternative
to the spatial view.

## Voice and text commands (local, no model needed)

`add task <name> [to <phase>]` · `remove task <name>` · `rename task <a> to <b>` · `make <task> high|normal|low priority`
· `<task> must come after <task>` · `move <phase|task> before <phase|task>` · `undo` · control words `stop`, `wait`,
`hold on` (stop speaking), `pause`, `resume`/`continue`, `cancel the workflow`. Ambiguous names are refused, never
guessed. Anything else goes to the AI.

## Separate controls (never merged)

| Control | Does | Does not |
|---|---|---|
| Stop speaking | silences speech now | touch the plan, workflow or turn |
| Pause (workflow) | no new step starts; the running step finishes | cancel anything |
| Cancel workflow (confirmed) | stops the running step, cancels unfinished steps | undo completed steps |
| End conversation | stops listening, speaking and the current reply | change the plan or workflow |

## Feedback

Toasts for results (Prometheus activity centre keeps them); the state line names the state in words; failures are
shown on the step with the error and offer Retry; restored sessions say what was paused and why.
