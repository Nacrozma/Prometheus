"""
patch_gate.py — an automatic gate for self-modification.

Prometheus can propose a rewrite of its own source (prometheus.py, gui_orb.py).
A human approves the diff, but a plausible-looking diff can still break things.
This gate checks every proposal BEFORE it is saved and again before it is applied:

  1. it parses;
  2. the symbols the rest of the system depends on are still defined;
  3. the safety lists (DANGEROUS_TOOLS, protected file names...) have not lost entries;
  4. it is not a wholesale rewrite (a changed-lines ceiling);
  5. the project's own test suite, run in an isolated COPY of the project with a
     stripped environment (no API keys), shows no new failures compared with the
     same suite on the unpatched copy, and no tests have disappeared.

A patch that fails any check is rejected with the reasons, so the model can fix it;
it is never written to pending_patches/. Nothing here touches the live files.

Honest limits: this proves "the existing tests still pass" - not that the patch is
good, and not that it is free of malicious intent (a patch could behave differently
only outside the tests). It narrows the accident surface; the human review and the
confirmation before applying remain the real approval step.
"""

import ast
import difflib
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

MAX_FILE_BYTES = 1_500_000
DEFAULT_MAX_CHANGED_RATIO = 0.35
DEFAULT_TEST_TIMEOUT = 240

_baseline_cache: Dict[str, Dict[str, Any]] = {}
_cache_lock = threading.Lock()


def top_level_names(tree: ast.AST) -> Set[str]:
    names: Set[str] = set()
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                for n in ast.walk(t):
                    if isinstance(n, ast.Name):
                        names.add(n.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                names.add((a.asname or a.name).split(".")[0])
    return names


def assignment_strings(tree: ast.AST, name: str) -> Optional[Set[str]]:
    """Every string constant inside the value assigned to `name` at top level, or
    None if there is no such assignment."""
    found: Optional[Set[str]] = None
    for node in getattr(tree, "body", []):
        targets = []
        if isinstance(node, ast.Assign):
            targets, value = [t.id for t in node.targets if isinstance(t, ast.Name)], node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            targets, value = [node.target.id], node.value
        else:
            continue
        if name in targets:
            found = (found or set()) | {n.value for n in ast.walk(value)
                                         if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    return found


# ------------------------------------------------------------------------------
# running the project's tests in a copy
# ------------------------------------------------------------------------------
def _copy_project(repo_dir: str, dest: str, test_dir: str) -> List[str]:
    """Copy top-level *.py files and the test directory (py files only). Returns the relative paths."""
    copied: List[str] = []
    for fname in sorted(os.listdir(repo_dir)):
        src = os.path.join(repo_dir, fname)
        if fname.endswith(".py") and os.path.isfile(src):
            shutil.copy2(src, os.path.join(dest, fname))
            copied.append(fname)
    tsrc = os.path.join(repo_dir, test_dir)
    if os.path.isdir(tsrc):
        os.makedirs(os.path.join(dest, test_dir), exist_ok=True)
        for fname in sorted(os.listdir(tsrc)):
            if fname.endswith(".py") and os.path.isfile(os.path.join(tsrc, fname)):
                shutil.copy2(os.path.join(tsrc, fname), os.path.join(dest, test_dir, fname))
                copied.append(f"{test_dir}/{fname}")
    return copied


def _project_key(root: str, rels: Iterable[str]) -> str:
    h = hashlib.sha256()
    for rel in sorted(rels):
        h.update(rel.encode())
        with open(os.path.join(root, rel), "rb") as f:
            h.update(hashlib.sha256(f.read()).digest())
    return h.hexdigest()


def run_unittests(project_dir: str, test_dir: str = "tests", timeout: int = DEFAULT_TEST_TIMEOUT) -> Dict[str, Any]:
    """Run `python -m unittest discover` inside project_dir with a minimal environment.
    Returns {"ran", "failed": set of test ids, "ok", "timed_out", "tail"}."""
    home = tempfile.mkdtemp(prefix="gate_home_")
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
           "QT_QPA_PLATFORM": "offscreen", "PROMETHEUS_FAST_BOOT": "1", "HOME": home, "USERPROFILE": home,
           "PROMETHEUS_PATCH_GATE_ACTIVE": "1"}  # lets a test know it is already running inside a gate (no recursion)
    for keep in ("SYSTEMROOT", "TEMP", "TMP", "LD_LIBRARY_PATH", "VIRTUAL_ENV"):
        if keep in os.environ:
            env[keep] = os.environ[keep]
    out_path = os.path.join(home, "out.txt")
    timed_out = False
    try:
        kwargs: Dict[str, Any] = {"start_new_session": True} if os.name != "nt" else {}
        with open(out_path, "wb") as fo:
            proc = subprocess.Popen([sys.executable, "-m", "unittest", "discover", "-s", test_dir],
                                    cwd=project_dir, env=env, stdin=subprocess.DEVNULL, stdout=fo,
                                    stderr=subprocess.STDOUT, **kwargs)
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    if os.name != "nt":
                        os.killpg(proc.pid, 9)
                    else:
                        proc.kill()
                except OSError:
                    pass
                proc.wait()
        with open(out_path, "rb") as f:
            text = f.read(2_000_000).decode("utf-8", errors="replace")
    finally:
        shutil.rmtree(home, ignore_errors=True)
    ran_match = re.search(r"^Ran (\d+) tests?", text, flags=re.M)
    failed = {m.group(0).strip() for m in re.finditer(r"^(?:FAIL|ERROR): .+$", text, flags=re.M)}
    return {"ran": int(ran_match.group(1)) if ran_match else 0, "failed": failed,
            "ok": bool(ran_match) and not failed and not timed_out and proc.returncode == 0,
            "timed_out": timed_out, "tail": "\n".join(text.strip().splitlines()[-12:])}


# ------------------------------------------------------------------------------
# the gate
# ------------------------------------------------------------------------------
def validate_patch(repo_dir: str, target_file: str, new_content: str,
                   required_symbols: Optional[Iterable[str]] = None,
                   protected_assignments: Iterable[str] = (),
                   max_changed_ratio: float = DEFAULT_MAX_CHANGED_RATIO,
                   run_tests: bool = True, test_dir: str = "tests",
                   timeout: int = DEFAULT_TEST_TIMEOUT) -> Dict[str, Any]:
    """Check a proposed full-file replacement. Returns
    {"accepted": bool, "problems": [str], "checks": [{"name","passed","detail"}], "tests": {...}|None}."""
    checks: List[Dict[str, Any]] = []

    def check(name: str, passed: bool, detail: str = "") -> bool:
        checks.append({"name": name, "passed": passed, "detail": detail})
        return passed

    target_path = os.path.join(repo_dir, target_file)
    try:
        with open(target_path, "r", encoding="utf-8", errors="replace") as f:
            current = f.read()
    except OSError as e:
        check("current file readable", False, str(e))
        return _result(checks, None)

    if not check("size", 0 < len(new_content.encode("utf-8")) <= MAX_FILE_BYTES,
                 f"{len(new_content.encode('utf-8'))} bytes (limit {MAX_FILE_BYTES})"):
        return _result(checks, None)
    try:
        new_tree = ast.parse(new_content)
        check("parses", True)
    except SyntaxError as e:
        check("parses", False, f"{e.msg} (line {e.lineno})")
        return _result(checks, None)
    cur_tree = ast.parse(current) if current.strip() else ast.parse("")

    if required_symbols:
        missing = sorted(set(required_symbols) - top_level_names(new_tree))
        check("required symbols still defined", not missing, f"missing: {', '.join(missing)}" if missing else "")

    for name in protected_assignments:
        before, after = assignment_strings(cur_tree, name), assignment_strings(new_tree, name)
        if before is None:
            continue
        lost = sorted(before - (after or set()))
        check(f"safety list {name} not weakened", after is not None and not lost,
              f"entries removed: {', '.join(lost)}" if lost else ("assignment was removed" if after is None else ""))

    a, b = current.splitlines(), new_content.splitlines()
    ratio = 1.0 - difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() if (a or b) else 0.0
    check("change size", ratio <= max_changed_ratio, f"{ratio:.0%} of lines changed (limit {max_changed_ratio:.0%})")

    if not all(c["passed"] for c in checks):
        return _result(checks, None)  # don't spend minutes on tests for a patch that is already rejected
    if not run_tests:
        check("tests", False, "test run disabled - cannot verify the patch")
        return _result(checks, None)

    tests_report = _test_against_copy(repo_dir, target_file, new_content, test_dir, timeout, check)
    return _result(checks, tests_report)


def _test_against_copy(repo_dir, target_file, new_content, test_dir, timeout, check) -> Optional[Dict[str, Any]]:
    if not os.path.isdir(os.path.join(repo_dir, test_dir)) or not any(
            f.startswith("test") and f.endswith(".py") for f in os.listdir(os.path.join(repo_dir, test_dir))):
        check("tests exist", False, f"no tests found in {test_dir}/ - a self-patch cannot be verified without them")
        return None
    work = tempfile.mkdtemp(prefix="patch_gate_")
    try:
        rels = _copy_project(repo_dir, work, test_dir)
        key = _project_key(work, rels)
        with _cache_lock:
            baseline = _baseline_cache.get(key)
        if baseline is None:
            baseline = run_unittests(work, test_dir, timeout)
            with _cache_lock:
                _baseline_cache.clear()  # one entry is plenty; it is only valid for this exact project state
                _baseline_cache[key] = baseline
        if not baseline["ran"] or baseline["timed_out"]:
            check("baseline tests usable", False, "the unpatched project's own tests did not run: " + baseline["tail"][-300:])
            return {"baseline": _summ(baseline), "patched": None}

        with open(os.path.join(work, target_file), "w", encoding="utf-8", newline="\n") as f:
            f.write(new_content)
        patched = run_unittests(work, test_dir, timeout)
        new_failures = sorted(patched["failed"] - baseline["failed"])
        check("tests ran in time", not patched["timed_out"], f"timed out after {timeout}s" if patched["timed_out"] else "")
        check("no new test failures", not new_failures, "; ".join(new_failures[:6]) if new_failures else
              f"{patched['ran']} tests, {len(patched['failed'])} failing (same as before: {len(baseline['failed'])})")
        check("no tests disappeared", patched["ran"] >= baseline["ran"],
              f"{patched['ran']} tests now vs {baseline['ran']} before")
        return {"baseline": _summ(baseline), "patched": _summ(patched)}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _summ(r: Dict[str, Any]) -> Dict[str, Any]:
    return {"ran": r["ran"], "failed": sorted(r["failed"])[:10], "timed_out": r["timed_out"]}


def _result(checks, tests) -> Dict[str, Any]:
    problems = [f"{c['name']}: {c['detail']}".rstrip(": ") for c in checks if not c["passed"]]
    return {"accepted": not problems, "problems": problems, "checks": checks, "tests": tests}
