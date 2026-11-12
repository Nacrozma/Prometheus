# Prometheus Desktop: UI map

Every visible control is wired to a real implementation. Screenshots: `screenshots/`.

| Section | What it shows | What it does (backend) | Screenshot |
|---|---|---|---|
| **Companion** | Conversation (Markdown, escaped), the OpenGL orb with state, provider/model, voice status | `gui_orb.PrometheusWorker` (same loop as the HUD); approval cards answer `provide_confirmation`; Stop/Esc → `request_stop`; Talk → `WhisperVoiceThread` (only if installed); speech → `TTSManager` | 01, 12 |
| **Memory** | Recall search or fact list; kind, source, Trust (unverified/verified), confidence, importance; stats | `MemoryGraph.recall/list_facts/stats`, `is_untrusted_source`. Corrections go through the Companion (`update_memory` tool, audited) | 02 |
| **Engineering** | Calculator picker, typed inputs, JSON result, disclaimer | `dispatch_tool("engineering_calc")` for all 17 calculators | 03 |
| **Forge** | Learned skills (version, enabled, tests), pending self-patches | `SkillRegistry.list`; *Roll back* → `dispatch_tool("rollback_skill")`. Patches: listed; in the packaged app labelled unavailable (they patch source files) | 04 |
| **Workspace** | Read-only tree of the workspace, safe text preview | `QFileSystemModel` rooted at `WORKSPACE_DIR`; preview refuses `.env`, binary, >200 KB, outside root | 05 |
| **Reminders & tasks** | Scheduled reminders, add/cancel, current task state | `schedule_task`, `cancel_scheduled`, `list_scheduled`, `read_task_state` through `dispatch_tool`; due reminders polled every 15 s → Companion + tray notification | 06 |
| **Obsidian** | Vault picker, inbox status, export | `set_obsidian_vault`; export is sent through the Companion so it raises an approval card | 07 |
| **Robot arm (simulation)** | Banner, joint sliders, forward kinematics SVG, IK solver | `arm_sim.forward/render_svg/within_limits/collisions`; IK via `dispatch_tool("arm_plan")`. No hardware controls exist | 08 |
| **Reflection** | Per-tool calls, failures, success rate, latency, lesson; offline eval results labelled synthetic | `ToolStats.summary`, `lesson_for`; `evals/results.json` | 09 |
| **Trust & safety** | Permission rule for every tool, auto-approve state, write scopes, audit tail + chain verification, undo journal, plain-language limits | `Policy`, `DANGEROUS_TOOLS`, `AuditLog.tail/verify`, `UndoJournal.list/undo` | 10 |
| **Settings** | Provider keys (masked, OS store), router status/reconnect, workspace, tray/notifications/sign-in/reduced motion, auto-approve (warning dialog), voice availability, data folder, import, about | `CredentialStore`, `llm_router.reload()`, `DesktopSettings`, platform adapter, `app.migration` | 11, 14 |
| **Command palette** (Ctrl+K) | Go to any section, new conversation, stop, reconnect, quit | Navigation and the same actions as the buttons | 13 |
| **Tray** | Show, New conversation, Stop current request, Quit | Same methods as the window | – (no system tray in the headless CI display) |

Keyboard: Ctrl+K palette · Ctrl+N new conversation · Ctrl+, Settings · Esc stop · Ctrl+Q quit · Enter send.
Status bar: provider · model (and **AUTO-APPROVE ON** when on) · busy · orb state.
