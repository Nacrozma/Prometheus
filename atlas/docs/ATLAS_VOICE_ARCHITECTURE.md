# Atlas Voice: architecture

Stage 2 (0.4.0). This page covers what exists.
* Models, sizes and measured speed: VOICE_MODELS_AND_BENCHMARKS.md.
* Problems and fixes: VOICE_TROUBLESHOOTING.md.

## Principles

* **Local-first.** Speech recognition and speech output run on the owner's computer.
* **No keys, no services.** No API key, paid service or internet connection is needed once the files
  are downloaded.
* **Downloaded on request.** Files come only from a pinned list, and each is checked against its
  publisher's SHA-256. Nothing is bundled into the installer, which stays about 9 MB.
* **Voice is optional.** It is off by default, and Atlas works fully without it. A missing or broken
  model never affects text conversation.
* **One conversation pipeline.** A spoken request becomes an ordinary message in the composer and
  follows the same context, permissions and safety rules as typed text. Replies are ordinary replies
  that can also be read aloud.
* **Real audio only.** The voice ring moves with the actual playback or microphone signal, read from
  a Web Audio analyser. Nothing is simulated from timers or text length.

## The six parts

| Part | Where | What it does |
|---|---|---|
| A. Speech recognition (STT) | `core/src/voice/stt.rs` | `SpeechToText` trait; `WhisperCli` (whisper.cpp 1.8.2); single-flight; 0.3–120 s recordings |
| B. Text-to-speech (TTS) | `core/src/voice/tts.rs` | `TextToSpeech` trait; `SherpaTts` (sherpa-onnx 1.12.40 running Piper voices); text sanitised and length-capped |
| C. Playback and streaming | `src/features/voice/audioEngine.ts` | Sentence queue, synthesised one ahead of playback; volume; pause, resume and stop |
| D. Microphone | `src/features/voice/audioEngine.ts`, `public/voice-capture.worklet.js` | Push-to-talk capture via `getUserMedia`; samples are collected on the audio thread by an AudioWorklet (ScriptProcessor only as a fallback), held in memory, downsampled to 16 kHz and cleared after recognition. Output device selectable where the web view supports `setSinkId` (WebView2). **Voice check** (`VoiceCheck.tsx`, `voiceCheck.ts`) measures real hardware; see VOICE_HARDWARE_VALIDATION.md |
| E. Visualisation | `src/features/voice/VoiceRing.tsx`, `ringShader.ts` | WebGL2 ring driven by a 64-band spectrum from the live analyser; 8 states |
| F. Orchestration | `src/state/voice.ts`, `VoiceProvider.tsx` | State machine, shortcuts, reading replies as they stream, transcript to composer |

**Supporting modules:**
* `catalog.rs`: pinned downloads.
* `download.rs`: verified installs.
* `hardware.rs`: local capability report.
* `wav.rs`: audio formats.
* `mod.rs`: the service and the app-facing API.

**Commands:** `src-tauri/src/commands.rs` (`voice_*`).

## Engines and why

| | Chosen | Why | Rejected |
|---|---|---|---|
| TTS runtime | **sherpa-onnx 1.12.40** (Apache-2.0; the last 1.x release) | Maintained project, CPU-only, prebuilt Windows binaries. Pinned to 1.x because sherpa-onnx 2.0 removed the built-in espeak-ng phonemizer, so Piper voices produce no audio there without a separate phonemizer (found by the real-engine CI run, which failed on 2.0.1 on Windows and Linux). Runs Piper voices, which are packaged on GitHub with published checksums. Also supports Kokoro, so higher-quality voices can come later without changing engines. | The Piper binary (`rhasspy/piper` 2023.11.14-2): archived Oct 2025, no fixes. piper1-gpl: GPL-3.0 Python/C library with no standalone Windows binary. OS speech (Web Speech API): its audio can't be analysed, so the ring could not be real. |
| Voices | **Piper VITS**, medium quality, 22 kHz, about 67 MB each (an 8-bit variant is 21 MB) | Natural enough, fast on CPUs, wide language coverage, including Arabic. | Kokoro (126–348 MB, slower): a candidate for a later "high quality" option. |
| STT runtime | **whisper.cpp 1.8.2** (MIT) | The newest release with Windows binaries (the 1.9.x releases are source-only). CPU, no GPU. | — |
| STT models | **Whisper** tiny / base / small / large-v3-turbo-q5 (ggml) | Multilingual, MIT. Base is the starting recommendation; the benchmark decides. | large-v3 (2.9 GB): too large for a default. |

**Licensing:**
* Each item's licence is shown in Settings → Voice before download.
* espeak-ng (GPL-3.0) pronunciation data ships inside the Piper voice packages and is used by the
  separate sherpa-onnx program. It is never linked into Atlas.

## How a request flows

1. **Talk.** Ctrl/⌘+Shift+Space or the microphone button starts capture; a red "Microphone on" indicator
   shows. Press again to finish, or Esc to cancel.
2. **Transcribe.** The recording, 16-bit samples at 16 kHz, goes to the core as raw bytes. The core:
   * writes a temporary WAV under `<data>/voice/tmp`;
   * runs `whisper-cli` through the Forge runner (no shell, scrubbed environment, time limit, kill on
     cancel);
   * deletes the WAV and returns the text.

   Only one transcription runs at a time.
3. **Review.** The text appears in the composer for editing; with "send automatically" on, it is sent
   at once. It is a normal message from here on.
4. **Reply.** Atlas answers through the normal conversation engine.
5. **Speak.** With "read replies aloud" on:
   * complete sentences are taken from the streaming reply (`SentenceStream`);
   * code blocks and tables are announced, not read;
   * Markdown, links and emoji are cleaned;
   * each sentence is synthesised by `sherpa-onnx-offline-tts` into a temporary WAV, which is read and
     deleted;
   * the audio is played through Web Audio, and the ring follows the analyser.
6. **Interrupt.** Esc or Stop:
   * silences playback at once and discards queued sentences;
   * kills any synthesis in progress;
   * leaves the reply text untouched and sends nothing new.

   A reply that is retried mid-stream (`step_reset`) or cancelled stops speaking too.

## State machine (ring)

| State | Shown when | Look |
|---|---|---|
| idle | Voice ready, nothing happening | Slow breathing glow, 20 fps |
| listening | Recording | Inward ripples; the waveform follows the microphone spectrum |
| processing | Transcribing, waiting for the reply, or synthesising the first sentence | An energy arc travelling round the ring |
| speaking | Playing speech | Ring radius and brightness follow the playback spectrum and loudness; sparkles |
| paused | Playback paused | Settled, dim |
| interrupted | 0.7 s after a stop | A quick fade back |
| error | A voice problem is shown | Restrained amber |
| offline | Voice off or not set up | Grey, still |

The ring:
* never claims a state the audio engine isn't in;
* renders nothing while the window is hidden;
* draws one still frame per state change under reduced motion, with no animation loop;
* falls back to a static SVG ring when WebGL2 is unavailable.

## Security and privacy

* **Downloads:**
  * HTTPS only, from the pinned catalog (GitHub releases and Hugging Face).
  * Streamed with a size cap and SHA-256 verified before use.
  * Unpacking refuses absolute paths, `..` and symbolic or hard links, and limits file count and total
    size.
  * Per-file hashes are kept, so "Verify" detects later tampering.
  * Cancel or failure leaves nothing behind.
  * Offline mode refuses downloads.
* **Engines:**
  * They are separate processes, never given a shell.
  * They get a scrubbed environment (credential variables removed), a time limit and a process-tree
    kill on cancel.
  * Text is passed as one argument, never parsed as an option (leading dashes are stripped).
  * Engine output is treated as untrusted audio or text.
* **Audio:**
  * Recordings stay in memory and are zeroed after use.
  * Temporary WAVs exist only for one engine call, and any left over are removed at startup.
  * No audio, transcripts or engine output go to logs, diagnostics or the audit log. The audit log
    records only item ids for installs and removals.
* **Microphone:**
  * Push-to-talk only; no background listening.
  * The system permission prompt and Windows' own microphone indicator apply, and Atlas shows its own.
  * The stream is released the moment listening stops.
* **Sharing:**
  * Transcripts are ordinary messages: never saved to memory automatically, and never sent to
    Prometheus.
  * Voice has no sibling path at all.

## Cloud extensibility (not implemented)

`TextToSpeech` and `SpeechToText` are the seams. A future cloud engine would be another
implementation, selected explicitly in Settings with:
* its own key in the credential store;
* consent text saying what audio or text leaves the device;
* routing through the budget checks.

Atlas never switches to a paid or cloud engine on its own. None exists in 0.4.0.

## Tests

| Level | File | Covers |
|---|---|---|
| Rust | `core/tests/voice.rs` (9) | Verified install, progress, no re-download, tamper detection, damaged state, corrupt or oversized downloads, unsafe archive paths and links, cancellation, duplicate download refused, offline refusal, settings validation, engine wrappers via test scripts (exact arguments, speed, cleanup, cancel kills a hung engine, failure reported), stand-in engines |
| Rust | `voice::*` unit tests (9) | Catalog pinning, WAV, resampling, sanitising, language codes, transcript cleanup, recording bounds, hardware recommendation, word accuracy |
| Rust (CI, real) | `core/tests/voice_real_engines.rs` | Real downloads and hashes; real synthesis; real recognition of that speech; cancel; benchmark |
| Vitest | `speech-text.test.ts` (6), `voice.test.tsx` (9) | Speakable text, streaming sentences, code fences; playback queue order, one-ahead synthesis, stop and late results, pause and resume, errors; band analysis; phases; static ring; push-to-talk store |
| e2e | `tests/e2e/app.e2e.mjs` (2 voice tests) | Real app: corrupt download refused; verified install; push-to-talk with the stand-in microphone; transcript edited and sent; reply spoken through real Web Audio (analyser level checked); Esc stops it with text intact and no re-send; settings persist; offline speech works and downloads are refused; microphone loss handled; reduced motion stills the ring; no audio files left |
