"""Import personal data from an existing Prometheus folder (for example a source checkout used from the
terminal) into the desktop app's data folder.

Rules: the source is only read, never changed or deleted. Anything already in the destination that
would be replaced is first backed up to <data>/backups/pre-import-<time>/. JSON state files are
validated before copying, every copied file is verified by SHA-256, and a failed import restores the
backup. Keys (.env) are never copied: they go into the credential store through Settings.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from typing import List

# Personal state files and folders, as the core names them (see prometheus.py, all under DATA_DIR).
STATE_FILES = (
    "memory.json", "vector_store.json", "memory_graph.json", "skills.json", "tool_stats.json", "audit.jsonl",
    "task_state.json", "schedule.json", "usage_log.jsonl", "permissions.json", "session.json", "prometheus_config.json",
)
STATE_DIRS = ("sessions", "dynamic_tools", ".prometheus_undo", "pending_patches")
JSON_FILES = {n for n in STATE_FILES if n.endswith(".json")}


class MigrationError(Exception):
    pass


@dataclass
class Plan:
    source: str
    dest: str
    files: List[str] = field(default_factory=list)  # relative paths to copy
    replaces: List[str] = field(default_factory=list)  # of those, already present in dest
    invalid: List[str] = field(default_factory=list)  # JSON files that do not parse (skipped)
    skipped_env: bool = False

    def summary(self) -> str:
        parts = [f"{len(self.files)} files to import from {self.source}"]
        if self.replaces:
            parts.append(f"{len(self.replaces)} existing files will be backed up and replaced")
        if self.invalid:
            parts.append(f"{len(self.invalid)} unreadable files will be left behind: {', '.join(self.invalid)}")
        if self.skipped_env:
            parts.append("the .env file is not copied (add keys in Settings → Providers)")
        return "; ".join(parts) + "."


def _sha(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def plan(source: str, dest: str) -> Plan:
    source, dest = os.path.realpath(source), os.path.realpath(dest)
    if source == dest:
        raise MigrationError("that is already the data folder")
    if not os.path.isdir(source):
        raise MigrationError("the folder does not exist")
    p = Plan(source, dest, skipped_env=os.path.exists(os.path.join(source, ".env")))
    rels: List[str] = [n for n in STATE_FILES if os.path.isfile(os.path.join(source, n))]
    for d in STATE_DIRS:
        root = os.path.join(source, d)
        for dirpath, _, names in os.walk(root):
            for n in names:
                rels.append(os.path.relpath(os.path.join(dirpath, n), source))
    for rel in rels:
        if rel in JSON_FILES:
            try:
                with open(os.path.join(source, rel), encoding="utf-8") as f:
                    json.load(f)
            except (OSError, ValueError):
                p.invalid.append(rel)
                continue
        p.files.append(rel)
        if os.path.exists(os.path.join(dest, rel)):
            p.replaces.append(rel)
    if not p.files:
        raise MigrationError("no Prometheus data was found in that folder")
    return p


def apply(p: Plan) -> str:
    """Run a plan. Returns the backup folder ('' if nothing needed backing up)."""
    backup = ""
    if p.replaces:
        backup = os.path.join(p.dest, "backups", "pre-import-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
        for rel in p.replaces:
            target = os.path.join(backup, rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(os.path.join(p.dest, rel), target)
            if _sha(target) != _sha(os.path.join(p.dest, rel)):
                raise MigrationError(f"backup of {rel} could not be verified; nothing was imported")
    done: List[str] = []
    try:
        for rel in p.files:
            src, dst = os.path.join(p.source, rel), os.path.join(p.dest, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            tmp = dst + ".importing"
            shutil.copy2(src, tmp)
            if _sha(tmp) != _sha(src):
                os.remove(tmp)
                raise MigrationError(f"{rel} did not copy correctly")
            os.replace(tmp, dst)  # atomic per file
            done.append(rel)
    except Exception as e:
        # Put the destination back as it was: restore backed-up files, remove newly added ones.
        for rel in done:
            dst = os.path.join(p.dest, rel)
            if rel in p.replaces and backup:
                shutil.copy2(os.path.join(backup, rel), dst)
            else:
                try:
                    os.remove(dst)
                except OSError:
                    pass
        raise MigrationError(f"import stopped and was rolled back: {e}") from None
    return backup
