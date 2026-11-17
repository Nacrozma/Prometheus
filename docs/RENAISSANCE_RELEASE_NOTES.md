# Prometheus 2.0 "Renaissance" — release notes (draft, not released)

Version 2.0.0 of Prometheus Desktop (0.1.0 was never published). Not released: waiting for the owner.

## New
* **A new look:** Solar × Cosmic design system: deep cosmic surfaces, solar gold and amber, consistent
  components and icons on every screen.
* **Home:** a command centre built from your own data, customizable.
* **Search everything (Ctrl+K):** conversations, memory, reminders, workspace files and activity.
* **Conversations:** keep many, search, rename, delete; multiline composer; copy, regenerate, retry.
* **The living sun:** clearer states (thinking, researching, building, speaking, listening, offline…),
  driven by what Prometheus is really doing and by the real audio level; lighter on the GPU; a painted
  sun where OpenGL is unavailable.
* **Memory you control:** add, correct, confirm, forget; see who each memory came from.
* **Forge disciplines:** Architect, Builder, Debugger, Reconstructor missions with enforced boundaries.
* **Workspace:** projects, Git state, recent changes, file filter, highlighted previews.
* **Reminders & tasks:** clearer times and repeats; edit the current task; ask Prometheus to plan it.
* **Reflection:** tiles, suggestions, model usage, evaluation results in plain words.
* **Trust & safety:** where your data goes, filtered activity, undo the last file change.
* **Settings:** test provider connections, choose each provider's model, export a backup.
* **First-launch welcome.**

## Fixed
* Memory page showed every confidence and importance as 0.00 and labelled model-written memories
  "operator / verified"; it now shows real importance and correct provenance.
* Trust page showed every tool duration as 0.00 s.
* The "Skills" filter on the Memory page matched no memory kind.

## Upgrading
Existing data folders open unchanged. The HUD's current session becomes your first conversation (the
original file is kept). Nothing is deleted.
