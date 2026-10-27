"""Tests for patch_gate.py - the automatic gate on self-modification.

Almost everything runs against a tiny synthetic project in a temp directory (fast, and
it cannot recurse into the real test suite). One optional slow test runs the gate against
the REAL project: set RUN_SLOW_TESTS=1.
"""
import hashlib
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import patch_gate as pg  # noqa: E402

CORE = '''"""A miniature stand-in for prometheus.py."""
CASES = [1, 2, 3]
DANGEROUS = frozenset({"shell", "write_file"})


def dispatch(x):
    return x * 2


def main():
    return "ok"
'''
TEST_CORE = '''import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core


class CoreTests(unittest.TestCase):
    def test_dispatch(self):
        self.assertEqual(core.dispatch(2), 4)

    def test_main(self):
        self.assertEqual(core.main(), "ok")

    def test_safety_list(self):
        self.assertIn("shell", core.DANGEROUS)


for _n in core.CASES:                      # one generated test per case: shrinking CASES silently drops tests
    setattr(CoreTests, f"test_case_{_n}", lambda self, n=_n: self.assertTrue(n))
'''
REQUIRED = {"dispatch", "main", "DANGEROUS"}


def sha_tree(base):
    h = hashlib.sha256()
    for d, _, files in sorted(os.walk(base)):
        for f in sorted(files):
            p = os.path.join(d, f)
            if "__pycache__" in p:
                continue
            h.update(p.encode())
            with open(p, "rb") as fh:
                h.update(fh.read())
    return h.hexdigest()


class GateCase(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="gate_repo_")
        os.makedirs(os.path.join(self.repo, "tests"))
        with open(os.path.join(self.repo, "core.py"), "w") as f:
            f.write(CORE)
        with open(os.path.join(self.repo, "tests", "test_core.py"), "w") as f:
            f.write(TEST_CORE)

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def gate(self, new, **kw):
        kw.setdefault("required_symbols", REQUIRED)
        kw.setdefault("protected_assignments", ["DANGEROUS"])
        kw.setdefault("timeout", 60)
        return pg.validate_patch(self.repo, "core.py", new, **kw)

    def failed(self, result):
        return [c["name"] for c in result["checks"] if not c["passed"]]


@unittest.skipIf(os.getenv("PROMETHEUS_PATCH_GATE_ACTIVE"), "already running inside a gate")
class StaticCheckTests(GateCase):
    def test_a_harmless_improvement_is_accepted(self):
        res = self.gate(CORE + "\n\ndef helper():\n    return 1\n")
        self.assertTrue(res["accepted"], res["problems"])
        self.assertEqual(res["tests"]["baseline"]["failed"], [])
        self.assertGreaterEqual(res["tests"]["patched"]["ran"], 5)

    def test_syntax_errors_are_rejected(self):
        res = self.gate("def broken(:\n")
        self.assertEqual(self.failed(res), ["parses"])
        self.assertIsNone(res["tests"])

    def test_removing_a_required_symbol_is_rejected(self):
        res = self.gate(CORE.replace("def main():\n    return \"ok\"\n", ""))
        self.assertEqual(self.failed(res), ["required symbols still defined"])
        self.assertIn("main", res["problems"][0])

    def test_weakening_a_safety_list_is_rejected(self):
        res = self.gate(CORE.replace('frozenset({"shell", "write_file"})', 'frozenset({"write_file"})'))
        self.assertEqual(self.failed(res), ["safety list DANGEROUS not weakened"])
        self.assertIn("shell", res["problems"][0])

    def test_adding_to_a_safety_list_is_fine(self):
        res = self.gate(CORE.replace('"write_file"}', '"write_file", "extra"}'))
        self.assertTrue(res["accepted"], res["problems"])

    def test_deleting_a_safety_list_is_rejected(self):
        res = self.gate(CORE.replace('DANGEROUS = frozenset({"shell", "write_file"})\n', "DANGEROUS = frozenset()\n"))
        self.assertIn("safety list DANGEROUS not weakened", self.failed(res))
        res = self.gate(CORE.replace('DANGEROUS = frozenset({"shell", "write_file"})\n', "DANGEROUS_RENAMED = 1\n"))
        self.assertTrue(any("DANGEROUS" in p for p in res["problems"]))

    def test_wholesale_rewrites_are_rejected(self):
        rewrite = "CASES = [1, 2, 3]\ndef dispatch(x):\n    return x * 2\n\ndef main():\n    return 'ok'\n\nDANGEROUS = frozenset({'shell', 'write_file'})\n" + \
                  "\n".join(f"# filler line {i}" for i in range(200))
        res = self.gate(rewrite)
        self.assertEqual(self.failed(res), ["change size"])
        self.assertTrue(self.gate(rewrite, max_changed_ratio=0.99)["accepted"])

    def test_oversized_and_empty_content(self):
        self.assertEqual(self.failed(self.gate("x = 1\n" * 400_000)), ["size"])
        self.assertEqual(self.failed(self.gate("")), ["size"])

    def test_missing_target_file(self):
        res = pg.validate_patch(self.repo, "nope.py", "x = 1\n")
        self.assertEqual(self.failed(res), ["current file readable"])


@unittest.skipIf(os.getenv("PROMETHEUS_PATCH_GATE_ACTIVE"), "already running inside a gate")
class TestRunTests(GateCase):
    def test_a_patch_that_breaks_behaviour_is_rejected(self):
        res = self.gate(CORE.replace("return x * 2", "return x * 3"))
        self.assertEqual(self.failed(res), ["no new test failures"])
        self.assertIn("test_dispatch", res["problems"][0])

    def test_a_patch_that_silently_drops_tests_is_rejected(self):
        res = self.gate(CORE.replace("CASES = [1, 2, 3]", "CASES = [1]"))
        self.assertEqual(self.failed(res), ["no tests disappeared"])

    def test_a_patch_that_hangs_is_stopped(self):
        res = self.gate(CORE + "\nwhile True:\n    pass\n", timeout=6)
        self.assertIn("tests ran in time", self.failed(res))

    def test_a_patch_that_cannot_be_imported_is_rejected(self):
        res = self.gate(CORE + "\nimport definitely_not_a_real_module_xyz\n")
        self.assertIn("no new test failures", self.failed(res))

    def test_preexisting_failures_do_not_block_a_good_patch_but_new_ones_do(self):
        with open(os.path.join(self.repo, "tests", "test_known_broken.py"), "w") as f:
            f.write("import unittest\n\nclass Broken(unittest.TestCase):\n    def test_known_failure(self):\n        self.fail('was already failing')\n")
        good = self.gate(CORE + "\n\ndef helper():\n    return 1\n")
        self.assertTrue(good["accepted"], good["problems"])
        self.assertEqual(len(good["tests"]["baseline"]["failed"]), 1)
        bad = self.gate(CORE.replace("return x * 2", "return x * 3"))
        self.assertFalse(bad["accepted"])

    def test_a_project_without_tests_cannot_be_patched(self):
        shutil.rmtree(os.path.join(self.repo, "tests"))
        res = self.gate(CORE + "\n# comment\n")
        self.assertEqual(self.failed(res), ["tests exist"])

    def test_disabling_tests_never_means_accepting(self):
        res = self.gate(CORE + "\n# comment\n", run_tests=False)
        self.assertFalse(res["accepted"])
        self.assertIn("tests", self.failed(res))

    def test_the_real_files_are_never_touched(self):
        before = sha_tree(self.repo)
        self.gate(CORE + "\n\ndef helper():\n    return 1\n")
        self.gate(CORE.replace("return x * 2", "return x * 3"))
        self.assertEqual(sha_tree(self.repo), before)

    def test_temp_copies_are_cleaned_up(self):
        import glob
        pattern = os.path.join(tempfile.gettempdir(), "patch_gate_*")
        before = set(glob.glob(pattern))
        self.gate(CORE + "\n\ndef helper():\n    return 1\n")
        self.gate(CORE.replace("return x * 2", "return x * 3"))
        self.assertEqual(set(glob.glob(pattern)) - before, set())

    def test_the_baseline_is_cached_for_an_unchanged_project(self):
        calls = []
        real = pg.run_unittests
        pg.run_unittests = lambda *a, **k: (calls.append(1), real(*a, **k))[1]
        try:
            pg._baseline_cache.clear()
            self.gate(CORE + "\n\ndef a():\n    return 1\n")
            self.assertEqual(len(calls), 2)          # baseline + patched
            self.gate(CORE + "\n\ndef b():\n    return 2\n")
            self.assertEqual(len(calls), 3)          # only the patched run: baseline reused
            with open(os.path.join(self.repo, "core.py"), "a") as f:
                f.write("\n# the project changed\n")
            self.gate(CORE + "\n\ndef c():\n    return 3\n")
            self.assertEqual(len(calls), 5)          # project changed -> a fresh baseline
        finally:
            pg.run_unittests = real

    def test_tests_run_without_the_callers_secrets(self):
        with open(os.path.join(self.repo, "tests", "test_env.py"), "w") as f:
            f.write("import os\nimport unittest\n\nclass Env(unittest.TestCase):\n"
                    "    def test_no_secrets(self):\n        self.assertNotIn('SECRET_CANARY_KEY', os.environ)\n"
                    "    def test_marked_as_gate_run(self):\n        self.assertEqual(os.environ.get('PROMETHEUS_PATCH_GATE_ACTIVE'), '1')\n")
        os.environ["SECRET_CANARY_KEY"] = "sk-should-never-be-visible"
        try:
            report = pg.run_unittests(self.repo, "tests", timeout=60)
        finally:
            os.environ.pop("SECRET_CANARY_KEY", None)
        self.assertTrue(report["ok"], report["tail"])


class HelperTests(unittest.TestCase):
    def test_top_level_names(self):
        import ast
        tree = ast.parse("import os.path\nfrom a import b as c\nX = 1\nY: int = 2\n(P, Q) = 1, 2\ndef f(): pass\nclass K: pass\n")
        self.assertEqual(pg.top_level_names(tree), {"os", "c", "X", "Y", "P", "Q", "f", "K"})

    def test_assignment_strings_collects_nested_constants(self):
        import ast
        tree = ast.parse('D = Registry({"a", "b", ("c",)})\nE = 5\n')
        self.assertEqual(pg.assignment_strings(tree, "D"), {"a", "b", "c"})
        self.assertEqual(pg.assignment_strings(tree, "E"), set())
        self.assertIsNone(pg.assignment_strings(tree, "missing"))


@unittest.skipUnless(os.getenv("RUN_SLOW_TESTS") == "1" and not os.getenv("PROMETHEUS_PATCH_GATE_ACTIVE"),
                     "slow: set RUN_SLOW_TESTS=1 to run the gate against the real project")
class RealProjectTests(unittest.TestCase):
    def test_an_identity_patch_of_prometheus_py_is_accepted(self):
        with open(os.path.join(ROOT, "prometheus.py"), encoding="utf-8") as f:
            current = f.read()
        res = pg.validate_patch(ROOT, "prometheus.py", current,
                                required_symbols={"dispatch_tool", "main", "update_memory_fact", "DANGEROUS_TOOLS"},
                                protected_assignments=["DANGEROUS_TOOLS"], timeout=600)
        self.assertTrue(res["accepted"], res["problems"])
        self.assertGreater(res["tests"]["patched"]["ran"], 150)


if __name__ == "__main__":
    unittest.main()
