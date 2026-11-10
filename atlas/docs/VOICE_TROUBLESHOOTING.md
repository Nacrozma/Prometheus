# Voice troubleshooting

Voice is optional: if anything here goes wrong, typing keeps working exactly as before.

## Setting up

| Symptom | What it means | What to do |
|---|---|---|
| "Voice is off" | Voice is switched off (the default) | Settings → Voice → turn on **Voice** |
| "…isn't set up yet" | The engine or the selected voice/model isn't downloaded | Settings → Voice → **Set up speech output** or **Set up speech recognition** (the size is shown on the button) |
| "offline mode is on, so Atlas will not download anything" | Settings → Data & privacy → offline mode is on | Turn it off for the download, then back on. Installed voices keep working offline |
| "…failed its integrity check… it was deleted" | The downloaded file was not the exact file Atlas expects (damaged download, captive Wi-Fi page, or tampering) | Try again later or on another network. Nothing was installed |
| "…is larger than expected; stopped the download" | The server sent more than the catalogue allows | As above; nothing was installed |
| "not enough free disk space" | The archive and its unpacked files need about three times the download size for a moment | Free some space (Settings → Voice shows free space) |
| A download stalls | No data for 60 seconds | It stops with "stalled"; press Download again |
| An item shows **Damaged** | Its file list (manifest) is missing or unreadable | **Remove**, then **Download** again |
| **Verify** reports changed files | Files were altered after installation (antivirus quarantine, disk errors, manual edits) | **Remove**, then **Download** again |

## Microphone

| Symptom | What to do |
|---|---|
| "Microphone access was declined" | Allow it when Atlas asks. In Windows: Settings → Privacy & security → Microphone → turn on "Microphone access" and "Let desktop apps access your microphone" |
| "No microphone was found" | Connect one, or pick one in Settings → Voice → Microphone (names appear after access is allowed) |
| "The microphone is in use by another app" | Close the other app (calls, recorders) or pick another microphone |
| "The microphone was disconnected" | It was unplugged while listening. Plug it back in and press the microphone button again |
| "I didn't catch anything" | Speak a little closer or louder; check the level with **Test microphone** (the ring moves with your voice) |
| "That was too short to understand" | Hold the button a little longer (at least 0.3 s of speech) |
| Listening stops after two minutes | Recordings are capped at two minutes; what you said is still transcribed |

## Recognition quality and speed

* Choose the language in Settings → Voice instead of "Detect automatically" if words come out in the
  wrong language.
* **Run benchmark** in Settings → Voice:
  * It times each downloaded model on this PC and shows how many words of a test sentence it got right.
  * A model slower than real time ("0.5× real time") will feel laggy; choose a smaller one.
* "This CPU lacks AVX2": recognition will be slow; use **Whisper tiny**.
* "speech recognition took too long and was stopped": the model is too heavy for this PC; choose a
  smaller one.

## Speech output

| Symptom | What to do |
|---|---|
| No sound, but the ring moves | The ring reads Atlas's own audio, so Atlas *is* playing. Check the Windows volume mixer and output device, and Settings → Voice → Volume |
| No sound and the ring is still | "Read replies aloud" may be off (the speaker button above the message box), or the voice isn't installed |
| "the speech engine failed (exit …)" | Settings → Voice → **Verify** the engine and voice; **Remove** and download again if anything changed |
| Speech starts late | The first sentence is synthesised before it plays; later ones are prepared while earlier ones play. A lighter voice (Lessac, light) is faster |
| It reads something it shouldn't | Code blocks and tables are announced, not read; links are read as "a link". Report other cases |
| I want it to stop | Esc, the ■ button, or the speaker button to stop reading replies aloud |

## Platform notes

* **Windows 10/11 (64-bit):** speech output and speech recognition are both supported.
* **Linux:** speech output works (sherpa-onnx publishes Linux builds). Speech recognition is not
  offered, because whisper.cpp publishes Windows binaries only.
* **macOS:** voice is not offered yet.

## Removing voice files

* In the app: Settings → Voice → **Remove** next to each item. Settings → Voice shows how much space
  voice files use.
* By hand: close Atlas and delete the `voice` folder inside Atlas's data folder.
  * Settings → About shows the data folder.
  * On Windows it is `%APPDATA%\app.atlascopilot.desktop\voice`.

## What Atlas never does

* It never listens in the background, and never keeps recordings.
* It never sends audio or transcripts to any service or to Prometheus.
* It never switches to a cloud speech service on its own.

## Measuring it on your PC

**Settings → Voice → Voice check** tests your real speakers and microphone and shows what Atlas
measured: how long speech takes to start, what it recognised and how many words were right. **Copy
report** gives the results as text (no audio). The full checklist is in
[VOICE_HARDWARE_VALIDATION.md](VOICE_HARDWARE_VALIDATION.md).
