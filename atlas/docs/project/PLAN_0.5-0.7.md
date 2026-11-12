# Atlas 0.5.0 → 0.7.0: plan

Written 2026-11-12 from the repository at `2d6697d` (release `atlas-v0.4.2`). Kept short on purpose;
the detailed audit is `docs/ATLAS_0.5_AUDIT.md`.

## 1. Verified 0.4.2 baseline

| Check | Result (2026-11-11) |
|---|---|
| Rust 143, frontend 61, Python 409, end-to-end 19 | All pass |
| CI: Windows, Linux, macOS | 5 of 5 jobs green |
| Install + upgrade from 0.4.1 and 0.3.0 | Pass; data kept; pre-upgrade backup made |
| Owner's PC: voice | **Owner reports it works and sounds smooth, with a slight delay before answers.** No measurements yet (no Voice check report) |
| Owner's PC: tray, shortcut, system notification | Not yet reported |

## 2. What exists and is reused

| Need | Reuse |
|---|---|
| Storage and migrations | `storage/` (SQLite, numbered migrations, automatic pre-upgrade backup) |
| Notifications | `desktop.rs` `NotificationCenter` (the only notification system; new kinds are added to it) |
| Background loop | The shell's 2 s upkeep loop (`sibling_sync_once`); the scheduler ticks from the same loop |
| Model tools, approvals, audit | `tools/`, `approvals.rs`, `audit.rs`, `policy.rs` |
| Dashboard | `features/home/Home.tsx` becomes the Command Center (no second dashboard) |
| Memory | `memory.rs` (approved memories, FTS) |
| Projects | `projects.rs` (tasks and documents attach to these) |
| Execution history | Existing `tasks` table = **runs** of tool-using turns. It is not the owner's to-do list |

## 3. Vocabulary (kept distinct in code and UI)

| Concept | Meaning | Table |
|---|---|---|
| **Task** (to-do) | Something the owner wants done; may have a deadline, reminder, recurrence, subtasks | `todos` (new) |
| **Reminder** | A time at which Atlas notifies about a task | `todos.remind_at` → a scheduled job |
| **Scheduled job** | A time-triggered action Atlas runs (reminder, briefing; later workflows) | `scheduled_jobs` (new) |
| **Run** | Record of one tool-using turn | `tasks` (existing; UI label "Activity") |
| **Mission** | Work shared with Prometheus | `missions` (existing) |

## 4. Gaps against the directive, and where each lands

| Area | 0.5.0 | 0.6.0 | 0.7.0 |
|---|---|---|---|
| Tasks, deadlines, recurrence, reminders, natural-language entry | ✔ | | |
| Scheduler (persistent, restart-safe, no duplicates, missed jobs) | ✔ | workflows use it | |
| Notification kinds: reminder, deadline, briefing | ✔ | | |
| Command Center, daily briefing | ✔ | | |
| Focus Mode | ✔ | | |
| Session recap, conversation summaries, handoff | ✔ | | |
| Memory: provenance, duplicates, conflicts, review | ✔ | | |
| Knowledge Vault: TXT, MD, PDF, DOCX, search, citations | ✔ | XLSX, CSV | |
| Trust Center, global pause | ✔ | | |
| Personality depth | ✔ | | |
| Specialist agents | design + role registry | full orchestration | |
| Workflow Studio, Integration Hub | | ✔ | |
| Linux/macOS speech recognition | | ✔ (needs evaluation) | |
| File exchange, patch review, mission plans | | | ✔ |

## 5. Dependency order for 0.5.0

```
Stage 1 tasks ─┬─> Stage 2 scheduler + reminders ─┬─> Stage 3 Command Center + briefing
               │                                  └─> Stage 4 Focus Mode + recap
               └─> (natural-language tools)
Stage 5 Knowledge Vault ──> Stage 6 memory quality + Trust Center ──> Stage 7 specialists + personality
```

## 6. Migration strategy

* One numbered migration per stage, each in its own transaction (existing mechanism). The database is
  copied to `atlas.pre-v<N>.bak` before any migration (existing, tested by the install test).
* Only additive changes: new tables and new columns with defaults. One exception in v5: the
  `notifications` table is rebuilt to accept new kinds; its rows are copied.
* Every migration gets a test that upgrades a database created at the previous version with data in it.
* v5 = tasks + scheduler + notification kinds. v6 = focus sessions + summaries. v7 = Knowledge Vault.
  v8 = memory quality. Later numbers as needed.

## 7. Security and privacy risks

| Risk | Handling |
|---|---|
| A scheduler that acts with nobody present | In 0.5.0 it only raises notifications and prepares the briefing. Global pause. No tool runs unattended |
| Job runs twice after a restart or retry | A job is claimed in one SQL statement (`pending → running`), unique key per (kind, subject, time) |
| Reminder text on a lock screen | Existing rule: generic wording unless "Show what it's about" is on |
| Model edits or deletes tasks unasked | Create, edit and complete go through a "planner" permission (default allow, can be set to ask); delete always asks |
| Imported documents carry instructions | Text is stored and retrieved as quoted data with a fixed warning; nothing in a file is executed; size and page limits |
| Documents sent to a cloud model | Passages go to the model only as part of a turn the owner started; local-only setting; shown in the Trust Center |
| One project's context leaking into another | Queries are scoped by project in the core; tests for cross-project retrieval |

## 8. Test strategy

Per stage: Rust unit and integration tests (including failure paths and restart), a migration test,
Vitest for UI logic, an end-to-end test in the real app with a **screenshot of every new feature**
(standing rule from the owner, 2026-11-12), then the full regression run. Release gates as in the
directive, plus install and upgrade tests from 0.4.2 and 0.3.0.

## 9. Deferred, with reasons

| Item | To | Why |
|---|---|---|
| Voice tuning (delay before answers, sentence gaps, model default) | When a Voice check report exists | The owner's report is positive but has no numbers; tuning blind risks a working feature |
| Calendar-backed "appointments" | 0.6.0 Integration Hub | Needs a real connected calendar; the briefing says so instead of inventing events |
| Specialists running tools on their own | 0.6.0 | Needs the workflow executor and budget limits first |
| Remote sibling link | After 0.7.0 | Needs the full security design |

## 10. First slice (Stage 1)

Migration v5 (tasks part) → `todos.rs` service (create, edit, complete, reopen, postpone, reschedule,
subtasks, recurrence, search, overdue, day and week views) → date parser for plain-language entry →
model tools → commands → Tasks page → tests → screenshots.

## Publication rule

Commits are pushed to the working branch as before. **A release is not published until the owner says
so** (directive, 2026-11-12).
