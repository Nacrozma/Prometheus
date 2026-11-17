"""Backup export: a .zip of the data folder that never contains credentials.

Excluded: .env files, anything whose name suggests a secret or key, crash/fault logs (they can hold
request details), temporary files and caches. API keys live in the OS credential store, not in the data
folder, so they are never in the archive. The archive can be imported with Settings → Data → Import
after unpacking it to a folder.
"""

from __future__ import annotations

import os
import time
import zipfile
from typing import Dict, List

EXCLUDE_NAMES = {".env", "desktop_crash.log", "desktop_faults.log", "prometheus.log"}
EXCLUDE_DIRS = {"__pycache__", ".cache", "sandbox_runs", "tmp"}
SECRETISH = ("secret", "credential", "token", "apikey", "api_key", ".pem", ".key")


def excluded(rel: str) -> bool:
    name = os.path.basename(rel).lower()
    parts = rel.replace("\\", "/").split("/")
    if any(p in EXCLUDE_DIRS for p in parts[:-1]):
        return True
    if name in EXCLUDE_NAMES or name.startswith(".env.") or name.endswith((".tmp", ".lock")) or ".corrupt." in name:
        return True
    return any(s in name for s in SECRETISH)


def export(data_dir: str, dest_zip: str) -> Dict[str, object]:
    data_dir = os.path.realpath(data_dir)
    dest = os.path.realpath(dest_zip)
    if dest.startswith(data_dir + os.sep):
        raise ValueError("Choose a place outside the data folder for the backup.")
    files: List[str] = []
    skipped = 0
    tmp = dest + ".partial"
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for base, dirs, names in os.walk(data_dir):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for n in names:
                path = os.path.join(base, n)
                rel = os.path.relpath(path, data_dir)
                if os.path.islink(path) or excluded(rel):
                    skipped += 1
                    continue
                z.write(path, rel)
                files.append(rel)
        z.writestr("PROMETHEUS_BACKUP.txt", f"Prometheus data backup made {time.strftime('%Y-%m-%d %H:%M')}.\nNo API keys or .env files are included. Unzip to a folder and use Settings > Data > Import to restore.\n")
    os.replace(tmp, dest)
    return {"path": dest, "files": len(files), "skipped": skipped}
