# Data and migration

## Where data lives
| Situation | Data folder | Workspace |
|---|---|---|
| `PROMETHEUS_HOME` / `PROMETHEUS_WORKSPACE` set | as set | as set |
| Running from a source checkout that **already has** Prometheus data (memory, sessions, audit…) | the source folder, unchanged | the source folder (as the terminal) |
| Packaged app, or a fresh checkout | per-user folder (Windows `%APPDATA%\Prometheus`) | chosen in Settings, else `Documents\Prometheus Workspace` |

So nothing moves for existing users: the terminal, the HUD and the desktop app opened from the same
checkout all keep reading and writing the same files. No state file was renamed or relocated by
this work; the core only gained the ability to be *told* where its data folder is.

Keys are never in the data folder when saved from the app: they go to the OS credential store. A
`.env` in the source folder or the data folder still works and wins over stored keys.

## Importing data into the installed app
Settings → Data → **Import data from another Prometheus folder…**
1. **Detect**: lists the state files and folders the core uses (memory, memory graph, skills, tool
   stats, audit log, task state, schedule, usage log, permissions, session, GUI config; folders
   `sessions/`, `dynamic_tools/`, `.prometheus_undo/`, `pending_patches/`). JSON files that do not
   parse are reported and skipped. `.env` is never copied.
2. **Confirm**: a summary says how many files, which existing ones will be replaced, which are skipped.
3. **Queue**: the import runs at the **next start, before the core loads**, so in-memory state cannot
   overwrite imported files.
4. **Back up**: every destination file that would be replaced is copied to
   `<data>/backups/pre-import-YYYYmmdd-HHMMSS/` and verified by SHA-256.
5. **Apply atomically**: each file is copied to `*.importing`, verified by SHA-256, then `os.replace`d.
6. **Roll back on failure**: restored from the backup; newly added files removed.
7. **Keep the backup**: never deleted automatically. The source folder is only read.

## Recovery
* Undo an import: quit Prometheus, copy the files from `backups/pre-import-…/` back into the data folder.
* A corrupt desktop settings file is renamed `desktop_settings.json.corrupt.*` and defaults are used
  (the core's own state files already had the same quarantine behaviour).
* Uninstalling keeps the data folder and the stored keys. To remove everything: delete
  `%APPDATA%\Prometheus` and the "Prometheus Desktop" entries in Credential Manager.
