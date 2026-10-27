"""
safety.py - guard rails around Prometheus's autonomy.

  * Policy       - an operator-owned permissions file (permissions.json). It can only make
                   things STRICTER: deny tools outright, require confirmation for extra
                   tools, and restrict where write_file/edit_file may write. It can never
                   remove a built-in confirmation. A missing file means "no extra rules";
                   an unreadable or malformed file is reported and the built-in rules
                   stand (failing closed on a typo would lock the operator out of everything).
  * AuditLog     - append-only JSON-lines record of every tool call (what, with which
                   arguments, outcome). Entries are hash-chained, so editing or deleting
                   an old line is detectable with verify(). Secret-looking values are
                   redacted and long values truncated before anything is written.
  * UndoJournal  - before write_file/edit_file changes a file, its previous content is saved.
                   undo() restores it, but refuses if the file changed again since (it will
                   not clobber work it did not do).

Honest scope: the audit chain detects tampering, it cannot prevent a process with file access
from rewriting the whole file; the undo journal covers the workspace file tools only, not
shell commands.
"""
import hashlib
import json
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from state_io import atomic_write_json, read_json_state

SECRET_KEY_RE = re.compile(r"(api[_-]?key|secret|token|password|passwd|authorization|credential)", re.I)
SECRET_VALUE_RE = re.compile(r"(sk-[A-Za-z0-9_\-]{12,}|gsk_[A-Za-z0-9]{12,}|AIza[0-9A-Za-z_\-]{20,}|tvly-[A-Za-z0-9\-]{10,}|ghp_[A-Za-z0-9]{20,})")
MAX_VALUE_CHARS = 300
GENESIS = "0" * 64


def redact(value: Any, depth: int = 0) -> Any:
    """A JSON-safe copy of `value` with secrets masked and long strings truncated."""
    if depth > 4:
        return "<nested>"
    if isinstance(value, dict):
        return {str(k)[:60]: ("<redacted>" if SECRET_KEY_RE.search(str(k)) else redact(v, depth + 1))
                for k, v in list(value.items())[:30]}
    if isinstance(value, (list, tuple)):
        return [redact(v, depth + 1) for v in list(value)[:20]]
    if isinstance(value, str):
        s = SECRET_VALUE_RE.sub("<redacted>", value)
        return s if len(s) <= MAX_VALUE_CHARS else s[:MAX_VALUE_CHARS] + f"...<{len(value) - MAX_VALUE_CHARS} more chars>"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return redact(str(value), depth + 1)


# ------------------------------------------------------------------------------ policy
class Policy:
    def __init__(self, path: str):
        self.path = path
        self.deny: Dict[str, str] = {}
        self.ask: set = set()
        self.write_scopes: List[str] = []
        self.problems: List[str] = []
        self.reload()

    def reload(self) -> None:
        self.deny, self.ask, self.write_scopes, self.problems = {}, set(), [], []
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:   # read directly: a typo must not get the file quarantined
                data = json.load(f)
        except (OSError, ValueError) as e:
            self.problems.append(f"permissions file unreadable ({e}); only the built-in rules apply")
            return
        if not isinstance(data, dict):
            self.problems.append("permissions file must be a JSON object; only the built-in rules apply")
            return
        deny = data.get("deny", {})
        if isinstance(deny, list):
            deny = {n: "denied by permissions.json" for n in deny}
        if isinstance(deny, dict):
            self.deny = {str(k): str(v)[:200] for k, v in deny.items()}
        else:
            self.problems.append("'deny' must be a list or an object")
        ask = data.get("ask", [])
        if isinstance(ask, list):
            self.ask = {str(a) for a in ask}
        else:
            self.problems.append("'ask' must be a list of tool names")
        scopes = data.get("write_scopes", [])
        if isinstance(scopes, list):
            self.write_scopes = [str(s).strip("/\\") for s in scopes if str(s).strip("/\\")]
        else:
            self.problems.append("'write_scopes' must be a list of workspace-relative folders")

    def check(self, tool: str) -> Optional[str]:
        """A refusal reason if the tool is denied, else None."""
        return f"'{tool}' is disabled by the operator: {self.deny[tool]}" if tool in self.deny else None

    def requires_confirmation(self, tool: str) -> bool:
        return tool in self.ask

    def path_allowed(self, rel_path: str) -> bool:
        """rel_path is workspace-relative and already resolved. No scopes configured = everywhere."""
        if not self.write_scopes:
            return True
        rel = rel_path.replace("\\", "/").strip("/")
        return any(rel == s.replace("\\", "/") or rel.startswith(s.replace("\\", "/") + "/") for s in self.write_scopes)


# ------------------------------------------------------------------------------ audit log
def _entry_hash(prev: str, body: str) -> str:
    return hashlib.sha256((prev + body).encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self, path: str, max_bytes: int = 5_000_000):
        self.path = path
        self.max_bytes = max_bytes
        self._lock = threading.RLock()
        self._last = GENESIS
        self._seq = 0
        self._resume()

    def _resume(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                last = None
                for line in f:
                    if line.strip():
                        last = line
            if last:
                rec = json.loads(last)
                self._last, self._seq = rec["hash"], int(rec["seq"])
        except (OSError, ValueError, KeyError):
            pass  # unreadable tail: verify() will report it; new entries start a fresh chain segment

    def record(self, tool: str, args: Any, outcome: str, detail: str = "", latency_s: float = 0.0) -> bool:
        """Append one entry. Never raises (auditing must not break the thing it audits)."""
        try:
            with self._lock:
                self._rotate_if_needed()
                self._seq += 1
                body = json.dumps({"seq": self._seq, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "tool": str(tool)[:80],
                                   "args": redact(args), "outcome": outcome, "detail": str(redact(detail))[:300],
                                   "ms": round(latency_s * 1000, 1)}, sort_keys=True, ensure_ascii=False)
                digest = _entry_hash(self._last, body)
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"body": body, "prev": self._last, "hash": digest, "seq": self._seq}) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
                self._last = digest
                return True
        except Exception:
            return False

    def _rotate_if_needed(self) -> None:
        try:
            if os.path.getsize(self.path) > self.max_bytes:
                os.replace(self.path, f"{self.path}.{time.strftime('%Y%m%d%H%M%S')}")
                self._last, self._seq = GENESIS, 0
        except OSError:
            pass

    def tail(self, n: int = 20) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                lines = [ln for ln in f if ln.strip()][-n:]
            for ln in lines:
                rec = json.loads(ln)
                out.append(json.loads(rec["body"]))
        except (OSError, ValueError, KeyError):
            pass
        return out

    def verify(self) -> Tuple[bool, str]:
        """Walk the chain. (True, 'N entries') or (False, what is wrong and where)."""
        prev, count = GENESIS, 0
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for lineno, ln in enumerate(f, 1):
                    if not ln.strip():
                        continue
                    rec = json.loads(ln)
                    if rec["prev"] != prev:
                        return False, f"chain broken at line {lineno}: an earlier entry was removed or changed"
                    if _entry_hash(prev, rec["body"]) != rec["hash"]:
                        return False, f"entry at line {lineno} was modified"
                    prev, count = rec["hash"], count + 1
        except FileNotFoundError:
            return True, "0 entries (no log yet)"
        except (OSError, ValueError, KeyError) as e:
            return False, f"log unreadable or malformed: {e}"
        return True, f"{count} entries, chain intact"


# ------------------------------------------------------------------------------ undo journal
def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class UndoJournal:
    def __init__(self, directory: str, max_entries: int = 50, max_file_bytes: int = 2_000_000):
        self.dir = directory
        self.max_entries = max_entries
        self.max_file_bytes = max_file_bytes
        self.index_path = os.path.join(directory, "index.json")
        self._lock = threading.RLock()

    def _load(self) -> List[Dict[str, Any]]:
        try:
            data = read_json_state(self.index_path)
            return data["entries"] if isinstance(data, dict) and isinstance(data.get("entries"), list) else []
        except (OSError, ValueError, KeyError):
            return []

    def _save(self, entries: List[Dict[str, Any]]) -> None:
        os.makedirs(self.dir, exist_ok=True)
        atomic_write_json(self.index_path, {"schema_version": 1, "entries": entries}, indent=1, prefix="undo_")

    def snapshot(self, path: str) -> Optional[str]:
        """Call BEFORE modifying `path`. Returns an entry id (pass it to commit()), or None if this
        change can't be journalled (too large) - the caller still proceeds; undo just won't cover it."""
        with self._lock:
            try:
                existed = os.path.isfile(path)
                data = b""
                if existed:
                    if os.path.getsize(path) > self.max_file_bytes:
                        return None
                    with open(path, "rb") as f:
                        data = f.read()
                entry_id = time.strftime("%Y%m%d%H%M%S") + "_" + _sha((path + str(time.time())).encode())[:8]
                os.makedirs(self.dir, exist_ok=True)
                if existed:
                    with open(os.path.join(self.dir, entry_id + ".bak"), "wb") as f:
                        f.write(data)
                entries = self._load()
                entries.append({"id": entry_id, "path": path, "existed": existed, "before_sha": _sha(data) if existed else None,
                                "after_sha": None, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "undone": False})
                for old in entries[:-self.max_entries]:
                    try:
                        os.remove(os.path.join(self.dir, old["id"] + ".bak"))
                    except OSError:
                        pass
                self._save(entries[-self.max_entries:])
                return entry_id
            except OSError:
                return None

    def commit(self, entry_id: Optional[str]) -> None:
        """Call AFTER the change: records the resulting hash so undo can detect later edits."""
        if not entry_id:
            return
        with self._lock:
            entries = self._load()
            for e in entries:
                if e["id"] == entry_id:
                    try:
                        with open(e["path"], "rb") as f:
                            e["after_sha"] = _sha(f.read())
                    except OSError:
                        e["after_sha"] = None
            self._save(entries)

    def abort(self, entry_id: Optional[str]) -> None:
        """The change failed before touching the file: drop the entry."""
        if not entry_id:
            return
        with self._lock:
            entries = [e for e in self._load() if e["id"] != entry_id]
            self._save(entries)
            try:
                os.remove(os.path.join(self.dir, entry_id + ".bak"))
            except OSError:
                pass

    def list(self, n: int = 10) -> List[Dict[str, Any]]:
        return [e for e in self._load() if not e["undone"]][-n:]

    def undo(self) -> Dict[str, Any]:
        """Revert the most recent journalled change that hasn't been undone."""
        with self._lock:
            entries = self._load()
            pending = [e for e in entries if not e["undone"]]
            if not pending:
                return {"status": "error", "message": "nothing to undo"}
            e = pending[-1]
            path = e["path"]
            current_sha = None
            if os.path.isfile(path):
                with open(path, "rb") as f:
                    current_sha = _sha(f.read())
            if e.get("after_sha") is not None and current_sha != e["after_sha"]:
                return {"status": "error", "path": path, "message":
                        "the file was changed again after Prometheus's edit; undoing would discard those changes. "
                        "Nothing was touched."}
            try:
                if e["existed"]:
                    with open(os.path.join(self.dir, e["id"] + ".bak"), "rb") as f:
                        before = f.read()
                    if _sha(before) != e["before_sha"]:
                        return {"status": "error", "path": path, "message": "the saved backup is damaged; nothing was touched"}
                    self._restore_bytes(path, before)
                elif os.path.isfile(path):
                    os.remove(path)
            except OSError as err:
                return {"status": "error", "path": path, "message": f"could not restore: {err}"}
            e["undone"] = True
            self._save(entries)
            return {"status": "success", "path": path, "action": "restored previous content" if e["existed"] else "removed the file Prometheus created"}

    @staticmethod
    def _restore_bytes(path: str, data: bytes) -> None:
        import tempfile
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", prefix=".undo_")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
