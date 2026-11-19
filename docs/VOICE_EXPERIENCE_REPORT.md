# Prometheus 2.3.0 — complete voice experience: report

Published 2026-11-19 (owner-authorised): https://github.com/Nacrozma/Prometheus/releases/tag/prometheus-desktop-v2.3.0
Installer SHA-256 `dae9a3966805d630b4bdb56a8ef192c3146e9aa4ce787f65aa8c5aab1ac55ccb` (52 MB). Windows run 18, commit `b3d8e68`.

## A. Architecture
* Inspected: `gui_orb.TTSManager` (edge-tts, synthesis + playback threads), Companion and ORBIT (each had its own
  TTSManager), desktop settings, `gui_config` (old voice/speed/on-off), voice input (`local_stt`), Windows workflow.
  Atlas's local TTS (sherpa-onnx + Piper voices, `atlas/core/src/voice/catalog.rs`) was read as a reference; no code
  was shared — Prometheus downloads, stores and runs its own copy.
* Engine chosen: **sherpa-onnx 1.12.40 `sherpa-onnx-offline-tts`** (Apache-2.0), Windows "MT" build (C++ runtime built
  in), run as a separate process like whisper.cpp. Why: offline, small (23 MB engine, 65 MB per voice), proven on
  Windows, no new Python dependency, no PyTorch, speed via length scale. Checksums computed from the real archives.
* Shared service: `app/services/speech.py` `SpeechService` (one text queue, synthesis ahead of playback, one player,
  `stop()` cuts within one audio block, honest `test()`), engines `LocalEngine` / `MicrosoftEngine`; Qt wrapper
  `app/ui/speech_bridge.py` owned by the main window and given to Companion, ORBIT and Settings.

## B. Features
Settings → Voice → Spoken replies (on/off, engine with Microsoft disclosure confirmed first, installed voices only,
speed 0.5–2.0×, Test voice, Stop, local voice set-up/repair/removal with sizes and licences); Companion and ORBIT on
the same service; the avatar speaks only during real playback; ORBIT continuous conversation resumes after speech
ends, fails or is off; no engine fallback; code, plan data, links and markup are never spoken.

## C. Files
New: `app/services/speech.py`, `app/ui/speech_bridge.py`, `app/ui/voice_settings.py`, `tests/test_speech.py`,
`docs/RELEASE_NOTES_2.3.0.md`. Changed: Companion, ORBIT, Settings, main window, theme (radio buttons), settings
defaults, start-up migration, Windows workflow. Dependencies: none added (edge-tts, soundfile, sounddevice, numpy
were already bundled).

## D. Testing
* Linux: 530 passed, 2 skipped (20 new speech tests: setup, checksum mismatch, cancel, disk space, safe extraction
  incl. links and `..`, removal not touching Whisper files, text cleaning, chunking, speed, engine command, errors,
  queue order, stop, no fallback, honest test, migration, settings UI).
* Windows CI (real): engine + Alba voice downloaded and checksum-verified, **speech generated: 3.19 s at 22 050 Hz in
  1.77 s, RMS 0.0485**; at 1.5× the same sentence was 2.55 s. Playback: **not possible on the runner** ("Error
  querying device -1" — no audio device). Full test suite, packaged self-test, install, upgrade (data kept),
  uninstall: passed.
* Not performed: listening on a real speaker; Microsoft online speech in CI; running the downloaded engine in the
  Linux container (blocked by the session's permission policy, not worked around).

## E. Security and privacy
Local engine: reply text stays on the computer (passed to a local process); Microsoft: reply text goes to Microsoft,
shown and confirmed before use; no automatic switch between engines; voice input audio never leaves the computer.
Downloads: pinned github.com URLs, SHA-256 before use, `.part` files, cancel, size limit, disk check, extraction of
regular files only inside the archive folder.

## F. Release
2.3.0 published (run 18). Earlier releases untouched. Upgrade keeps 2.2.0's Microsoft voice settings; fresh installs
start local. Known issues: playback not heard in CI; Lessac and Ryan voices are non-commercial licences.

## G. Recommendation / next
Owner test on a real PC: Settings → Voice → Set up local voice → Test voice; then ORBIT continuous conversation.
Next: device selection for output, more voices/languages, showing generation latency, legacy HUD (`gui_orb.py`) still
uses its own edge-tts player.
