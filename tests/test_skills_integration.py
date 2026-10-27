"""
Integration tests: prometheus.py <-> skill_forge.py / patch_gate.py.

Skills, registries, pending patches and "target" source files all live in temp
directories; the real prometheus.py is never modified.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import skill_forge  # noqa: E402
import prometheus as p  # noqa: E402
from test_memory_integration import Redirected, capture  # noqa: E402

GOOD = "def execute(a=0, b=0, **kw):\n    return a + b\n"
GOOD_TESTS = "def test_adds():\n    assert skill.execute(a=2, b=3) == 5\n\ndef test_zero():\n    assert skill.execute() == 0\n"


class SkillCase(Redirected):
    def setUp(self):
        super().setUp()
        self.skills_dir = os.path.join(self.tmp, "skills")
        self._skill_saved = (p.skill_registry, p.DYNAMIC_TOOLS_DIR)
        p.skill_registry = skill_forge.SkillRegistry(self.skills_dir, os.path.join(self.tmp, "skills.json"),
                                                     reserved_names=p._RESERVED_SKILL_NAMES, sandbox="subprocess")
        p.DYNAMIC_TOOLS_DIR = self.skills_dir

    def tearDown(self):
        p.skill_registry, p.DYNAMIC_TOOLS_DIR = self._skill_saved
        super().tearDown()

    def teach(self, name="adder", code=GOOD, tests=GOOD_TESTS, description="Adds two numbers"):
        return self.dispatch("synthesize_dynamic_tool", tool_name=name, description=description,
                             python_code=code, tests_code=tests)


class SkillToolTests(SkillCase):
    def test_a_tested_skill_is_installed_remembered_and_runnable(self):
        r = self.teach()
        self.assertEqual((r["status"], r["version"], r["tests"]), ("success", 1, "2/2 passing"))
        self.assertIn("run_skill", r["message"])
        self.assertEqual(self.dispatch("run_skill", name="adder", args={"a": 4, "b": 5})["result"], 9)
        self.assertEqual(self.dispatch("adder", a=1, b=1)["result"], 2)     # callable directly by its name too
        self.assertIn("adder", [s["name"] for s in self.dispatch("list_skills")["skills"]])
        with open(self.mem) as f:
            self.assertIn("adder", json.load(f)["synthesized_tools"])
        view = p.memory_graph.neighbors("adder")
        self.assertEqual(view["entity"]["type"], "skill")
        self.assertIn("installed", view["facts"][0]["text"])

    def test_a_rejected_skill_returns_reasons_and_installs_nothing(self):
        r = self.teach(tests="def test_wrong():\n    assert skill.execute(a=1, b=1) == 3\n")
        self.assertEqual((r["status"], r["stage"]), ("error", "tests"))
        self.assertIn("test_wrong", r["problems"][0])
        r = self.teach(name="evil", code="import os\n\ndef execute(**kw):\n    return os.listdir('/')\n")
        self.assertEqual(r["stage"], "policy")
        self.assertEqual(self.dispatch("list_skills")["skills"], [])
        self.assertEqual(self.dispatch("evil")["status"], "unknown_tool")

    def test_tests_are_required(self):
        r = self.dispatch("synthesize_dynamic_tool", tool_name="adder", description="d", python_code=GOOD)
        self.assertEqual((r["status"], r["stage"]), ("error", "policy"))

    def test_builtin_tool_names_cannot_be_shadowed(self):
        for name in ("read_file", "web_search", "update_memory", "run_skill", "execute_python"):
            self.assertEqual(self.teach(name=name)["stage"], "name", name)

    def test_files_written_straight_to_disk_are_never_executed(self):
        """Older versions wrote tools into dynamic_tools/ and imported them in-process."""
        os.makedirs(self.skills_dir, exist_ok=True)
        marker = os.path.join(self.tmp, "PWNED")
        with open(os.path.join(self.skills_dir, "legacy_tool.py"), "w") as f:
            f.write(f"def execute(**kw):\n    open({marker!r}, 'w').write('x')\n    return 1\n")
        r = self.dispatch("legacy_tool")
        self.assertEqual(r["status"], "unknown_tool")
        self.assertFalse(os.path.exists(marker))
        self.assertEqual(self.dispatch("list_skills")["unregistered_files_ignored"], ["legacy_tool"])
        self.assertNotIn("legacy_tool", p.DANGEROUS_TOOLS)   # not callable, so nothing to confirm

    def test_a_skill_edited_on_disk_refuses_to_run(self):
        self.teach()
        with open(os.path.join(self.skills_dir, "adder.py"), "a") as f:
            f.write("\n# edited\n")
        r = self.dispatch("run_skill", name="adder", args={})
        self.assertEqual(r["status"], "error")
        self.assertIn("modified outside the registry", r["message"])

    def test_versioning_and_rollback_through_the_tools(self):
        self.teach()
        self.teach(code="def execute(a=0, b=0, **kw):\n    return a + b + 100\n",
                   tests="def test_plus_100():\n    assert skill.execute(a=1, b=1) == 102\n")
        self.assertEqual(self.dispatch("run_skill", name="adder", args={"a": 1, "b": 1})["result"], 102)
        self.assertEqual(self.dispatch("rollback_skill", name="adder")["version"], 1)
        self.assertEqual(self.dispatch("run_skill", name="adder", args={"a": 1, "b": 1})["result"], 2)
        lessons = p.memory_graph.recall("adder rolled back", kinds=["lesson"])
        self.assertTrue(lessons)

    def test_run_skill_validates_its_input(self):
        self.assertEqual(self.dispatch("run_skill", name="ghost")["status"], "error")
        self.teach()
        self.assertEqual(self.dispatch("run_skill", name="adder", args="not an object")["status"], "error")
        self.assertEqual(self.dispatch("run_skill", name="adder")["result"], 0)

    def test_skills_appear_in_the_prompt_context(self):
        self.assertNotIn("AVAILABLE SKILLS", p.build_context_block("hello"))
        self.teach()
        block = p.build_context_block("hello")
        self.assertIn("[AVAILABLE SKILLS", block)
        self.assertIn("adder: Adds two numbers (v1)", block)

    def test_tool_schema_and_confirmation_rules(self):
        names = {t["function"]["name"] for t in p.TOOLS}
        self.assertTrue({"run_skill", "list_skills", "rollback_skill", "synthesize_dynamic_tool"} <= names)
        spec = next(t for t in p.TOOLS if t["function"]["name"] == "synthesize_dynamic_tool")["function"]["parameters"]
        self.assertIn("tests_code", spec["required"])
        self.assertIn("synthesize_dynamic_tool", p.DANGEROUS_TOOLS)          # installing always needs a human yes
        self.assertIn("run_skill", p.DANGEROUS_TOOLS)                        # no Docker here -> confirm each run
        p.skill_registry.sandbox = "docker"
        self.assertNotIn("run_skill", p.DANGEROUS_TOOLS)                     # real boundary -> no prompt
        self.assertIn("synthesize_dynamic_tool", p.DANGEROUS_TOOLS)

    def test_skills_reach_the_obsidian_vault(self):
        self.teach()
        vault = self.make_vault()
        p.set_obsidian_vault(vault)
        self.assertEqual(self.dispatch("export_obsidian")["status"], "success")
        with open(os.path.join(vault, "Prometheus", "Entities", "adder.md"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("Adds two numbers", text)       # the skill IS its entity note: one node in the graph
        self.assertIn("2/2 passing", text)
        self.assertIn("prometheus/skill", text)
        self.assertFalse(os.path.exists(os.path.join(vault, "Prometheus", "Skills", "adder.md")))
        self.assertEqual([e["name"] for e in p.memory_graph.entities.values()], ["adder"])   # and no junk entities

    def test_the_skills_slash_command(self):
        out = capture(p.handle_slash_command, "/skills")[1]
        self.assertIn("No skills yet", out)
        self.teach()
        out = capture(p.handle_slash_command, "/skills")[1]
        self.assertIn("adder  v1  active  2/2 passing", out)
        self.assertIn("no Docker", out)
        self.assertIn("disabled", capture(p.handle_slash_command, "/skills off adder")[1])
        self.assertEqual(self.dispatch("run_skill", name="adder")["status"], "error")
        capture(p.handle_slash_command, "/skills on adder")
        self.assertEqual(self.dispatch("run_skill", name="adder")["status"], "success")
        self.assertIn("Usage: /skills", capture(p.handle_slash_command, "/skills rollback")[1])
        self.assertIn("/skills", capture(p.handle_slash_command, "/help")[1])


class PatchGateWiringTests(Redirected):
    """tool_propose_code_change / tool_apply_pending_patch with the gate stubbed, against temp 'source' files."""

    def setUp(self):
        super().setUp()
        self.target = os.path.join(self.tmp, "target.py")
        with open(self.target, "w") as f:
            f.write("VALUE = 1\n")
        self.pending = os.path.join(self.tmp, "pending")
        os.makedirs(self.pending)
        self._saved_patch = (p._self_patch_targets, p.PENDING_PATCHES_DIR, p.run_patch_gate)
        p._self_patch_targets = lambda: {"prometheus.py": self.target}
        p.PENDING_PATCHES_DIR = self.pending
        self.gate_calls = []
        self.verdict = {"accepted": True, "problems": [], "checks": [], "tests": None}

        def fake_gate(target_file, new_content):
            self.gate_calls.append((target_file, new_content))
            return self.verdict
        p.run_patch_gate = fake_gate

    def tearDown(self):
        p._self_patch_targets, p.PENDING_PATCHES_DIR, p.run_patch_gate = self._saved_patch
        super().tearDown()

    def read_target(self):
        with open(self.target) as f:
            return f.read()

    def test_a_rejected_proposal_is_never_saved(self):
        self.verdict = {"accepted": False, "problems": ["no new test failures: test_x"], "checks": []}
        r = p.tool_propose_code_change("prometheus.py", "VALUE = 2\n", "why")
        self.assertEqual((r["status"], r["stage"]), ("rejected", "automatic gate"))
        self.assertEqual(r["problems"], ["no new test failures: test_x"])
        self.assertEqual(os.listdir(self.pending), [])
        self.assertEqual(self.read_target(), "VALUE = 1\n")

    def test_an_accepted_proposal_is_saved_and_applied_after_a_second_check(self):
        r = p.tool_propose_code_change("prometheus.py", "VALUE = 2\n", "bump")
        self.assertEqual(r["status"], "success")
        self.assertEqual(len(self.gate_calls), 1)
        applied = p.tool_apply_pending_patch(r["patch_id"])
        self.assertEqual(applied["status"], "success")
        self.assertEqual(len(self.gate_calls), 2)                  # re-checked at apply time
        self.assertEqual(self.read_target(), "VALUE = 2\n")
        self.assertTrue(os.path.exists(applied["backup_path"]))

    def test_a_patch_that_fails_the_recheck_stays_pending_and_the_file_is_untouched(self):
        r = p.tool_propose_code_change("prometheus.py", "VALUE = 2\n")
        self.verdict = {"accepted": False, "problems": ["the project changed"], "checks": []}
        applied = p.tool_apply_pending_patch(r["patch_id"])
        self.assertEqual((applied["status"], applied["stage"]), ("rejected", "automatic gate (re-check at apply time)"))
        self.assertEqual(self.read_target(), "VALUE = 1\n")
        self.assertTrue(os.path.exists(os.path.join(self.pending, f"{r['patch_id']}.json")))

    def test_identical_content_is_a_noop_and_never_reaches_the_gate(self):
        self.assertEqual(p.tool_propose_code_change("prometheus.py", "VALUE = 1\n")["status"], "noop")
        self.assertEqual(self.gate_calls, [])


class PatchGateConfigTests(unittest.TestCase):
    def test_the_symbol_lists_name_things_that_really_exist(self):
        for sym in p.PATCH_GATE_SYMBOLS["prometheus.py"] | set(p.PATCH_GATE_PROTECTED_LISTS["prometheus.py"]):
            self.assertTrue(hasattr(p, sym), f"prometheus.py no longer defines {sym}; the gate list has gone stale")
        import ast
        with open(os.path.join(ROOT, "gui_orb.py"), encoding="utf-8") as f:
            defined = patch_gate_names(f.read())
        self.assertTrue(p.PATCH_GATE_SYMBOLS["gui_orb.py"] <= defined, p.PATCH_GATE_SYMBOLS["gui_orb.py"] - defined)

    def test_run_patch_gate_passes_the_right_configuration(self):
        import patch_gate
        seen = {}
        real = patch_gate.validate_patch
        patch_gate.validate_patch = lambda *a, **k: (seen.update(args=a, kwargs=k), {"accepted": True, "problems": [], "checks": []})[1]
        old = os.environ.get("PROMETHEUS_PATCH_GATE_TIMEOUT")
        try:
            os.environ["PROMETHEUS_PATCH_GATE_TIMEOUT"] = "not a number"
            p.run_patch_gate("prometheus.py", "x = 1\n")
        finally:
            patch_gate.validate_patch = real
            if old is None:
                os.environ.pop("PROMETHEUS_PATCH_GATE_TIMEOUT", None)
            else:
                os.environ["PROMETHEUS_PATCH_GATE_TIMEOUT"] = old
        self.assertEqual(seen["args"][1], "prometheus.py")
        self.assertIn("DANGEROUS_TOOLS", seen["kwargs"]["protected_assignments"])
        self.assertIn("dispatch_tool", seen["kwargs"]["required_symbols"])
        self.assertEqual(seen["kwargs"]["timeout"], 240)                     # a bad value falls back to the default

    def test_the_gate_can_only_be_disabled_explicitly(self):
        old = os.environ.get("PROMETHEUS_PATCH_GATE")
        try:
            os.environ["PROMETHEUS_PATCH_GATE"] = "off"
            res = p.run_patch_gate("prometheus.py", "this is not even python (")
            self.assertTrue(res["accepted"])
            self.assertIn("disabled", res["checks"][0]["name"])
            os.environ["PROMETHEUS_PATCH_GATE"] = "0"                           # anything but "off" keeps it on
            self.assertFalse(p.run_patch_gate("prometheus.py", "this is not even python (")["accepted"])
        finally:
            if old is None:
                os.environ.pop("PROMETHEUS_PATCH_GATE", None)
            else:
                os.environ["PROMETHEUS_PATCH_GATE"] = old


def patch_gate_names(source):
    import ast
    import patch_gate
    return patch_gate.top_level_names(ast.parse(source))


if __name__ == "__main__":
    unittest.main()
