# Prometheus Desktop 2.1.0 — ORBIT

Released 2026-11-19 at the owner's request, so the owner can test ORBIT on their Windows PC. Unsigned installer.
Everything from 2.0.0 (the Renaissance) is kept; 2.0.0 and its installer stay published unchanged.

## New: ORBIT (navigation → Conversation → ORBIT, or Ctrl+Shift+O)

* Talk with Prometheus (Talk button, Ctrl+Shift+Space) or type. The plan forms as orbits around the sun:
  phases are orbits, tasks sit on them, arcs show what waits for what.
* Change the plan by voice or typing (“add task Write tests to Build”, “make Publish high priority”,
  “move Verify before Build”, “undo”), by dragging a task to another orbit, or in the Step tab.
  Every change is a new version (who, why); compare and restore in Versions.
* Plans from Prometheus are drafts until you press **Approve plan**. **Build workflow** turns the approved
  plan into steps done by real capabilities (Prometheus, Forge disciplines, reminders, or you).
* **Autonomy** per session: Approval-first (default), Balanced, Advanced. Tools with real-world effects still
  show the approval card every time.
* Separate **Stop speaking**, **Pause**, **Cancel workflow** and **End conversation**.
* Continuous conversation (listens again after each reply, ends your turn when you pause) or push-to-talk.
* Outline view (the same plan as a list), immersive mode (Esc returns), new sun states Planning and Executing.
* Closing Prometheus during a step pauses it; it is never repeated automatically.

## Know before you test

* Voice input needs Whisper (`openai-whisper`, `sounddevice`), which the installer does not include; without it
  ORBIT works by typing. Spoken replies use edge-tts (reply text goes to Microsoft's speech service).
* While Prometheus speaks, the microphone is paused: interrupt with Stop speaking, Esc or Talk.
* A model provider is needed for conversation (Settings → Providers, or Ollama); plan edits work without one.
* Details: `ORBIT_PRODUCT_SPECIFICATION.md`, limitations in `ORBIT_RELEASE_READINESS.md`.
