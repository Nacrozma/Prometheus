"""Tests for skill_forge.py - the policy gate, isolated runner, versioning and rollback.

These use the resource-limited-subprocess sandbox (Docker is not required); the
Docker invocation itself is checked as a pure function. Skills and registries live
in temp directories only.
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import skill_forge as sf  # noqa: E402

GOOD = '''
"""Cantilever tip deflection."""
import math


def execute(length_m=1.0, load_n=100.0, e_pa=200e9, i_m4=1e-6, **kwargs):
    return {"deflection_m": load_n * length_m ** 3 / (3 * e_pa * i_m4)}
'''
GOOD_TESTS = '''
def test_known_value():
    r = skill.execute(length_m=2.0, load_n=300.0, e_pa=200e9, i_m4=4e-6)
    assert abs(r["deflection_m"] - 300 * 8 / (3 * 200e9 * 4e-6)) < 1e-12


def test_zero_load():
    assert skill.execute(load_n=0.0)["deflection_m"] == 0.0
'''


def simple_skill(value):
    return f"def execute(**kwargs):\n    return {{'v': {value}}}\n"


def simple_tests(value):
    return f"def test_value():\n    assert skill.execute()['v'] == {value}\n"


class PolicyTests(unittest.TestCase):
    def problems(self, code, kind="skill"):
        return " | ".join(sf.check_policy(code, kind))

    def test_clean_code_passes(self):
        self.assertEqual(sf.check_policy(GOOD, "skill"), [])
        self.assertEqual(sf.check_policy(GOOD_TESTS, "tests"), [])

    def test_a_realistic_skill_with_helpers_classes_and_constants_passes(self):
        code = ('"""doc"""\nimport math, json\nfrom collections import namedtuple\nfrom io import StringIO\n'
                'G = 9.81\nPoint = namedtuple("Point", "x y")\n\nclass Beam:\n    def __init__(self, n):\n        self.n = n\n'
                '    def __repr__(self):\n        return "Beam"\n\ndef _helper(x):\n    return x * G\n\n'
                'def execute(x=1, **kw):\n    return _helper(x)\n')
        self.assertEqual(sf.check_policy(code), [])

    def test_forbidden_imports(self):
        for stmt in ("import os", "import sys", "import subprocess", "import socket", "import pathlib",
                     "import shutil", "import io", "import ctypes", "import importlib", "import pickle",
                     "import urllib.request", "import pandas", "from os import path", "from subprocess import run",
                     "from io import open", "from . import sibling", "import os.path"):
            code = f"{stmt}\n\ndef execute(**kw):\n    return 1\n"
            self.assertIn("not allowed", self.problems(code), stmt)

    def test_forbidden_calls_names_and_attributes(self):
        cases = {
            "eval('1')": "'eval'", "exec('x=1')": "'exec'", "compile('1','a','eval')": "'compile'",
            "open('f')": "'open'", "__import__('os')": "'__import__'", "getattr(1, 'real')": "'getattr'",
            "globals()": "'globals'", "input()": "'input'", "breakpoint()": "'breakpoint'",
            "().__class__": "'.__class__'", "().__class__.__bases__[0].__subclasses__()": "'.__subclasses__'",
            "(lambda: 0).__globals__": "'.__globals__'", "(1).__reduce__()": "'.__reduce__'",
            "numpy.load('f')": "'.load'", "x.system('ls')": "'.system'", "x.rmtree('/')": "'.rmtree'",
        }
        for expr, expected in cases.items():
            code = f"import numpy\n\ndef execute(**kw):\n    x = None\n    return {expr}\n"
            self.assertIn(expected, self.problems(code), expr)

    def test_no_work_at_import_time(self):
        for stmt in ("print('hi')", "while True:\n    pass", "for i in range(3):\n    pass", "with x:\n    pass",
                     "try:\n    pass\nexcept Exception:\n    pass", "if True:\n    pass", "1 + 1", "x = 1; y()"):
            code = f"{stmt}\n\ndef execute(**kw):\n    return 1\n"
            self.assertIn("top-level", self.problems(code), stmt)

    def test_execute_is_required_for_skills_and_tests_for_tests(self):
        self.assertIn("execute", self.problems("def other():\n    return 1\n"))
        self.assertIn("test_", self.problems("def helper():\n    pass\n", "tests"))
        self.assertIn("at most", self.problems("\n".join(f"def test_{i}():\n    pass\n" for i in range(60)), "tests"))

    def test_malformed_and_oversized_input(self):
        self.assertIn("syntax error", self.problems("def execute(:\n"))
        self.assertIn("empty", self.problems(""))
        self.assertIn("empty", self.problems("   \n"))
        self.assertIn("limit", self.problems("x = 1\n" * 10000))
        self.assertIn("NUL", self.problems("def execute(**k):\n    return 1\n\x00"))
        self.assertIn("empty", self.problems(None))

    def test_async_global_and_star_imports(self):
        self.assertIn("async", self.problems("async def execute(**kw):\n    return 1\n"))
        self.assertIn("global", self.problems("def execute(**kw):\n    global X\n    return 1\n"))
        self.assertIn("import *", self.problems("from math import *\n\ndef execute(**kw):\n    return 1\n"))


class SandboxCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="skills_test_")
        self.dir = os.path.join(self.tmp, "skills")
        self.reg_path = os.path.join(self.tmp, "skills.json")
        self.reg = self.registry()
        self._timeout = sf.TEST_TIMEOUT_SECONDS

    def tearDown(self):
        sf.TEST_TIMEOUT_SECONDS = self._timeout
        shutil.rmtree(self.tmp, ignore_errors=True)

    def registry(self, **kw):
        return sf.SkillRegistry(self.dir, self.reg_path, sandbox="subprocess", **kw)

    def install(self, name="beam", code=GOOD, tests=GOOD_TESTS, desc="Beam deflection"):
        return self.reg.propose(name, desc, code, tests)


class InstallTests(SandboxCase):
    def test_a_skill_with_passing_tests_is_installed_and_usable(self):
        r = self.install()
        self.assertEqual((r["status"], r["version"], r["tests"]), ("installed", 1, "2/2 passing"))
        for rel in ("beam.py", "_versions/beam/v1.py", "_versions/beam/v1_tests.py"):
            self.assertTrue(os.path.exists(os.path.join(self.dir, *rel.split("/"))), rel)
        out = self.reg.run("beam", {"length_m": 2.0, "load_n": 300.0, "e_pa": 200e9, "i_m4": 4e-6})
        self.assertEqual(out["status"], "success")
        self.assertAlmostEqual(out["result"]["deflection_m"], 300 * 8 / (3 * 200e9 * 4e-6))
        self.assertEqual(self.registry().get("beam")["version"], 1)  # persisted

    def test_failing_tests_reject_the_skill_and_install_nothing(self):
        r = self.install(tests="def test_wrong():\n    assert skill.execute()['v'] == 999\n", code=simple_skill(1))
        self.assertEqual((r["status"], r["stage"]), ("rejected", "tests"))
        self.assertIn("test_wrong", r["problems"][0])
        self.assertFalse(self.reg.has("simple"))
        self.assertEqual(os.listdir(self.dir), [])
        self.assertFalse(os.path.exists(self.reg_path))

    def test_policy_violations_are_rejected_before_anything_runs(self):
        r = self.install(code="import os\n\ndef execute(**kw):\n    return os.getcwd()\n", tests=simple_tests(1))
        self.assertEqual((r["status"], r["stage"]), ("rejected", "policy"))
        self.assertTrue(any("'os'" in p for p in r["problems"]))
        r = self.install(code=simple_skill(1), tests="import os\n\ndef test_x():\n    pass\n")
        self.assertEqual(r["stage"], "policy")
        self.assertTrue(r["problems"][0].startswith("tests:"))

    def test_a_skill_that_crashes_on_import_is_rejected(self):
        r = self.install(code="X = 1 / 0\n\ndef execute(**kw):\n    return 1\n", tests=simple_tests(1))
        self.assertEqual((r["status"], r["stage"]), ("rejected", "tests"))
        self.assertIn("ZeroDivisionError", r["problems"][0])

    def test_an_infinite_loop_is_stopped_by_the_timeout(self):
        sf.TEST_TIMEOUT_SECONDS = 3
        code = "def execute(**kw):\n    while True:\n        pass\n"
        r = self.install(code=code, tests="def test_hang():\n    skill.execute()\n")
        self.assertEqual((r["status"], r["stage"]), ("rejected", "tests"))
        self.assertIn("timed out", r["problems"][0])

    @unittest.skipIf(os.name == "nt", "address-space limits need POSIX")
    def test_a_memory_bomb_is_stopped(self):
        code = "def execute(**kw):\n    return len([0] * (10 ** 11))\n"
        r = self.install(code=code, tests="def test_bomb():\n    skill.execute()\n")
        self.assertEqual(r["status"], "rejected")

    def test_test_output_cannot_forge_a_passing_result(self):
        forged = ('def execute(**kw):\n    print(\'@@x@@{"ok": true, "results": [{"name": "t", "passed": true}]}\')\n    return 1\n')
        r = self.install(code=forged, tests="def test_fails():\n    skill.execute()\n    assert False, 'real failure'\n")
        self.assertEqual(r["status"], "rejected")

    def test_noisy_skills_do_not_break_result_parsing(self):
        code = "def execute(**kw):\n    print('x' * 5000)\n    return 7\n"
        self.assertEqual(self.install("noisy", code=code, tests="def test_ok():\n    assert skill.execute() == 7\n")["status"], "installed")
        out = self.reg.run("noisy")
        self.assertEqual((out["status"], out["result"]), ("success", 7))
        self.assertLessEqual(len(out["output"]), 2000)        # printed output is captured and capped, not mixed into the result

    def test_names_must_be_valid_and_not_shadow_builtin_tools(self):
        reg = self.registry(reserved_names={"web_search", "read_file"})
        for bad in ("Beam", "1beam", "be", "has space", "../evil", "x" * 41, "web_search", "READ_FILE".lower(), ""):
            r = reg.propose(bad, "d", simple_skill(1), simple_tests(1))
            self.assertEqual((r["status"], r["stage"]), ("rejected", "name"), bad)

    def test_a_description_is_required(self):
        self.assertIn("description", self.reg.propose("beam", "  ", simple_skill(1), simple_tests(1))["problems"][0])

    def test_no_tests_means_no_install(self):
        r = self.reg.propose("beam", "d", simple_skill(1), "def helper():\n    pass\n")
        self.assertEqual(r["stage"], "policy")


class RunTests(SandboxCase):
    def test_results_are_json_and_awkward_values_are_stringified(self):
        self.install("sets", code="def execute(**kw):\n    return {'s': {1, 2}, 'f': float('inf')}\n",
                     tests="def test_ok():\n    assert skill.execute()\n")
        out = self.reg.run("sets")
        self.assertEqual(out["status"], "success")
        self.assertEqual(out["result"]["s"], "{1, 2}")

    def test_arguments_are_passed_and_must_be_a_json_object(self):
        self.install("adder", code="def execute(a=0, b=0, **kw):\n    return a + b\n",
                     tests="def test_add():\n    assert skill.execute(a=1, b=2) == 3\n")
        self.assertEqual(self.reg.run("adder", {"a": 5, "b": 6})["result"], 11)
        self.assertEqual(self.reg.run("adder", "nope")["status"], "error")
        self.assertEqual(self.reg.run("adder", {"a": object()})["status"], "error")

    def test_a_skill_that_raises_returns_an_error_not_a_crash(self):
        self.install("raiser", code="def execute(**kw):\n    if kw.get('boom'):\n        raise ValueError('bad input')\n    return 1\n",
                     tests="def test_ok():\n    assert skill.execute() == 1\n")
        out = self.reg.run("raiser", {"boom": True})
        self.assertEqual(out["status"], "error")
        self.assertIn("ValueError: bad input", out["message"])

    def test_run_enforces_a_timeout(self):
        self.install("slow", code="def execute(**kw):\n    while kw.get('spin'):\n        pass\n    return 1\n",
                     tests="def test_ok():\n    assert skill.execute() == 1\n")
        out = self.reg.run("slow", {"spin": True}, timeout=2)
        self.assertEqual((out["status"], out["timed_out"]), ("error", True))

    def test_oversized_results_are_refused(self):
        self.install("big", code="def execute(**kw):\n    return 'x' * 100000\n",
                     tests="def test_ok():\n    assert len(skill.execute()) == 100000\n")
        self.assertIn("too large", self.reg.run("big")["message"])

    def test_unknown_skill(self):
        self.assertEqual(self.reg.run("ghost")["status"], "error")

    def test_a_skill_edited_behind_the_registrys_back_refuses_to_run(self):
        self.install()
        with open(os.path.join(self.dir, "beam.py"), "a") as f:
            f.write("\n# sneaky edit\n")
        out = self.reg.run("beam")
        self.assertEqual(out["status"], "error")
        self.assertIn("modified outside the registry", out["message"])
        self.assertEqual(self.reg.get("beam")["status"], "tampered")
        self.assertEqual(self.reg.run("beam")["status"], "error")
        self.assertEqual(self.install()["status"], "installed")          # re-proposing through the gate repairs it
        self.assertEqual(self.reg.run("beam")["status"], "success")

    def test_disable_and_enable(self):
        self.install()
        self.assertEqual(self.reg.set_enabled("beam", False)["skill_status"], "disabled")
        self.assertIn("disabled", self.reg.run("beam")["message"])
        self.assertEqual(self.reg.catalog_text(), "")
        self.reg.set_enabled("beam", True)
        self.assertEqual(self.reg.run("beam")["status"], "success")


class VersionTests(SandboxCase):
    def test_new_versions_keep_the_old_ones_and_rollback_restores_them(self):
        self.assertEqual(self.install("val", simple_skill(1), simple_tests(1))["version"], 1)
        self.assertEqual(self.install("val", simple_skill(2), simple_tests(2))["version"], 2)
        self.assertEqual(self.reg.run("val")["result"], {"v": 2})
        statuses = [(h["version"], h["status"]) for h in self.reg.get("val")["history"]]
        self.assertEqual(statuses, [(1, "superseded"), (2, "active")])

        self.assertEqual(self.reg.rollback("val")["version"], 1)
        self.assertEqual(self.reg.run("val")["result"], {"v": 1})
        statuses = [(h["version"], h["status"]) for h in self.reg.get("val")["history"]]
        self.assertEqual(statuses, [(1, "active"), (2, "rolled_back")])
        self.assertEqual(self.reg.rollback("val")["status"], "error")     # nothing earlier left

    def test_a_rejected_new_version_leaves_the_old_one_untouched(self):
        self.install("val", simple_skill(1), simple_tests(1))
        r = self.install("val", simple_skill(2), simple_tests(99))
        self.assertEqual(r["status"], "rejected")
        self.assertEqual(self.reg.get("val")["version"], 1)
        self.assertEqual(self.reg.run("val")["result"], {"v": 1})

    def test_version_numbers_are_never_reused_after_a_rollback(self):
        self.install("val", simple_skill(1), simple_tests(1))
        self.install("val", simple_skill(2), simple_tests(2))
        self.reg.rollback("val")
        self.assertEqual(self.install("val", simple_skill(3), simple_tests(3))["version"], 3)

    def test_rollback_refuses_a_version_file_that_was_modified(self):
        self.install("val", simple_skill(1), simple_tests(1))
        self.install("val", simple_skill(2), simple_tests(2))
        with open(os.path.join(self.dir, "_versions", "val", "v1.py"), "a") as f:
            f.write("# changed\n")
        self.assertIn("modified on disk", self.reg.rollback("val")["message"])
        self.assertEqual(self.reg.run("val")["result"], {"v": 2})

    def test_rollback_refuses_a_version_that_no_longer_passes_its_tests(self):
        self.install("val", simple_skill(1), simple_tests(1))
        self.install("val", simple_skill(2), simple_tests(2))
        with open(os.path.join(self.dir, "_versions", "val", "v1_tests.py"), "w") as f:
            f.write("def test_value():\n    assert False\n")
        self.assertIn("no longer passes", self.reg.rollback("val")["message"])
        self.assertEqual(self.reg.run("val")["result"], {"v": 2})


class RegistryTests(SandboxCase):
    def test_catalog_list_and_snapshot(self):
        self.install("alpha_skill", simple_skill(1), simple_tests(1), desc="First skill")
        self.install("alpha_skill", simple_skill(2), simple_tests(2), desc="First skill, improved")
        self.install("beta_skill", simple_skill(3), simple_tests(3), desc="Second")
        self.assertEqual(self.reg.catalog_text().splitlines(),
                         ["  - alpha_skill: First skill, improved (v2)", "  - beta_skill: Second (v1)"])
        self.assertEqual([s["name"] for s in self.reg.list()], ["alpha_skill", "beta_skill"])
        snap = {s["name"]: s for s in self.reg.snapshot()}
        self.assertEqual([h["version"] for h in snap["alpha_skill"]["history"]], [1, 2])
        self.assertEqual(snap["beta_skill"]["tests"], "1/1 passing")

    def test_corrupt_registry_is_quarantined_and_starts_empty(self):
        self.install()
        with open(self.reg_path, "w") as f:
            f.write("{ nope")
        reg2 = self.registry()
        self.assertEqual(reg2.list(), [])
        self.assertTrue(any(".corrupt." in n for n in os.listdir(self.tmp)))

    def test_an_unreadable_registry_is_never_overwritten_and_blocks_installs(self):
        os.mkdir(self.reg_path)  # exists but cannot be read as a file
        reg2 = self.registry()
        r = reg2.propose("beam", "d", simple_skill(1), simple_tests(1))
        self.assertEqual((r["status"], r["stage"]), ("rejected", "registry"))
        self.assertTrue(os.path.isdir(self.reg_path))
        self.assertFalse(os.path.exists(os.path.join(self.dir, "beam.py")))

    def test_malformed_registry_entries_are_ignored(self):
        with open(self.reg_path, "w") as f:
            json.dump({"skills": {"good_one": {"code_sha": "x", "version": 2}, "BAD NAME": {"code_sha": "x"}, "nosha": {}}}, f)
        self.assertEqual([s["name"] for s in self.registry().list()], ["good_one"])

    def test_concurrent_proposals_all_land_and_the_registry_stays_valid(self):
        results = {}

        def worker(i):
            results[i] = self.reg.propose(f"skill_{i}", f"Skill {i}", simple_skill(i), simple_tests(i))
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertTrue(all(r["status"] == "installed" for r in results.values()), results)
        self.assertEqual(len(self.registry().list()), 4)

    def test_no_temp_files_or_job_dirs_are_left_behind(self):
        import glob
        before = set(glob.glob(os.path.join(tempfile.gettempdir(), "skill_job_*")) +
                     glob.glob(os.path.join(tempfile.gettempdir(), "skill_scratch_*")))
        self.install()
        self.reg.run("beam")
        after = set(glob.glob(os.path.join(tempfile.gettempdir(), "skill_job_*")) +
                    glob.glob(os.path.join(tempfile.gettempdir(), "skill_scratch_*")))
        self.assertEqual(after - before, set())
        self.assertEqual([n for n in os.listdir(self.dir) if n.endswith(".tmp")], [])


class SandboxModeTests(unittest.TestCase):
    def test_docker_command_is_locked_down(self):
        cmd = sf._docker_command("/tmp/job", "name1", "run", "@@n@@")
        joined = " ".join(cmd)
        for flag in ("--network none", "--read-only", "--memory 256m", "--pids-limit 64", "--cpus 1",
                     "-v /tmp/job:/sandbox:ro", "--tmpfs /tmp:rw,size=64m", "--rm"):
            self.assertIn(flag, joined)
        self.assertEqual(cmd[-4:], ["-I", "/sandbox/_runner.py", "run", "@@n@@"])

    def test_mode_resolution(self):
        self.assertEqual(sf.resolve_sandbox_mode("docker"), "docker")
        self.assertEqual(sf.resolve_sandbox_mode("subprocess"), "subprocess")
        old = os.environ.get("PROMETHEUS_SKILL_SANDBOX")
        try:
            os.environ["PROMETHEUS_SKILL_SANDBOX"] = "subprocess"
            self.assertEqual(sf.resolve_sandbox_mode(), "subprocess")
        finally:
            if old is None:
                os.environ.pop("PROMETHEUS_SKILL_SANDBOX", None)
            else:
                os.environ["PROMETHEUS_SKILL_SANDBOX"] = old

    def test_an_unavailable_docker_is_reported_not_raised(self):
        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = ""            # the `docker` command cannot be found, whatever this machine has installed
        try:
            res = sf.run_isolated(simple_skill(1), "run", sandbox="docker", timeout=5)
        finally:
            os.environ["PATH"] = old_path
        self.assertFalse(res["ok"])
        self.assertIn("could not start", res["error"])

    def test_auto_mode_needs_a_working_daemon_not_just_the_cli(self):
        saved = dict(sf._docker_probe)
        try:
            sf._docker_probe.update(at=0.0, usable=False)
            calls = []
            real_run = sf.subprocess.run
            sf.subprocess.run = lambda *a, **k: (calls.append(a[0]), type("R", (), {"returncode": 1})())[1]
            try:
                self.assertEqual(sf.resolve_sandbox_mode("auto"), "subprocess")   # CLI present, daemon not answering
                self.assertEqual(len(calls), 1 if shutil.which("docker") else 0)
                sf.resolve_sandbox_mode("auto")
                self.assertEqual(len(calls), 1 if shutil.which("docker") else 0)  # the probe result is cached
                sf._docker_probe.update(at=0.0)
                sf.subprocess.run = lambda *a, **k: type("R", (), {"returncode": 0})()
                self.assertEqual(sf.resolve_sandbox_mode("auto"), "docker" if shutil.which("docker") else "subprocess")
            finally:
                sf.subprocess.run = real_run
        finally:
            sf._docker_probe.update(saved)

    def test_strong_sandbox_flag_follows_the_mode(self):
        tmp = tempfile.mkdtemp()
        try:
            self.assertFalse(sf.SkillRegistry(tmp, os.path.join(tmp, "r.json"), sandbox="subprocess").strongly_sandboxed)
            self.assertTrue(sf.SkillRegistry(tmp, os.path.join(tmp, "r.json"), sandbox="docker").strongly_sandboxed)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
