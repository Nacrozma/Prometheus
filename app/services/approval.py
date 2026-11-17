"""What an approval card says: the action in plain words, its effects, reversibility and a real diff.

Built only from the tool's actual arguments and the workspace's actual files (read-only, inside the
workspace, size-capped). Nothing here decides anything: the card shows this, the owner chooses, and the
core still checks the call again (policy, conscience check, audit log) when it runs.
"""

from __future__ import annotations

import difflib
import os
from typing import Any, Dict, List

MAX_DIFF_LINES = 400
MAX_FILE_BYTES = 400_000


def _inside(root: str, rel: str) -> str:
    """The resolved path if `rel` is inside the workspace, else ''."""
    if not rel:
        return ""
    root_r = os.path.realpath(root)
    p = os.path.realpath(os.path.join(root_r, rel))
    return p if p == root_r or p.startswith(root_r + os.sep) else ""


def _read(path: str) -> str:
    try:
        if os.path.getsize(path) > MAX_FILE_BYTES:
            return ""
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def unified(old: str, new: str, name: str) -> List[str]:
    lines = list(difflib.unified_diff(old.splitlines(), new.splitlines(), f"{name} (now)", f"{name} (after)", lineterm="", n=2))
    return lines[:MAX_DIFF_LINES] + ([f"… {len(lines) - MAX_DIFF_LINES} more diff lines"] if len(lines) > MAX_DIFF_LINES else [])


def describe(tool: str, args: Dict[str, Any], workspace: str) -> Dict[str, Any]:
    """Plain-language description of a pending tool call."""
    a = args if isinstance(args, dict) else {}
    d: Dict[str, Any] = {"title": f"Run {tool}", "what": "", "affects": [], "reversible": "Not reversible from Prometheus.", "leaves": "Nothing leaves this computer.", "if_denied": "Nothing happens; Prometheus is told you said no and continues without it.", "diff": [], "preview": ""}
    path = str(a.get("path") or "")
    if tool == "write_file":
        full = _inside(workspace, path)
        exists = bool(full) and os.path.isfile(full)
        content = str(a.get("content") or "")
        n = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
        if a.get("append"):
            d.update(title=f"Add to {path}", what=f"Append {n} line{'s' if n != 1 else ''} to the end of {path}.")
        elif exists:
            d.update(title=f"Replace {path}", what=f"Overwrite {path} with new content ({n} lines).")
            d["diff"] = unified(_read(full), content, path)
        else:
            d.update(title=f"Create {path}", what=f"Create a new file {path} ({n} lines).")
            d["preview"] = content[:4000]
        d["affects"] = [path or "(no path given)"]
        d["reversible"] = "Reversible: the previous content is kept in the undo journal (Trust & safety → Undo)." if exists else "Reversible by deleting the new file."
        if not full:
            d["what"] += " The path is outside the workspace: the core will refuse it."
    elif tool == "edit_file":
        full = _inside(workspace, path)
        old, new = str(a.get("old_string") or ""), str(a.get("new_string") or "")
        current = _read(full) if full else ""
        count = current.count(old) if old else 0
        d.update(title=f"Edit {path}", what=f"Replace {'every' if a.get('replace_all') else 'one'} exact passage in {path}" + (f" (found {count} time{'s' if count != 1 else ''})." if current else "."))
        if current and old and count:
            after = current.replace(old, new) if a.get("replace_all") else current.replace(old, new, 1)
            d["diff"] = unified(current, after, path)
        else:
            d["diff"] = unified(old, new, path)
            if current and not count:
                d["what"] += " The passage is not in the file as it is now, so the core will refuse the edit."
        d["affects"] = [path or "(no path given)"]
        d["reversible"] = "Reversible: the previous content is kept in the undo journal (Trust & safety → Undo)."
    elif tool == "execute_shell":
        d.update(title="Run a shell command", what="Run this command in the workspace folder (at most 120 seconds):", preview=str(a.get("command") or ""))
        d["affects"] = ["Anything the command touches inside (and possibly outside) the workspace"]
        d["reversible"] = "Not reversible: Undo covers only files changed by the file tools."
        d["leaves"] = "Depends on the command: it can reach the network if the command does."
    elif tool == "run_code_forge":
        d.update(title="Run generated Python code", what="Run this code in the Code Forge (isolated in Docker when available, otherwise a resource-limited subprocess, which is not a security boundary):", preview=str(a.get("python_code") or "")[:6000])
        d["affects"] = ["Files the code writes; processes it starts"]
    elif tool == "export_obsidian":
        d.update(title="Export memory to Obsidian", what="Write the memory graph as linked notes into the vault's Prometheus folder. Text you added below a note's generated section is kept.")
        d["affects"] = ["<vault>/Prometheus/ only"]
        d["reversible"] = "Generated notes are rewritten on each export; your own text in them is kept."
    elif tool == "apply_pending_patch":
        d.update(title="Apply a self-patch", what=f"Change Prometheus's own source code with the proposed patch {a.get('patch_id', '')}. It has passed the patch gate (static policy and tests), which is not proof it is safe.")
        d["affects"] = ["Prometheus's own code (source checkout only)"]
        d["reversible"] = "Use Git to revert the change."
    elif tool == "synthesize_dynamic_tool":
        d.update(title=f"Teach Prometheus a new skill: {a.get('name', '')}", what="Register new Python code as a skill after its static check and tests pass.", preview=str(a.get("python_code") or "")[:6000])
        d["affects"] = ["Prometheus's skills (Forge → Skills)"]
        d["reversible"] = "Reversible: roll the skill back in Forge → Skills."
    elif tool == "ghost_control":
        d.update(title="Control the mouse, keyboard or screen", what="Prometheus wants to operate this computer's input devices or capture the screen.")
        d["affects"] = ["Whatever is on screen and has focus"]
        d["leaves"] = "A screen capture stays on this computer unless a later step sends it."
    elif tool == "sculpt_workspace":
        d.update(title="Open application layouts", what="Launch desktop applications in a layout.")
        d["affects"] = ["Your desktop windows"]
    else:
        d["what"] = f"Run the tool {tool} with the arguments below."
    return d
