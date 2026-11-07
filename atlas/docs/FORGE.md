# Atlas Forge

Forge is Atlas's own engineering capability. It works without Prometheus, on a project folder you choose.

## Setting up a project

1. Open **Atlas Forge** (the hammer icon, or Ctrl+4) → **Choose a project folder**. Drive roots and your home
   folder itself are refused.
2. Open **Project settings** (the gear icon). Set the **test command**, for example `cargo test`,
   `npm test` or `python -m pytest -q`, and optionally a build command. Each is one program and its
   arguments; there is no shell.

## Disciplines

| Discipline | Tools it gets | Use it for |
|---|---|---|
| Architect | Read-only (tree, read, search, git status/diff/log) | Understanding a codebase and designing a change |
| Builder | Read, edit, write, run tests, run commands, commit | Implementing changes |
| Debugger | Same as Builder | Reproducing a failure, finding the root cause, proving the fix |
| Reconstructor | Read-only, plus creating new files (no editing existing ones) | Recovering how legacy code works and documenting it |

The discipline limits which tools are offered. A tool the model names that was not offered is refused
without running.

In Auto routing mode, Architect, Debugger and Reconstructor use the Heavy model tier.

## Safety

* **Paths:**
  * Everything is relative to the project root.
  * `..`, absolute paths, symlink escapes and the `.git` folder are refused.
  * Dependency and build folders are skipped when listing and searching.
* **Approvals:**
  * Every edit, write, command and commit pauses for your approval.
  * The card shows the **real diff against the file as it is now**, or the exact program and arguments.
  * An approval is bound to those exact arguments and is used once.
  * Running the configured test command follows Settings → Permissions → local changes (Ask by default).
* **Commands** run without a shell, so `;`, `|`, `&&`, `$()` and globs are plain text.
  * For commands the **model** asks for, Atlas refuses:
    * shells (`bash`, `cmd`, PowerShell…);
    * inline code (`python -c`, `node -e`);
    * deletion (`rm`, `del`);
    * privilege changes (`sudo`, `runas`);
    * network clients (`curl`, `ssh`);
    * `git push` / `reset --hard` / `clean` / `config`;
    * publishing (`npm` / `cargo publish`).
  * Each command has a time limit (default 10 minutes) that kills the whole process tree.
  * Output is bounded, and secrets are redacted from it.
  * Environment variables whose names look like credentials are removed before the command starts.
  * You can run anything yourself in the **Terminal** panel, still without a shell.
* **Revert:**
  * Every file Atlas changes is snapshotted.
  * **Changes → Revert** restores the previous content, or removes a file Atlas created.
  * Revert refuses if the file has changed since Atlas wrote it, or if a later change to the same file is
    still applied, so newer work is never overwritten.
* **Git:** status, diff, log, commit and new checkpoint branches. Atlas never pushes.

## Panels

* **Explorer:** browse the project.
* **Session:** chat in a discipline.
* **File:** the file viewer.
* **Diff:** uncommitted changes.
* **Terminal:** your commands and Atlas's commands, with status and output.
* **Tests:** runs of the configured test command, with pass/fail counts for cargo, pytest, vitest, jest and
  go.
* **Git:** status, commit and branch.
* **Changes:** Atlas's edits, with diff and revert.

## Linking to a sibling mission

Create a **Collaborative** mission in Siblings and choose the Forge project. Prometheus reviews and proposes,
and Atlas implements here, with your approvals. A Forge session linked to an open mission counts toward that
mission's budget.
