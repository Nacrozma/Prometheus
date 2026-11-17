"""Read-only access to an Obsidian vault for the desktop's knowledge reader.

Lists Markdown notes (bounded walk, `.obsidian` and `.trash` skipped, links that leave the vault
ignored), reads a note (size-capped, inside the vault only), and computes links from the notes' own
`[[wikilinks]]`: outgoing links of a note and the notes that link to it. Nothing is written here; writing
to the vault stays with the approval-gated export_obsidian tool.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List

WIKILINK = re.compile(r"\[\[([^\]|#^]+)(?:[#^][^\]|]*)?(?:\|[^\]]*)?\]\]")
SKIP = {".obsidian", ".trash", ".git", "node_modules"}
MAX_NOTES = 3000
MAX_NOTE_BYTES = 300_000


def _inside(vault: str, path: str) -> bool:
    v, p = os.path.realpath(vault), os.path.realpath(path)
    return p == v or p.startswith(v + os.sep)


def notes(vault: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not vault or not os.path.isdir(vault):
        return out
    for base, dirs, files in os.walk(vault):
        dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith(".")]
        for n in files:
            if not n.lower().endswith(".md"):
                continue
            p = os.path.join(base, n)
            if os.path.islink(p) and not _inside(vault, p):
                continue
            try:
                m = os.path.getmtime(p)
            except OSError:
                continue
            out.append({"name": n[:-3], "path": p, "rel": os.path.relpath(p, vault), "modified": m})
            if len(out) >= MAX_NOTES:
                return sorted(out, key=lambda x: -x["modified"])
    return sorted(out, key=lambda x: -x["modified"])


def read(vault: str, path: str) -> str:
    if not _inside(vault, path) or not os.path.isfile(path):
        raise ValueError("not a note in this vault")
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read(MAX_NOTE_BYTES)


def links(text: str) -> List[str]:
    seen: List[str] = []
    for m in WIKILINK.finditer(text or ""):
        name = m.group(1).strip()
        if name and name not in seen:
            seen.append(name)
    return seen


def backlinks(vault: str, name: str, all_notes: List[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Notes whose own [[links]] point to `name` (by note name, case-insensitive)."""
    target = name.lower()
    out = []
    for n in all_notes if all_notes is not None else notes(vault):
        if n["name"].lower() == target:
            continue
        try:
            text = read(vault, n["path"])
        except (OSError, ValueError):
            continue
        if any(l.lower().split("/")[-1] == target for l in links(text)):
            out.append(n)
    return out


def search(vault: str, query: str, all_notes: List[Dict[str, Any]], limit: int = 60) -> List[Dict[str, Any]]:
    q = query.lower().strip()
    if not q:
        return all_notes[:limit]
    hits = [n for n in all_notes if q in n["name"].lower()]
    for n in all_notes:
        if len(hits) >= limit:
            break
        if n in hits:
            continue
        try:
            if q in read(vault, n["path"]).lower():
                hits.append(n)
        except (OSError, ValueError):
            pass
    return hits[:limit]
