# ORBIT — Release readiness

**Status: released at the owner's request (2026-11-19)**: Prometheus 2.1.0 (ORBIT) and 2.2.0 (ORBIT + voice input
setup), ATLAS 0.5.0 (ORBIT + the 0.5.0 work). Earlier releases and their artifacts are untouched. The checks
below that are still open were not done before release.

| Item | Prometheus | Atlas |
|---|---|---|
| Implemented | yes | yes (core, commands, page) |
| Unit/integration tests | pass (498 / 2 skipped) | pass (core all, vitest 100) |
| Real-window visual QA | yes (10 screenshots) | **no** |
| Windows build/install CI | passed (runs 14, 15, 16) | atlas-release run 7 (checks + build before publish) |
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
