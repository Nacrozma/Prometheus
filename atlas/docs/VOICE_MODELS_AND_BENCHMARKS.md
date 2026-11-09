# Voice models and benchmarks

All sizes are the published download sizes. Every file is verified against the SHA-256 in
`core/src/voice/catalog.rs` before use.

## Engines

| Engine | Version | Download | Platform | Licence | Source |
|---|---|---|---|---|---|
| sherpa-onnx (speech output) | 1.12.40 (last 1.x) | 22.2 MiB (Windows), 25.5 MiB (Linux) | Windows x64, Linux x64 | Apache-2.0; bundles onnxruntime (MIT). Voices include espeak-ng data (GPL-3.0), used by the separate engine program | github.com/k2-fsa/sherpa-onnx |
| whisper.cpp (speech recognition) | 1.8.2 | 3.65 MiB | Windows x64 | MIT | github.com/ggml-org/whisper.cpp |

**Why these:**
* **sherpa-onnx:**
  * The original Piper program was archived in Oct 2025.
  * Its successor (piper1-gpl) is a GPL-3.0 Python/C library with no standalone Windows binary.
  * sherpa-onnx is maintained, runs the same Piper voices on CPU, and publishes voice packages with
    checksums on GitHub.
  * It also runs Kokoro, a likely future "higher quality" option.
  * **Pinned to 1.12.40, not 2.x:** sherpa-onnx 2.0 removed its built-in espeak-ng phonemizer.
    Piper voices then generate no audio unless a separate phonemizer is supplied. The first
    real-engine CI run used 2.0.1 and failed on Windows and Linux with "Error in generating audio";
    1.12.40 still bundles espeak-ng.
* **whisper.cpp 1.8.2:** the newest release that ships Windows binaries (1.9.x are source-only).

## Voices (Piper, VITS)

| Voice | Language | Download | Licence (dataset) | Notes |
|---|---|---|---|---|
| **Alba** (default) | English (UK) | 64.1 MiB | CC BY 4.0 | Clearest licence |
| Lessac | English (US) | 64.1 MiB | Blizzard 2013 Lessac licence (non-commercial research terms) | Widely rated among the most natural Piper voices |
| Lessac, light (8-bit) | English (US) | 20.0 MiB | as Lessac | Faster on older PCs, slightly less smooth |
| Ryan | English (US) | 64.1 MiB | CC BY-NC-SA 4.0 | Male |
| Kareem | Arabic (Jordan) | 64.1 MiB | See the dataset's terms | Male |

* The default was chosen for licence clarity.
* Naturalness is subjective: **Preview voice** in Settings → Voice lets the owner judge on their own
  speakers.
* All voices are 22 kHz, medium quality.

## Whisper models (ggml)

| Model | Download | RAM in use (approx.)¹ | Accuracy | When |
|---|---|---|---|---|
| tiny | 77.7 MB | ~0.4 GB | Lowest | Low-memory PCs, or CPUs without AVX2 |
| **base** (starting recommendation) | 148 MB | ~0.5 GB | Good | Most PCs |
| small | 488 MB | ~1 GB | Clearly better | 8 GB+ RAM |
| large-v3 turbo (q5_0) | 574 MB | ~1.5 GB | Near-best | 16 GB+ RAM and a recent CPU |

¹ whisper.cpp's published guidance, not measured here.

## How Atlas recommends a model

`core/src/voice/hardware.rs` reads memory, cores and AVX2 locally:

| Condition | Recommendation |
|---|---|
| Under 4 GB RAM or a single core | tiny |
| x86-64 without AVX2 | tiny |
| Otherwise | base |
| 16 GB+ and 8+ cores | base, noting that small or turbo are affordable |

The recommendation is a starting point. **Run benchmark** (Settings → Voice) measures the real speed on
the owner's PC:
* It synthesises a fixed sentence with the selected voice.
* It transcribes that audio with every downloaded model.
* It reports the time, the speed relative to real time, and the share of words recognised.

## Measured benchmarks

Measured by `core/tests/voice_real_engines.rs` in `.github/workflows/atlas-voice-engines.yml`, with the
real engines and models downloaded from their public sources.
* **Machines:** GitHub-hosted CI VMs, not the owner's PC.
* **No microphone or speaker:** the "speech" is the Piper voice's own output fed to Whisper. That
  measures engine speed and round-trip intelligibility, not microphone quality.

*Results are filled in from the CI run below.*
