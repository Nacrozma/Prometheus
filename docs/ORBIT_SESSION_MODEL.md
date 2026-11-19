# ORBIT — Session model

A session holds: id, title, created/updated, the dialogue conversation id, autonomy (+ allowed step kinds for
Advanced), plan versions, active version, approved version, workflow (or none), an event log (last 500), archived.

| | Prometheus | Atlas |
|---|---|---|
| Storage | `<data>/orbit/<32-hex id>.json`, written by `state_io.atomic_write_json` | SQLite `orbit_sessions(id, title, updated_at, archived, data JSON)`, schema 10 |
| Validation on load | schema number, id shape, versions list; damaged file quarantined (`quarantine_file`), never half-read | JSON parse; an unreadable record is reported as a storage error |
| Who writes | the ORBIT page through `OrbitStore.save` | only the core, after `orbit::apply` validated the action |
| Dialogue | a Companion conversation tagged `orbit` | an Atlas conversation titled “ORBIT · …” |
| Each step | its own conversation “ORBIT step · …” (inspectable in Companion) | its own conversation “ORBIT step · …” |

## Lifecycle

* **New** — Prometheus keeps a blank session in memory until first real use (no empty files); Atlas creates on
  *New session* or the first message.
* **Reopen** — the last session reopens when you return (Prometheus `orbit_session` setting; Atlas local storage).
* **Recovery after a restart** — any step that was *running* or *awaiting approval* becomes *paused*, with the history
  note “interrupted … it was not repeated”; the workflow is paused; nothing starts by itself. Prometheus applies this
  on load; Atlas at start-up for all sessions (audited as `orbit.steps_interrupted`).
* **Archive** — hidden from the list, kept on disk. **Delete** (confirmed) removes the session record; its
  conversations stay.

## Privacy

Sessions are local. No audio is stored by ORBIT. Transcripts are the conversation messages already kept by each
app. Nothing is shared between Prometheus and Atlas.
