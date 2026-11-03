# ADR 0002 — Local-first storage in SQLite

**Decision.** One bundled SQLite database (WAL) per user with ordered migrations under `user_version`, FTS5 for
conversation and memory search, and `VACUUM INTO` / the backup API for backups.

**Why.** No server, works offline, transactional, single-file backups, and full-text search without a vector
database. **Consequences.** Retrieval is lexical (BM25), not semantic; an embedding index can be added behind
`memory::search` later.
