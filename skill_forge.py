"""
skill_forge.py — verified skill acquisition for Prometheus.

A "skill" is a small Python module the model writes for itself (a unit converter,
a beam-deflection calculator...). The old flow wrote whatever the model produced
straight to disk and later imported it INSIDE Prometheus's own process. This
replaces that with a pipeline where nothing is installed until it has earned it:

  1. POLICY GATE   static checks on the code and its tests: an allowlist of pure-
                   computation imports, no eval/exec/open/getattr, no dunder
                   escape hatches, no work at import time, a real execute().
  2. TESTS         the model must supply tests; they run against the skill in an
                   isolated process (Docker with no network when available, else a
                   resource-limited subprocess). Any failure, crash or timeout
                   rejects the skill and NOTHING is installed.
  3. VERSIONING    every accepted skill is stored as a numbered version with its
                   tests; a bad new version rolls back to the last good one (whose
                   tests are re-run first).
  4. SANDBOXED USE skills are executed through the same isolated runner, never
                   imported into Prometheus; the active file's hash is checked on
                   every call, so a skill edited behind the registry's back refuses
                   to run.

Threat model, stated plainly: this protects against buggy or careless model-written
code, and makes accidents and prompt-injected junk fail closed. The policy gate is a
filter, NOT a security boundary (Python code can't be perfectly statically vetted).
The real boundary is the sandbox - strong with Docker (no network, read-only
filesystem, capped memory/CPU/processes), best-effort without it - plus the human
confirmation Prometheus requires before installing a skill.
"""

import ast
import datetime
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from typing import Any, Dict, List, Optional, Tuple

from state_io import atomic_write_json, atomic_write_text, read_json_state

logger = logging.getLogger("PrometheusSkills")

SKILL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,39}$")
MAX_CODE_CHARS = 20_000
MAX_TESTS_CHARS = 20_000
MAX_TESTS = 50
MAX_RESULT_CHARS = 20_000
TEST_TIMEOUT_SECONDS = 30
RUN_TIMEOUT_SECONDS = 10
MAX_OUTPUT_BYTES = 200_000

# Pure-computation modules. Deliberately absent: os, sys, subprocess, socket, pathlib,
# shutil, io (io.open), pickle, importlib, ctypes, urllib/http, pandas (reads files)...
ALLOWED_IMPORTS = frozenset("""
math cmath statistics fractions decimal itertools functools operator collections heapq bisect array
string re textwrap unicodedata difflib json csv datetime calendar time random hashlib base64 binascii
struct copy pprint enum dataclasses typing abc numbers numpy scipy sympy
""".split())
_ALLOWED_FROM = {"io": {"StringIO", "BytesIO"}}

BANNED_NAMES = frozenset("""
eval exec compile __import__ open input breakpoint exit quit globals locals vars getattr setattr delattr help
""".split())
BANNED_ATTRS = frozenset("""
system popen spawn fork execv execve remove unlink rmdir rmtree load loadtxt genfromtxt fromfile tofile save savez
savetxt memmap read_csv read_excel to_csv urlopen urlretrieve __class__ __bases__ __subclasses__ __globals__
__builtins__ __code__ __closure__ __mro__ __import__ __loader__ __spec__ __getattribute__ __reduce__ __reduce_ex__
__dict__ __base__ __self__ __func__ f_globals f_locals gi_frame tb_frame
""".split())
_TOP_LEVEL_OK = (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef, ast.Assign, ast.AnnAssign, ast.Pass)


def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _sha(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------------------
# 1. policy gate
# ------------------------------------------------------------------------------
def check_policy(code: str, kind: str = "skill") -> List[str]:
    """Static checks. Returns human-readable problems (empty list = passes).
    kind='skill' also requires a top-level execute(); kind='tests' requires test_* functions."""
    problems: List[str] = []
    limit = MAX_CODE_CHARS if kind == "skill" else MAX_TESTS_CHARS
    if not isinstance(code, str) or not code.strip():
        return [f"{kind} code is empty"]
    if len(code) > limit:
        return [f"{kind} code is {len(code)} characters; the limit is {limit}"]
    if "\x00" in code:
        return [f"{kind} code contains a NUL byte"]
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"{kind} code has a syntax error: {e.msg} (line {e.lineno})"]

    for node in tree.body:
        is_docstring = isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Constant) \
            and isinstance(node.value.value, str)
        if not (isinstance(node, _TOP_LEVEL_OK) or is_docstring):
            problems.append(f"line {node.lineno}: top-level {type(node).__name__} - modules may only define "
                            "imports, functions, classes and constants (no work at import time)")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in ALLOWED_IMPORTS:
                    problems.append(f"line {node.lineno}: import of '{alias.name}' is not allowed")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if node.level:
                problems.append(f"line {node.lineno}: relative imports are not allowed")
            elif root in _ALLOWED_FROM:
                bad = [a.name for a in node.names if a.name not in _ALLOWED_FROM[root]]
                if bad:
                    problems.append(f"line {node.lineno}: from {root} import {', '.join(bad)} is not allowed")
            elif root not in ALLOWED_IMPORTS:
                problems.append(f"line {node.lineno}: import from '{node.module}' is not allowed")
            elif any(a.name == "*" for a in node.names):
                problems.append(f"line {node.lineno}: 'import *' is not allowed")
        elif isinstance(node, ast.Name):
            if node.id in BANNED_NAMES:
                problems.append(f"line {node.lineno}: use of '{node.id}' is not allowed")
        elif isinstance(node, ast.Attribute):
            if node.attr in BANNED_ATTRS:
                problems.append(f"line {node.lineno}: access to '.{node.attr}' is not allowed")
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            problems.append(f"line {node.lineno}: global/nonlocal is not allowed")
        elif isinstance(node, (ast.AsyncFunctionDef, ast.Await, ast.AsyncFor, ast.AsyncWith)):
            problems.append(f"line {node.lineno}: async code is not allowed")

    if kind == "skill":
        execs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "execute"]
        if not execs:
            problems.append("the skill must define a top-level function execute(**kwargs)")
        elif execs[0].args.posonlyargs or (execs[0].args.args and not execs[0].args.kwarg and
                                           any(a.arg == "self" for a in execs[0].args.args)):
            problems.append("execute must be a plain function that takes keyword arguments")
    else:
        tests = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
        if not tests:
            problems.append("the tests must define at least one top-level function named test_*")
        elif len(tests) > MAX_TESTS:
            problems.append(f"at most {MAX_TESTS} tests are allowed")
    return sorted(set(problems), key=lambda s: (int(re.match(r"line (\d+)", s).group(1)) if s.startswith("line ") else 0, s))


# ------------------------------------------------------------------------------
# 2. isolated runner
# ------------------------------------------------------------------------------
_RUNNER = r'''
import contextlib, importlib.util, io, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
MODE, NONCE = sys.argv[1], sys.argv[2]


def emit(obj):
    sys.__stdout__.write("\n" + NONCE + json.dumps(obj, default=str) + "\n")
    sys.__stdout__.flush()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


captured = io.StringIO()
try:
    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        skill = load(os.path.join(HERE, "skill_under_test.py"), "skill_under_test")
        if MODE == "test":
            ns = {"skill": skill, "__name__": "tests_under_test"}
            with open(os.path.join(HERE, "tests_under_test.py"), encoding="utf-8") as f:
                exec(compile(f.read(), "tests_under_test.py", "exec"), ns)
            results = []
            for name in sorted(k for k, v in ns.items() if k.startswith("test_") and callable(v)):
                try:
                    ns[name]()
                    results.append({"name": name, "passed": True})
                except AssertionError as e:
                    results.append({"name": name, "passed": False, "error": "AssertionError: " + str(e)[:300]})
                except Exception as e:
                    results.append({"name": name, "passed": False, "error": type(e).__name__ + ": " + str(e)[:300]})
            payload = {"ok": True, "results": results}
        else:
            with open(os.path.join(HERE, "args.json"), encoding="utf-8") as f:
                args = json.load(f)
            payload = {"ok": True, "result": skill.execute(**args)}
except BaseException as e:
    payload = {"ok": False, "error": type(e).__name__ + ": " + str(e)[:500]}
payload["output"] = captured.getvalue()[:2000]
emit(payload)
'''


def _docker_command(job_dir: str, name: str, mode: str, nonce: str) -> List[str]:
    """The exact docker invocation (a pure function so it can be unit-tested without Docker)."""
    return [
        "docker", "run", "--rm", "--name", name,
        "--network", "none", "--memory", "256m", "--cpus", "1", "--pids-limit", "64",
        "--read-only", "--tmpfs", "/tmp:rw,size=64m",
        "-v", f"{job_dir}:/sandbox:ro", "-w", "/sandbox",
        "python:3.11-slim", "python", "-I", "/sandbox/_runner.py", mode, nonce,
    ]


def _hardened_limits() -> None:  # runs in the child, POSIX only
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
        resource.setrlimit(resource.RLIMIT_AS, (2048 * 1024 * 1024, 2048 * 1024 * 1024))  # numpy/BLAS reserve a lot of address space
        resource.setrlimit(resource.RLIMIT_FSIZE, (10 * 1024 * 1024, 10 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    except Exception:
        pass


def _read_capped(path: str) -> str:
    try:
        with open(path, "rb") as f:
            return f.read(MAX_OUTPUT_BYTES).decode("utf-8", errors="replace")
    except OSError:
        return ""


_docker_probe: Dict[str, Any] = {"at": 0.0, "usable": False}


def docker_usable(max_age: float = 60.0) -> bool:
    """True only if the Docker DAEMON answers - having the `docker` command installed is not
    enough (it is common to have the CLI without a running engine). Cached briefly."""
    import time
    now = time.monotonic()
    if now - _docker_probe["at"] < max_age and _docker_probe["at"]:
        return bool(_docker_probe["usable"])
    usable = False
    if shutil.which("docker"):
        try:
            usable = subprocess.run(["docker", "info"], capture_output=True, timeout=8,
                                    stdin=subprocess.DEVNULL).returncode == 0
        except (OSError, subprocess.SubprocessError):
            usable = False
    _docker_probe.update(at=now, usable=usable)
    return usable


def resolve_sandbox_mode(preferred: Optional[str] = None) -> str:
    mode = (preferred or os.getenv("PROMETHEUS_SKILL_SANDBOX", "auto")).strip().lower()
    if mode == "docker":
        return "docker"      # explicit: honoured even if it later fails, so the failure is visible
    if mode == "subprocess":
        return "subprocess"
    return "docker" if docker_usable() else "subprocess"


def run_isolated(skill_code: str, mode: str, tests_code: str = "", args: Optional[Dict[str, Any]] = None,
                 timeout: int = RUN_TIMEOUT_SECONDS, sandbox: Optional[str] = None) -> Dict[str, Any]:
    """Run a skill (mode='run') or its tests (mode='test') in an isolated process.
    Returns {"ok": bool, ...}; infrastructure problems and timeouts are returned as
    {"ok": False, "error": ..., "timed_out": bool}, never raised."""
    sandbox = resolve_sandbox_mode(sandbox)
    nonce = "@@" + secrets.token_hex(12) + "@@"
    job_dir = tempfile.mkdtemp(prefix="skill_job_")
    scratch = tempfile.mkdtemp(prefix="skill_scratch_")
    try:
        for fname, content in (("_runner.py", _RUNNER), ("skill_under_test.py", skill_code),
                               ("tests_under_test.py", tests_code), ("args.json", json.dumps(args or {}))):
            with open(os.path.join(job_dir, fname), "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
        out_path, err_path = os.path.join(scratch, "out.txt"), os.path.join(scratch, "err.txt")
        timed_out = False
        container = f"prom-skill-{uuid.uuid4().hex[:12]}"
        if sandbox == "docker":
            argv = _docker_command(job_dir, container, mode, nonce)
            kwargs: Dict[str, Any] = {}
        else:
            env = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
            for keep in ("SYSTEMROOT", "TEMP", "TMP", "LD_LIBRARY_PATH"):  # Windows needs SYSTEMROOT to start Python
                if keep in os.environ:
                    env[keep] = os.environ[keep]
            argv = [sys.executable, "-I", os.path.join(job_dir, "_runner.py"), mode, nonce]
            kwargs = {"cwd": scratch, "env": env}
            if os.name != "nt":
                kwargs.update(preexec_fn=_hardened_limits, start_new_session=True)
        try:
            with open(out_path, "wb") as fo, open(err_path, "wb") as fe:
                proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=fo, stderr=fe, **kwargs)
                try:
                    proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    if sandbox == "docker":
                        subprocess.run(["docker", "rm", "-f", container], capture_output=True, timeout=15)
                    proc.kill()
                    proc.wait()
        except OSError as e:
            return {"ok": False, "error": f"could not start the sandbox ({sandbox}): {e}", "timed_out": False}
        if timed_out:
            return {"ok": False, "error": f"timed out after {timeout}s", "timed_out": True}
        stdout, stderr = _read_capped(out_path), _read_capped(err_path)
        for line in reversed(stdout.splitlines()):
            if line.startswith(nonce):
                try:
                    payload = json.loads(line[len(nonce):])
                except ValueError:
                    break
                payload["timed_out"] = False
                return payload
        tail = (stderr.strip().splitlines() or [""])[-1][:300]
        return {"ok": False, "timed_out": False,
                "error": f"the sandboxed process produced no result (exit code {proc.returncode}). {tail}".strip()}
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)
        shutil.rmtree(scratch, ignore_errors=True)


# ------------------------------------------------------------------------------
# 3. registry
# ------------------------------------------------------------------------------
class SkillRegistry:
    """Installed skills, their versions and their status, persisted atomically."""

    def __init__(self, skills_dir: str, registry_path: str, reserved_names=(), sandbox: Optional[str] = None):
        self.skills_dir = skills_dir
        self.registry_path = registry_path
        self.reserved = {n.lower() for n in reserved_names}
        self.sandbox = resolve_sandbox_mode(sandbox)
        self._lock = threading.RLock()
        self._unsafe_to_save = False
        self.skills: Dict[str, Dict[str, Any]] = {}
        os.makedirs(self.skills_dir, exist_ok=True)
        self._load()

    # -- persistence -------------------------------------------------------------
    def _load(self) -> None:
        if not os.path.exists(self.registry_path):
            return
        try:
            data = read_json_state(self.registry_path)
        except json.JSONDecodeError as e:
            logger.error(f"Skill registry corrupt (moved aside), starting empty: {e}")
            return
        except OSError as e:
            logger.error(f"Skill registry unreadable; will NOT overwrite it: {e}")
            self._unsafe_to_save = True
            return
        if isinstance(data, dict) and isinstance(data.get("skills"), dict):
            for name, e in data["skills"].items():
                if SKILL_NAME_RE.match(name) and isinstance(e, dict) and "code_sha" in e:
                    e.setdefault("history", [])
                    e.setdefault("status", "active")
                    e.setdefault("version", 1)
                    e.setdefault("next_version", e["version"] + 1)
                    self.skills[name] = e

    def _save(self) -> bool:
        if self._unsafe_to_save:
            logger.error("Refusing to save the skill registry: the existing file could not be read.")
            return False
        return atomic_write_json(self.registry_path, {"schema_version": 1, "skills": self.skills}, indent=1, prefix="skills_")

    # -- paths ---------------------------------------------------------------------
    def _active_path(self, name: str) -> str:
        return os.path.join(self.skills_dir, f"{name}.py")

    def _version_paths(self, name: str, version: int) -> Tuple[str, str]:
        base = os.path.join(self.skills_dir, "_versions", name)
        return os.path.join(base, f"v{version}.py"), os.path.join(base, f"v{version}_tests.py")

    # -- queries ---------------------------------------------------------------------
    @property
    def strongly_sandboxed(self) -> bool:
        return self.sandbox == "docker"

    def has(self, name: str) -> bool:
        with self._lock:
            return name in self.skills

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            e = self.skills.get(name)
            return json.loads(json.dumps(e)) if e else None

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [{"name": n, "description": e.get("description", ""), "version": e["version"],
                     "status": e["status"], "tests": e.get("tests", ""), "updated": e.get("updated", "")}
                    for n, e in sorted(self.skills.items())]

    def snapshot(self) -> List[Dict[str, Any]]:
        """For the Obsidian exporter: list() plus each skill's version history."""
        with self._lock:
            out = []
            for item in self.list():
                item["history"] = [{"version": h["version"], "status": h["status"], "created": h["created"]}
                                   for h in self.skills[item["name"]]["history"]]
                out.append(item)
            return out

    def catalog_text(self, limit: int = 20) -> str:
        """One line per usable skill, for the prompt - so the model knows what it can call."""
        with self._lock:
            lines = [f"  - {n}: {e.get('description', '')[:120]} (v{e['version']})"
                     for n, e in sorted(self.skills.items()) if e["status"] == "active"][:limit]
            return "\n".join(lines)

    # -- proposing a new skill / version ------------------------------------------------
    def check_name(self, name: str) -> Optional[str]:
        if not isinstance(name, str) or not SKILL_NAME_RE.match(name):
            return "skill names must be lowercase letters, digits and underscores, start with a letter, 3-40 characters"
        if name.lower() in self.reserved:
            return f"'{name}' is the name of a built-in tool"
        return None

    def propose(self, name: str, description: str, code: str, tests_code: str) -> Dict[str, Any]:
        """The only way a skill gets installed. Returns {"status": "installed"|"rejected", ...};
        a rejection lists every reason and leaves the registry and disk untouched."""
        with self._lock:
            problems: List[str] = []
            if self._unsafe_to_save:
                return {"status": "rejected", "stage": "registry",
                        "problems": ["the skill registry file exists but could not be read; nothing was installed"]}
            bad_name = self.check_name(name)
            if bad_name:
                return {"status": "rejected", "stage": "name", "problems": [bad_name]}
            description = re.sub(r"\s+", " ", str(description or "")).strip()[:300]
            if not description:
                problems.append("a one-line description is required")
            problems += [f"skill: {p}" for p in check_policy(code, "skill")]
            problems += [f"tests: {p}" for p in check_policy(tests_code, "tests")]
            if problems:
                return {"status": "rejected", "stage": "policy", "problems": problems}

            report = run_isolated(code, "test", tests_code=tests_code, timeout=TEST_TIMEOUT_SECONDS, sandbox=self.sandbox)
            if not report.get("ok"):
                reason = "tests timed out" if report.get("timed_out") else "the skill failed to load or crashed"
                return {"status": "rejected", "stage": "tests", "problems": [f"{reason}: {report.get('error', '')}"],
                        "output": report.get("output", "")}
            results = report.get("results", [])
            failed = [r for r in results if not r["passed"]]
            if not results:
                return {"status": "rejected", "stage": "tests", "problems": ["no tests were run"]}
            if failed:
                return {"status": "rejected", "stage": "tests",
                        "problems": [f"{r['name']}: {r.get('error', 'failed')}" for r in failed],
                        "tests": f"{len(results) - len(failed)}/{len(results)} passing"}

            entry = self.skills.get(name)
            version = entry["next_version"] if entry else 1
            vcode, vtests = self._version_paths(name, version)
            os.makedirs(os.path.dirname(vcode), exist_ok=True)
            ok = (atomic_write_text(vcode, code, prefix="skill_") and atomic_write_text(vtests, tests_code, prefix="skill_")
                  and atomic_write_text(self._active_path(name), code, prefix="skill_"))
            if not ok:
                return {"status": "rejected", "stage": "install", "problems": ["could not write the skill files"]}
            now = _now_iso()
            summary = f"{len(results)}/{len(results)} passing"
            if entry:
                for h in entry["history"]:
                    if h["status"] == "active":
                        h["status"] = "superseded"
            else:
                entry = {"created": now, "history": []}
            entry.update({"description": description, "version": version, "next_version": version + 1,
                          "status": "active", "code_sha": _sha(code), "tests": summary, "updated": now})
            entry["history"].append({"version": version, "status": "active", "created": now,
                                     "code_sha": _sha(code), "tests_sha": _sha(tests_code)})
            self.skills[name] = entry
            if not self._save():
                return {"status": "rejected", "stage": "install", "problems": ["could not save the skill registry"]}
            return {"status": "installed", "name": name, "version": version, "tests": summary,
                    "sandbox": self.sandbox}

    # -- rollback / enable / disable ---------------------------------------------------------
    def rollback(self, name: str) -> Dict[str, Any]:
        with self._lock:
            entry = self.skills.get(name)
            if not entry:
                return {"status": "error", "message": f"no skill named '{name}'"}
            previous = [h for h in entry["history"] if h["status"] == "superseded"]
            if not previous:
                return {"status": "error", "message": "there is no earlier version to roll back to"}
            target = max(previous, key=lambda h: h["version"])
            vcode, vtests = self._version_paths(name, target["version"])
            try:
                with open(vcode, encoding="utf-8") as f:
                    code = f.read()
                with open(vtests, encoding="utf-8") as f:
                    tests_code = f.read()
            except OSError as e:
                return {"status": "error", "message": f"version {target['version']} is missing on disk: {e}"}
            if _sha(code) != target["code_sha"]:
                return {"status": "error", "message": f"version {target['version']} was modified on disk; refusing to restore it"}
            report = run_isolated(code, "test", tests_code=tests_code, timeout=TEST_TIMEOUT_SECONDS, sandbox=self.sandbox)
            results = report.get("results", []) if report.get("ok") else []
            if not results or any(not r["passed"] for r in results):
                return {"status": "error", "message": f"version {target['version']} no longer passes its own tests; "
                                                      "not restored (disable the skill instead)"}
            if not atomic_write_text(self._active_path(name), code, prefix="skill_"):
                return {"status": "error", "message": "could not write the restored skill"}
            for h in entry["history"]:
                if h["status"] == "active":
                    h["status"] = "rolled_back"
            target["status"] = "active"
            entry.update({"version": target["version"], "code_sha": target["code_sha"], "status": "active",
                          "tests": f"{len(results)}/{len(results)} passing", "updated": _now_iso()})
            self._save()
            return {"status": "success", "name": name, "version": target["version"]}

    def set_enabled(self, name: str, enabled: bool) -> Dict[str, Any]:
        with self._lock:
            entry = self.skills.get(name)
            if not entry:
                return {"status": "error", "message": f"no skill named '{name}'"}
            entry["status"] = "active" if enabled else "disabled"
            entry["updated"] = _now_iso()
            self._save()
            return {"status": "success", "name": name, "skill_status": entry["status"]}

    # -- using a skill -------------------------------------------------------------------------
    def run(self, name: str, args: Optional[Dict[str, Any]] = None, timeout: int = RUN_TIMEOUT_SECONDS) -> Dict[str, Any]:
        with self._lock:
            entry = self.skills.get(name)
            if not entry:
                return {"status": "error", "message": f"no registered skill named '{name}'"}
            if entry["status"] != "active":
                return {"status": "error", "message": f"skill '{name}' is {entry['status']}"}
            try:
                with open(self._active_path(name), encoding="utf-8") as f:
                    code = f.read()
            except OSError as e:
                return {"status": "error", "message": f"skill file unreadable: {e}"}
            if _sha(code) != entry["code_sha"]:
                entry["status"] = "tampered"
                self._save()
                return {"status": "error", "message": f"skill '{name}' was modified outside the registry; it is disabled "
                                                      "until it is re-proposed through the gate"}
        args = {} if args is None else args
        if not isinstance(args, dict):
            return {"status": "error", "message": "arguments must be a JSON object"}
        try:
            json.dumps(args)
        except (TypeError, ValueError):
            return {"status": "error", "message": "arguments must be JSON-serialisable"}
        res = run_isolated(code, "run", args=args, timeout=timeout, sandbox=self.sandbox)
        if not res.get("ok"):
            return {"status": "error", "message": res.get("error", "skill failed"), "timed_out": bool(res.get("timed_out")),
                    "output": res.get("output", "")}
        rendered = json.dumps(res.get("result"), default=str)
        if len(rendered) > MAX_RESULT_CHARS:
            return {"status": "error", "message": f"the skill's result is too large ({len(rendered)} characters)"}
        return {"status": "success", "skill": name, "version": entry["version"], "result": json.loads(rendered),
                "output": res.get("output", ""), "sandbox": self.sandbox}
