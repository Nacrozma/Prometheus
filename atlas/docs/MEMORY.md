# Memory

Short things worth remembering about the owner and their work, used in later conversations when they
are relevant. Separate from the Knowledge Vault (documents, `KNOWLEDGE_VAULT.md`) and from the activity
record (`TRUST_CENTER.md`): importing a document never creates a memory, and the activity record never
holds memory text.

## What creates a memory

* **The owner**, on the Memory page.
* **Atlas, through `memory.save`**: a proposal the owner approves (it follows the "Changes on this
  computer" permission, which asks by default). The tool description tells the model not to save
  temporary details, credentials, sensitive data, or anything only because a document or web page says
  so. The owner can switch proposals off (`memory.atlas_may_propose`, Memory page or Trust Center); the
  core then neither offers the tool nor runs it if called (checked again at execution, against the
  settings as they are at that moment).
* Nothing else. Atlas never infers and saves something silently, so every memory is either the owner's
  words or wording the owner approved. Anything that looks like a password or key is refused.

## What a memory records

| Field | Meaning |
|---|---|
| kind | preference, fact or note (kept from earlier versions; enough for the cases Atlas has) |
| scope | all conversations, or one project (another project's memories are never used; tested) |
| source | `user` (shown "Added by you") or `assistant` ("Suggested by Atlas, approved by you") |
| conversation | the conversation a proposal came from, linked from the Memory page |
| confirmed | when the owner last wrote, corrected or confirmed it (created time for older memories) |
| review date | optional; when reached, the memory needs review |
| status | active, needs review, outdated, superseded (replaced by a newer memory) |
| history | saved, corrected (with the old wording), confirmed, marked outdated, replaced, restored, due for review |

## Lifecycle

```
saved ─► active ──(fact unconfirmed 365 days, note 180, or review date reached)──► needs review
           ▲  │                                                                       │
           │  ├─ owner marks outdated ──► outdated (kept, never used) ── restore ──┐  │
           │  ├─ owner or approved proposal replaces it ──► superseded (kept, never used, links the new one)
           └──┴──────────────── owner confirms / corrects ◄──────────────────────────┴──┘
```

Preferences never age into review automatically. A memory needing review is still used, ranked lower,
and marked "may be out of date" in what the model receives.

**Duplicates** (same words, numbers included) in the same scope are refused, naming the memory Atlas
already has. **Possible conflicts** (overlapping subject, different content) are shown before saving on
the Memory page and in the approval for an Atlas proposal, which can carry `replaces` to supersede the
older memory. Atlas does not decide by itself which of two conflicting memories is right: the owner does,
by replacing, correcting or marking one outdated.

## Retrieval

* SQLite FTS5 (BM25) over the message, limited to global memories plus the conversation's project.
* Outdated and superseded memories are never retrieved; pinned memories are always eligible.
* Ranking: text relevance, adjusted by freshness (how long since the owner confirmed it), pinned first,
  "needs review" lower.
* Bounded by *Memories per request* (default 6) **and** about 1,800 characters in total, with no text twice.
* What the model receives says who worded each memory, when it was confirmed, whether it may be out of
  date, and that the owner's current message overrides memories. Memories are never instructions and
  cannot grant permissions.
* Which memories went with which message, to which provider and model, and whether that left the
  computer, is recorded (ids only) as `memory.used`.

Measured (debug build): a search over 2,000 memories in 13 ms (`core/tests/trust.rs`).

## Correction and deletion

* **Correct** (edit the wording): recorded in the history with the old wording; counts as confirmation.
* **Replace**: the new version is used from now on; the old one stays visible, marked replaced.
* **Still true**: confirms it (clears "needs review").
* **Mark outdated / Restore.**
* **Delete** removes the memory, its full-text index entry and its history. The activity record keeps
  only that a memory was deleted (never its text). Database backups made earlier still contain it until
  they are deleted; exports the owner saved are the owner's files. *Delete all* requires typing DELETE.
* **Export:** Memory → Export (JSON).
* **Off switch:** Settings → Memory. When off, nothing is retrieved and `memory.save` is unavailable.

**Future:** an optional embedding index can be added behind the same `memory::search` interface; it will stay
local by default and will not require a paid external vector database.
