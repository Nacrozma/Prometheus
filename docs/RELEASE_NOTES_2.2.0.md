# Prometheus Desktop 2.2.0 — voice input, set up from inside Prometheus

Released 2026-11-19 at the owner's request. Unsigned installer. Everything in 2.1.0 (ORBIT) is kept; earlier
releases stay published unchanged.

## New: Settings → Voice → Set up voice input

* A guided setup: choose **Tiny** (75 MB, fastest), **Base** (142 MB, recommended) or **Small** (466 MB, most
  accurate), see exactly what is downloaded and from where, then *Download and set up* with a progress bar.
  Cancel at any time; nothing half-downloaded is kept.
* Downloads: the official whisper.cpp 1.8.2 engine from github.com/ggml-org/whisper.cpp and the model from
  huggingface.co/ggerganov/whisper.cpp. Each file is checked against its published SHA-256 before use; a file
  that does not match is deleted. Only the engine's own program files are unpacked.
* Speech is turned into text **on your PC**. Recordings stay in memory only while they are transcribed; the
  temporary audio file the engine reads is deleted immediately. Nothing is sent anywhere.
* Talk works in the **Companion** and in **ORBIT** straight away (no restart). No PyTorch needed.
* The Microsoft C++ runtime the engine needs is copied from Prometheus's own install folder, so it also works
  on PCs without the Visual C++ Redistributable.
* *Remove voice files* in the same dialog deletes everything it downloaded (`voice/` in your data folder).

## Verified

On GitHub's Windows VM before publishing: the real download of the engine and the Tiny model, checksum
verification, extraction and one transcription; plus the full test suite, the packaged app's self-test,
install, upgrade and uninstall. Not yet tried with a real microphone.
