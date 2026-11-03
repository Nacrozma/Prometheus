# Memory

* **Kinds:** preference, fact, note. **Scope:** all conversations, or one project.
* **Sources:** added by you, or saved by Atlas via `memory.save` — a local-write tool that asks for approval
  by default and refuses anything that looks like a credential.
* **Retrieval:** SQLite FTS5 (BM25) over the message text, limited to global memories plus the active project's,
  bounded by *Memories per request* (default 6). Pinned memories are always eligible. Each retrieved memory
  carries a reason ("matches “tomato”") shown in the conversation under *Using N memories*.
* **Isolation:** another project's memories are never retrieved (tested).
* **Editing & deletion:** edits update the full-text index; deletion removes the row and its index entry
  permanently. *Delete all* requires typing DELETE.
* **Export:** Memory → Export (JSON). Full backups include memories.
* **Off switch:** Settings → Memory. When off, nothing is retrieved and `memory.save` is unavailable.

**Future:** an optional embedding index can be added behind the same `memory::search` interface; it will stay
local by default and will not require a paid external vector database.
