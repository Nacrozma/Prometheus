# ORBIT — Voice specification

## Prometheus

* **Input**: `WhisperVoiceThread` (Whisper on this computer). Not bundled in the Windows installer; without it the
  Talk button is disabled with the reason, and typing works.
* **Continuous conversation (default)**: Talk opens the mic; `TurnTaker` reads the real input level (~25/s) and ends
  your turn after `orbit_silence` seconds (default 1.2) of quiet following ≥0.35 s of speech; coughs/clicks are
  ignored; steady background noise raises the threshold (adaptive floor); 30 s with no speech closes the mic.
  After Prometheus finishes speaking (playback no longer busy), ORBIT listens again — but not while a step runs or
  an approval waits, and not after *End conversation*.
* **Push-to-talk**: untick Continuous; Talk starts, Talk again sends.
* **Output**: `TTSManager` (edge-tts: reply text goes to Microsoft's speech service — stated in the panel; mute speech
  in Settings → Voice to stay local). Plan blocks are never spoken.
* **Interruption**: Stop speaking, Space (canvas), Esc, or Talk. The mic is paused while Prometheus speaks (no echo
  cancellation in this audio stack), so spoken barge-in is not offered.
* **Options**: session menu → Voice options (silence seconds 0.6–4, sensitivity 0–1).

## Atlas

* **Input**: Atlas's whisper.cpp engine through `useVoice` (`startListening/stopListening`, draft transcript).
  In ORBIT the transcript is sent as your message (shown in the transcript).
* **Continuous**: `TurnTaker` (TypeScript) on `audio.level()`; listens again when playback goes from speaking to idle.
* **Output**: Atlas's sherpa-onnx voice (on this computer), spoken by the existing VoiceProvider when *read replies
  aloud* is on.
* **Interruption**: Stop speaking, Esc (existing voice shortcut), Talk.

## Truthfulness (both)

LISTENING only while the mic is open (with “microphone on”), SPEAKING only while audio plays, avatar reacting to
the real level. No audio is stored by ORBIT; nothing is recorded silently.
