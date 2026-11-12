# Known limitations (Prometheus Desktop 0.1.0)

Stated plainly so nothing is mistaken for validated.

## Not validated
* **No physical Windows PC was used.** Build, install, upgrade and uninstall were verified on a
  GitHub-hosted Windows VM; the app's pages were exercised offscreen there (self-test). Nobody has
  yet looked at the window on a real Windows desktop, clicked the tray, seen a notification,
  signed out and in with "Start when I sign in", or used it on a high-DPI or multi-monitor setup.
* **The orb on a real GPU** (CPU use, colours) is unmeasured; screenshots use software OpenGL.
* **macOS and Linux desktop sessions**: adapters exist, nothing validated (see CROSS_PLATFORM_ROADMAP).
* **Voice in the packaged app**: speech output (edge-tts, needs internet) is bundled but not tested
  on Windows audio hardware. Voice input is not bundled (Whisper/PyTorch); the Talk button is
  disabled with an explanation.
* **No real model conversation was run** in this work: no provider key was available here. The
  Companion uses the same worker as the existing HUD (which has its own tests); the router reports
  Ollama as a candidate even when no Ollama server is running, and a first message then fails with
  the provider's error.

## Limits by design (0.1)
* **Unsigned installer**: SmartScreen warns about an unknown publisher. Check the SHA-256.
* **No global shortcut** on any platform yet (not offered in Settings).
* **Self-modification patches** cannot be applied from the packaged app (they edit source files).
  The Forge page explains this; use a source checkout for patches.
* **Changing the workspace** applies after a restart.
* **Data import** runs at the next start, not immediately.
* **Robot arm**: simulation only. No serial/hardware control in the desktop app.
* **Child-Python mode** in the packaged app has only the bundled standard library plus bundled
  packages; generated code that imports other packages fails with ImportError.
* **Crash logs** (`desktop_crash.log`, `desktop_faults.log`) hold Python tracebacks locally; a
  third-party library error could in principle include request details.
* **Forge skills** are strongly isolated only when Docker is available (unchanged core limit).
* **Reminders** are delivered only while Prometheus runs; missed ones are delivered on next start.
