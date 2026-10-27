"""
state_io.py — crash-safe file helpers shared by every module that persists state.

Dependency-free (standard library only) so any module can import it without
creating import cycles.

  * atomic_write_json / atomic_write_text - temp file in the SAME directory,
    flush + fsync, then os.replace(); the live file is never left half-written,
    and a failed write cleans up its temp file.
  * read_json_state - retries briefly on OS errors (Windows can refuse a read
    while another process is mid-replace); a file that is genuinely corrupt is
    moved aside to <name>.corrupt.<timestamp> instead of being left in place to
    be overwritten.
  * quarantine_file - the "move it aside" step on its own.
"""

import json
import logging
import os
import tempfile
import time
from typing import Any, Callable, Optional

logger = logging.getLogger("PrometheusState")


def quarantine_file(path: str) -> Optional[str]:
    """Move an unreadable state file to <path>.corrupt.<timestamp>. Returns the
    new path, or None if it could not be moved."""
    dest = f"{path}.corrupt.{int(time.time())}"
    try:
        os.replace(path, dest)
        logger.error(f"Corrupt file moved aside: {dest}")
        return dest
    except OSError as e:
        logger.error(f"Could not move corrupt file {path} aside: {e}")
        return None


def _atomic_write(path: str, write_body: Callable[[Any], None], prefix: str, newline: Optional[str]) -> bool:
    temp_path: Optional[str] = None
    try:
        dir_name = os.path.dirname(os.path.abspath(path))
        fd, temp_path = tempfile.mkstemp(dir=dir_name, prefix=prefix, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8", newline=newline) as f:
            write_body(f)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(5):
            try:
                os.replace(temp_path, path)
                break
            except PermissionError:  # Windows: target briefly held open elsewhere
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))
        temp_path = None
        return True
    except Exception as e:
        logger.error(f"Atomic write failed for {path}: {e}")
        if temp_path:
            try:
                os.remove(temp_path)
            except OSError:
                pass
        return False


def atomic_write_json(path: str, data: Any, indent: Optional[int] = 2, prefix: str = "state_") -> bool:
    return _atomic_write(path, lambda f: json.dump(data, f, ensure_ascii=False, indent=indent), prefix, None)


def atomic_write_text(path: str, text: str, prefix: str = "state_") -> bool:
    """Writes `text` with plain '\\n' line endings regardless of platform."""
    return _atomic_write(path, lambda f: f.write(text), prefix, "\n")


def read_json_state(path: str, attempts: int = 5) -> Any:
    """Read a JSON state file. Raises json.JSONDecodeError (after quarantining the
    file) if it is corrupt, or the last OSError if every retry fails."""
    last_err: Optional[Exception] = None
    for attempt in range(attempts):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            quarantine_file(path)
            raise
        except UnicodeDecodeError:
            quarantine_file(path)
            raise json.JSONDecodeError("file is not valid UTF-8", "", 0)
        except OSError as e:
            last_err = e
            time.sleep(0.05 * (attempt + 1))
    raise last_err  # type: ignore[misc]
