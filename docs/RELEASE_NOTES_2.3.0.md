# Prometheus Desktop 2.3.0 — Prometheus speaks on its own terms

**Status: prepared, not published** (waiting for the owner's approval). Unsigned installer when published.

## New: spoken replies you control (Settings → Voice → Spoken replies)

* **On/off** for spoken replies, separate from voice input (turning speech off never turns off the microphone).
* **Two engines, your choice, no silent fallback:**
  * **On this computer** — sherpa-onnx 1.12.40 (Apache-2.0) with Piper voices: Alba (UK, CC BY 4.0), Lessac (US,
    non-commercial licence), Ryan (US, CC BY-NC-SA 4.0). Set up from *Set up local voice…*: shows what is
    downloaded, from where (github.com/k2-fsa/sherpa-onnx), sizes and licences; progress, cancel, SHA-256 check of
    every file, safe unpacking (only the program, its libraries and the voice files; no links or paths outside the
    folder), disk-space check, repair and removal. After setup it works without the internet and no reply text
    leaves the computer.
  * **Microsoft online voice** — the 2.2.0 edge-tts service, now optional. Choosing it shows what happens to your
    text first (it is sent to Microsoft) and asks you to confirm.
  * If the chosen engine cannot speak, the reply stays as text with a plain reason; Prometheus does not switch
    engines by itself.
* **Voice** (only voices that are really installed / offered) and **speed** (0.5×–2.0×), remembered across restarts.
* **Test voice** generates and plays real speech with your settings and says whether it worked.
* **One shared speech service** for the Companion and ORBIT: same engine, voice and speed; one speaker queue, so
  the two never talk over each other. Code blocks, plan data, links and markup are never read aloud.
* **The sun speaks only while audio plays**: the avatar's SPEAKING state now follows real playback, not the
  moment a reply was queued.
* **Continuous conversation in ORBIT** continues after a reply is spoken — or, if speech failed or is off, right
  after the reply — and never while a step runs, an approval waits or after *End conversation*.

## Upgrading from 2.2.0

Your existing behaviour is kept: if you used 2.2.0, spoken replies stay on Microsoft's online voice with the same
voice, speed and on/off setting until you choose the local voice. New installations start with the local engine
(speech begins once it is set up). Voice input files are not touched.

## Verified

See `docs/VOICE_EXPERIENCE_REPORT.md`.
