# ORBIT — Visual QA

## Prometheus (real window, xvfb, `tools/orbit_screens.py`)

Captured from the actual application against throwaway folders. **Sample data:** the plan is a sample reply passed
through the real parser (`orbit.extract_plan`) and recorded as a Prometheus-authored version; step states are
produced by the real state machine; the approval card is the real card from the real gate. No model was called.

| File | Checked |
|---|---|
| `01-orbit-empty.png` | empty state: the sun alone, one sentence, composer; no fake content |
| `02-orbit-plan-proposed.png` | draft v1, 8 tasks on 4 orbits, dependencies, labels outside the sun, “draft, not approved” |
| `03-orbit-edited-step.png` | voice-style edits as versions; Step tab with state in symbol + words; edit grid |
| `04-orbit-outline.png` | outline alternative: phases, symbols, words, priority, operation |
| `05-orbit-workflow-running.png` | approved, balanced; two steps ✓, one ▶ running; only valid buttons shown |
| `06-orbit-tool-approval.png` | approval card in the Step tab, step “? Awaiting your approval” |
| `07-orbit-versions-failed-step.png` | versions list with authors/reasons, compare text, failed step “!” with Retry |
| `08-orbit-immersive-listening.png` | immersive: no navigation/top bar; “Listening · microphone on” |
| `09-orbit-1280x800.png` | smaller window: everything fits, labels flip to stay on canvas |
| `10-orbit-reduced-motion-executing.png` | reduce motion, EXECUTING sign drawn still |

Issues found and fixed during QA: raw HTML in the plan line (rich text enabled); the sun drawn in a visible square
(smaller disc + vignette layer); orbit labels colliding with tasks (tasks start off the top of each orbit); clipped
labels (measured text width, flip near edges); truncated buttons (show only valid workflow buttons; voice controls
on two rows; step edits in a 3-column grid); launch animation covering captures (script finishes it).

Known cosmetic items: toasts can briefly cover the lower side panel; the activity list shows event kinds
(`step.running`) rather than sentences.

## Atlas

Not captured. The Atlas ORBIT page was verified by type-checking, lint and unit tests only; rendering it needs the
built Tauri app (WebDriver harness) or a full IPC mock, neither run in this session. **Visual quality of the Atlas
page is unverified.**
