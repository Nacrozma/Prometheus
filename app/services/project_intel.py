"""Project intelligence for the Engineering workbench: what a project is made of, where its tests are,
and plain-text code search. Read-only, bounded, inside the workspace only (links that leave it are
skipped, as are hidden and dependency folders)."""

from __future__ import annotations

import os
from collections import Counter
from typing import Any, Dict, List

from .search import SKIP_DIRS
from .workspace_info import inside

LANGS = {".py": "Python", ".js": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript", ".jsx": "JavaScript", ".rs": "Rust", ".go": "Go", ".java": "Java", ".kt": "Kotlin", ".c": "C", ".h": "C/C++ header", ".cpp": "C++", ".hpp": "C/C++ header", ".cs": "C#", ".rb": "Ruby", ".php": "PHP", ".swift": "Swift", ".ino": "Arduino", ".md": "Markdown", ".json": "JSON", ".toml": "TOML", ".yaml": "YAML", ".yml": "YAML", ".html": "HTML", ".css": "CSS", ".sh": "Shell", ".ps1": "PowerShell", ".sql": "SQL"}
TEXTY = set(LANGS) | {".txt", ".cfg", ".ini", ".xml", ".bat", ".lua"}
MAX_FILES = 8000
MAX_BYTES = 400_000


def _walk(root: str):
    seen = 0
    rr = os.path.realpath(root)
    for base, dirs, files in os.walk(rr):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for n in files:
            seen += 1
            if seen > MAX_FILES:
                return
            p = os.path.join(base, n)
            if n.startswith(".") or (os.path.islink(p) and not inside(rr, p)):
                continue
            yield p


def is_test_file(path: str) -> bool:
    n = os.path.basename(path).lower()
    parts = path.replace("\\", "/").lower().split("/")
    return n.startswith("test_") or n.endswith(("_test.py", "_test.go", ".test.ts", ".test.js", ".spec.ts", ".spec.js", "tests.rs")) or ("tests" in parts[:-1] and n.endswith(tuple(LANGS)))


def summary(workspace: str, project: str) -> Dict[str, Any]:
    if not inside(workspace, project):
        return {"error": "outside the workspace"}
    langs: Counter = Counter()
    lines = 0
    files = 0
    tests: List[str] = []
    entry: List[str] = []
    for p in _walk(project):
        files += 1
        ext = os.path.splitext(p)[1].lower()
        rel = os.path.relpath(p, project)
        if ext in LANGS:
            langs[LANGS[ext]] += 1
        if is_test_file(p):
            tests.append(rel)
        if os.path.basename(p).lower() in ("main.py", "__main__.py", "app.py", "index.js", "index.ts", "main.rs", "main.go", "cargo.toml", "package.json", "pyproject.toml", "setup.py", "requirements.txt", "makefile", "readme.md"):
            entry.append(rel)
        if ext in TEXTY:
            try:
                if os.path.getsize(p) <= MAX_BYTES:
                    with open(p, "rb") as f:
                        lines += f.read().count(b"\n")
            except OSError:
                pass
    return {"files": files, "lines": lines, "languages": langs.most_common(8), "tests": sorted(tests)[:200], "entry": sorted(entry)[:20]}


def grep(workspace: str, project: str, needle: str, limit: int = 80) -> List[Dict[str, Any]]:
    """Plain, case-insensitive substring search in text files of a project."""
    if not inside(workspace, project) or len(needle.strip()) < 2:
        return []
    q = needle.lower()
    out: List[Dict[str, Any]] = []
    for p in _walk(project):
        if os.path.splitext(p)[1].lower() not in TEXTY:
            continue
        try:
            if os.path.getsize(p) > MAX_BYTES:
                continue
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f, 1):
                    if q in line.lower():
                        out.append({"path": p, "rel": os.path.relpath(p, project), "line": i, "text": line.strip()[:200]})
                        if len(out) >= limit:
                            return out
        except OSError:
            continue
    return out
