# Prometheus 2.0: UX audit (experience-first)

**Date:** 2026-11-17 · Reviewed: the running app (`docs/screenshots/renaissance/`, first pass) and the code
of every page. Verdict on the first Renaissance pass: functional and consistent, but it reads as a set of
administration panels. The same header, the same bordered card, the same table, on almost every screen.

## Cross-cutting findings

| # | Problem | User impact | Proposed experience | Implementation | Verify |
|---|---|---|---|---|---|
| X1 | Every page = eyebrow + title + subtitle + bordered cards + table | Screens blur together; nothing says what the screen is *for* | Page-specific compositions; the shared header shrinks to a quiet title line where the screen speaks for itself | `Page(header="compact"/"none")`, per-page layouts | Screenshot review: no two screens share a composition |
| X2 | Action results shown in tiny labels or the status bar | People miss whether something worked | Toasts (acknowledge vs. done, tone + icon + text, never colour alone), also announced to screen readers | `Toast` overlay in the main window, `notify()` helper | Window test: an action raises a toast |
| X3 | Bell lists session notifications only | No single place to see what happened | Activity centre drawer: notifications + recent audit events, each opens its source | Drawer from the bell | Screenshot, smoke test |
| X4 | Navigation groups mirror code areas | "Build" mixes calculators with files; Obsidian sits apart from Memory | Groups by intent: Overview · Conversation · Knowledge · Creation · Organisation · Laboratory · System | `NAV` | Screenshot |
| X5 | Empty states: one generic pattern | Doesn't tell what to do next | Each empty state answers why / what here / next action, with a screen-specific action | Per page | Screenshots of empty data |
| X6 | Tables used where people read sentences | Hard to scan memories, reminders, activity | Readable rows, timelines grouped by day, inspectors for detail | Custom list rows | Screenshot |

## Per screen

| Screen | Who / goal | First thing needed | Problems found | Proposed experience |
|---|---|---|---|---|
| Home | Owner starting a session: "what's going on, what next?" | Is Prometheus ready; what needs me; continue where I left off | 7 equal cards compete; no priority; activity log on Home is noise | Editorial composition: solar hero with a real ask box; **Needs you** (only real items: no provider, overdue reminders, pending patches, repeated tool failures); **Continue** (last conversation, current task, last Forge mission); **Today** timeline of reminders. Customize stays |
| Companion | Talking, thinking, getting things done | The conversation | Three columns always visible; reading column too wide; presence column mostly text; empty conversation is blank | Immersive reading column (max ≈ 820 px), conversation list and context panel as toggles (remembered), sun in a slim presence bar with the state in words, starter prompts in an empty conversation, contextual actions on replies (copy, regenerate, **save a list as the current task's steps**) |
| Memory | "What does Prometheus know about me, is it right?" | Recent memories and what needs review | Database table, provenance buried in a column | Library + inspector: category rail with counts, readable memory rows, inspector with provenance, history (corrections), links; **Review** queue for memories Prometheus suggested |
| Engineering | Engineer getting numbers / understanding a project | The tool for the job | A form generator under a dropdown; result as JSON | Workbench with two modes: **Calculation studio** (searchable library, form, a result sheet with the headline value large) and **Project intelligence** (project, branch, changes, languages, test files found, code search) |
| Forge | Starting and following project work | Start a mission; see what happened | Four equal cards then a form; history is a list of strings | Mission studio: guided start (project → objective → recommended discipline → scope → start), mission list on the left, mission workspace with real stages derived from the mission's tool calls, files touched, refusals, final report; wording per discipline |
| Workspace | Finding and reading files | Which project, what changed | Big blank preview until a file is picked; Git hidden in a tab | Explorer: tree + preview + inspector; with nothing selected the preview shows the workspace overview (projects, recent changes); inspector actions for the selected file (open, copy path, ask Prometheus about it) |
| Reminders & tasks | Keeping commitments | What's next and what's overdue | A form above a table; current task as raw text boxes | Planner: views rail with counts (Today, Upcoming, Overdue, Done, Cancelled), quick-add line, day-grouped agenda, current task as a checklist (steps checked through `update_task_state`) |
| Obsidian | Reading the knowledge Prometheus mirrors | The notes | A settings card and an empty text box | Knowledge reader: onboarding when no vault; with a vault: note list + search, Markdown reader, backlinks and outgoing links computed from the vault's own `[[links]]` |
| Robot arm | Exploring the arm's reach safely | The arm | Small diagram, sliders, JSON | Lab studio: large viewport, joint dials with numeric readouts and keyboard nudges, reach target with result, telemetry (tip position, limits, collisions), reset; SIMULATION always stated |
| Reflection | "Is Prometheus reliable, what should change?" | A summary in words | Tiles + table | Insights: a written headline, reliability bars with sample sizes (n<5 marked too few), recent-outcome strips per tool, suggestions, evaluations in words |
| Trust & safety | Oversight | Is anything wrong; what happened | Tiles + tabs + table | Oversight: posture statement, timeline grouped by day with an inspector, data flows as source → destination lines, permissions grouped as Asks first / Allowed / Denied |
| Settings | Configuring by intent | The thing to change | One long scroll | Category rail (Models, Voice, Appearance, Workspace, Desktop, Privacy & autonomy, Data, About) with focused pages; save feedback via toasts |

## Accessibility findings
Status shown by colour alone in pills and timelines (add text/icons); focus ring only on some controls
(extend); several labels not exposed to assistive tech (accessible names added to new controls).
