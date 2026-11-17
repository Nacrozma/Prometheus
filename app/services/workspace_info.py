"""Read-only facts about the workspace for the desktop: projects, Git state, recent changes.

Git is run with a fixed argument list (no shell, no user-supplied arguments), read-only commands only,
inside a project folder that is itself inside the workspace, with a short timeout. Walks are bounded
and never follow links out of the workspace.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional

from .search import MAX_DEPTH, SKIP_DIRS

GIT_TIMEOUT = 6


def inside(root: str, path: str) -> bool:
    root, path = os.path.realpath(root), os.path.realpath(path)
    return path == root or path.startswith(root + os.sep)


def projects(root: str, limit: int = 30) -> List[Dict[str, Any]]:
    """Top-level folders of the workspace (and the workspace itself if it is a Git repository)."""
    out: List[Dict[str, Any]] = []
    if not os.path.isdir(root):
        return out
    cands = [root] + [os.path.join(root, n) for n in sorted(os.listdir(root)) if not n.startswith(".") and n not in SKIP_DIRS]
    for path in cands:
        if not os.path.isdir(path) or not inside(root, path):
            continue
        is_git = os.path.isdir(os.path.join(path, ".git"))
        if path == root and not is_git:
            continue
        try:
            mtime = max((os.path.getmtime(os.path.join(path, n)) for n in os.listdir(path)), default=os.path.getmtime(path))
        except OSError:
            mtime = 0
        out.append({"name": os.path.basename(path) if path != root else os.path.basename(root) + " (workspace)", "path": path, "git": is_git, "modified": mtime})
    out.sort(key=lambda p: p["modified"], reverse=True)
    return out[:limit]


def _git(path: str, *args: str) -> Optional[str]:
    exe = shutil.which("git")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "-C", path, *args], capture_output=True, text=True, timeout=GIT_TIMEOUT, env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"})
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def git_status(root: str, path: str) -> Dict[str, Any]:
    """Branch, changed files and recent commits of a project inside the workspace."""
    if not inside(root, path):
        return {"error": "outside the workspace"}
    if not os.path.isdir(os.path.join(path, ".git")):
        return {"git": False}
    if not shutil.which("git"):
        return {"git": True, "error": "Git is not installed, so the repository state cannot be read."}
    st = _git(path, "status", "--porcelain=v1", "-b", "--untracked-files=normal")
    if st is None:
        return {"git": True, "error": "Git could not read this repository."}
    lines = st.splitlines()
    branch = lines[0][3:] if lines and lines[0].startswith("## ") else ""
    changes = [{"code": ln[:2], "path": ln[3:]} for ln in lines[1:] if ln.strip()][:200]
    log = _git(path, "log", "-8", "--pretty=format:%h\x1f%s\x1f%cr") or ""
    commits = [dict(zip(("hash", "subject", "when"), ln.split("\x1f"))) for ln in log.splitlines() if ln.count("\x1f") == 2]
    return {"git": True, "branch": branch, "changes": changes, "commits": commits}


def recent_files(root: str, days: int = 7, limit: int = 15) -> List[Dict[str, Any]]:
    """Files changed in the last `days` days, newest first (bounded walk)."""
    out: List[Dict[str, Any]] = []
    if not os.path.isdir(root):
        return out
    cutoff = time.time() - days * 86400
    seen = 0
    root_r = os.path.realpath(root)
    for base, dirs, files in os.walk(root_r):
        depth = os.path.relpath(base, root_r).count(os.sep)
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".") and depth < MAX_DEPTH]
        for n in files:
            seen += 1
            if seen > 5000:
                break
            p = os.path.join(base, n)
            if n.startswith(".") or os.path.islink(p):
                continue
            try:
                m = os.path.getmtime(p)
            except OSError:
                continue
            if m >= cutoff:
                out.append({"path": p, "rel": os.path.relpath(p, root_r), "modified": m})
    out.sort(key=lambda f: f["modified"], reverse=True)
    return out[:limit]
