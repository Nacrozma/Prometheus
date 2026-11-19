# ORBIT — Release readiness

**Status: implemented and tested on Linux; not released.** No release was published; Prometheus Desktop 2.0.0 and
its artifacts are untouched.

| Item | Prometheus | Atlas |
|---|---|---|
| Implemented | yes | yes (core, commands, page) |
| Unit/integration tests | pass (498 / 2 skipped) | pass (core all, vitest 100) |
| Real-window visual QA | yes (10 screenshots) | **no** |
| Windows build/install CI | not yet observed for the ORBIT commit | Atlas workflow queued at hand-off |
| Real model turn producing a plan | not verified | not verified |
| Real microphone/speaker | not verified | not verified |

## Before a release (owner decision)

1. Green Windows workflow for the ORBIT commits; install the build and try ORBIT with a real provider and voice.
2. Atlas: run the WebDriver e2e and look at the ORBIT page in the real app.
3. Decide version numbers (Prometheus 2.1.0? Atlas 0.6.0?) and release notes.
4. Explicit authorisation to publish.

## Known limitations

No spoken barge-in (mic paused while speaking); Prometheus hotkeys are in-app only; Atlas steps do not yet include
specialists/Forge; Prometheus Workspace/Forge pages lack dedicated ORBIT buttons; session saves grow with versions;
Whisper is not bundled in the Prometheus installer (voice input needs it installed).
