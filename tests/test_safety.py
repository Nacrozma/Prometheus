"""Tests for safety.py (policy, audit log, undo journal) and its wiring into prometheus.py."""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import safety  # noqa: E402


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="safety_")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def p(self, name):
        return os.path.join(self.tmp, name)


class RedactTests(unittest.TestCase):
    def test_secrets_and_long_values(self):
        out = safety.redact({"api_key": "abc", "note": "use sk-abcdefghijklmnop1234 now", "big": "x" * 1000,
                             "nested": {"Authorization": "Bearer z"}, "n": 3})
        self.assertEqual(out["api_key"], "<redacted>")
        self.assertNotIn("sk-abcdefghijklmnop1234", out["note"])
        self.assertLess(len(out["big"]), 400)
        self.assertEqual(out["nested"]["Authorization"], "<redacted>")
        self.assertEqual(out["n"], 3)
        json.dumps(safety.redact({"o": object(), "s": {1, 2}}))


class PolicyTests(Tmp):
    def test_missing_file_means_no_extra_rules(self):
        pol = safety.Policy(self.p("permissions.json"))
        self.assertIsNone(pol.check("write_file"))
        self.assertTrue(pol.path_allowed("anything/at/all.txt"))
        self.assertEqual(pol.problems, [])

    def test_deny_ask_and_scopes(self):
        json.dump({"deny": {"execute_shell": "no shell on this machine"}, "ask": ["web_search"],
                   "write_scopes": ["projects", "notes/"]}, open(self.p("permissions.json"), "w"))
        pol = safety.Policy(self.p("permissions.json"))
        self.assertIn("no shell", pol.check("execute_shell"))
        self.assertIsNone(pol.check("read_file"))
        self.assertTrue(pol.requires_confirmation("web_search"))
        self.assertTrue(pol.path_allowed("projects/a/b.py"))
        self.assertTrue(pol.path_allowed("notes/x.md"))
        self.assertFalse(pol.path_allowed("projectsX/a.py"))     # prefix must be a whole folder
        self.assertFalse(pol.path_allowed("elsewhere/a.py"))

    def test_deny_as_list(self):
        json.dump({"deny": ["ghost_control"]}, open(self.p("permissions.json"), "w"))
        self.assertIsNotNone(safety.Policy(self.p("permissions.json")).check("ghost_control"))

    def test_a_malformed_file_is_reported_not_quarantined_and_builtin_rules_stand(self):
        open(self.p("permissions.json"), "w").write("{oops")
        pol = safety.Policy(self.p("permissions.json"))
        self.assertTrue(pol.problems)
        self.assertTrue(os.path.exists(self.p("permissions.json")))     # the operator's file is left alone
        self.assertEqual([f for f in os.listdir(self.tmp) if "corrupt" in f], [])

    def test_wrong_types_are_reported(self):
        json.dump({"deny": 5, "ask": "x", "write_scopes": 7}, open(self.p("permissions.json"), "w"))
        self.assertEqual(len(safety.Policy(self.p("permissions.json")).problems), 3)


class AuditTests(Tmp):
    def test_chain_verifies_and_tail_reads_back(self):
        log = safety.AuditLog(self.p("audit.jsonl"))
        for i in range(5):
            log.record("read_file", {"path": f"f{i}", "api_key": "secret"}, "success", "", 0.01)
        ok, note = log.verify()
        self.assertTrue(ok, note)
        tail = log.tail(3)
        self.assertEqual([r["seq"] for r in tail], [3, 4, 5])
        self.assertNotIn("secret", open(self.p("audit.jsonl")).read())

    def test_editing_deleting_or_reordering_is_detected(self):
        log = safety.AuditLog(self.p("audit.jsonl"))
        for i in range(4):
            log.record("t", {"i": i}, "success")
        lines = open(self.p("audit.jsonl")).read().splitlines()
        cases = {"edited": [lines[0], lines[1].replace('\\"i\\": 1', '\\"i\\": 9'), *lines[2:]],
                 "deleted": [lines[0], *lines[2:]],
                 "reordered": [lines[1], lines[0], *lines[2:]]}
        for name, new in cases.items():
            with self.subTest(name):
                open(self.p("audit.jsonl"), "w").write("\n".join(new) + "\n")
                self.assertFalse(safety.AuditLog(self.p("audit.jsonl")).verify()[0])

    def test_resumes_the_chain_after_restart(self):
        safety.AuditLog(self.p("audit.jsonl")).record("a", {}, "success")
        again = safety.AuditLog(self.p("audit.jsonl"))
        again.record("b", {}, "success")
        self.assertTrue(again.verify()[0])
        self.assertEqual(again.tail(5)[-1]["seq"], 2)

    def test_garbage_in_the_log_is_reported_and_never_raises(self):
        open(self.p("audit.jsonl"), "w").write("not json at all\n")
        log = safety.AuditLog(self.p("audit.jsonl"))
        self.assertFalse(log.verify()[0])
        self.assertTrue(log.record("a", {}, "success"))

    def test_record_never_raises_on_an_unwritable_path(self):
        self.assertFalse(safety.AuditLog(os.path.join(self.tmp, "no", "such", "dir", "a.jsonl")).record("a", {}, "x"))

    def test_rotation(self):
        log = safety.AuditLog(self.p("audit.jsonl"), max_bytes=300)
        for i in range(10):
            log.record("t", {"i": i}, "success")
        self.assertTrue(any(f.startswith("audit.jsonl.") for f in os.listdir(self.tmp)))
        self.assertTrue(log.verify()[0])


class UndoTests(Tmp):
    def setUp(self):
        super().setUp()
        self.j = safety.UndoJournal(self.p(".undo"))
        self.f = self.p("a.txt")

    def change(self, new):
        uid = self.j.snapshot(self.f)
        open(self.f, "w").write(new)
        self.j.commit(uid)

    def test_undo_restores_previous_content(self):
        open(self.f, "w").write("one")
        self.change("two")
        res = self.j.undo()
        self.assertEqual(res["status"], "success")
        self.assertEqual(open(self.f).read(), "one")
        self.assertEqual(self.j.undo()["status"], "error")           # nothing left

    def test_undo_removes_a_file_prometheus_created(self):
        self.change("new")
        self.assertEqual(self.j.undo()["status"], "success")
        self.assertFalse(os.path.exists(self.f))

    def test_a_stack_of_changes_unwinds_in_order(self):
        open(self.f, "w").write("0")
        for v in "123":
            self.change(v)
        for expect in "210":
            self.j.undo()
            self.assertEqual(open(self.f).read(), expect)

    def test_refuses_to_clobber_later_edits(self):
        open(self.f, "w").write("one")
        self.change("two")
        open(self.f, "w").write("the operator edited this by hand")
        res = self.j.undo()
        self.assertEqual(res["status"], "error")
        self.assertEqual(open(self.f).read(), "the operator edited this by hand")

    def test_damaged_backup_is_not_restored(self):
        open(self.f, "w").write("one")
        self.change("two")
        bak = [x for x in os.listdir(self.p(".undo")) if x.endswith(".bak")][0]
        open(os.path.join(self.p(".undo"), bak), "w").write("tampered")
        self.assertEqual(self.j.undo()["status"], "error")
        self.assertEqual(open(self.f).read(), "two")

    def test_abort_drops_the_entry(self):
        open(self.f, "w").write("one")
        uid = self.j.snapshot(self.f)
        self.j.abort(uid)
        self.assertEqual(self.j.list(), [])

    def test_the_journal_is_bounded(self):
        j = safety.UndoJournal(self.p(".u2"), max_entries=3)
        for i in range(8):
            open(self.f, "w").write(str(i))
            uid = j.snapshot(self.f)
            open(self.f, "w").write("x" + str(i))
            j.commit(uid)
        self.assertEqual(len(j.list(100)), 3)
        self.assertEqual(len([x for x in os.listdir(self.p(".u2")) if x.endswith(".bak")]), 3)

    def test_oversized_files_are_skipped_not_fatal(self):
        j = safety.UndoJournal(self.p(".u3"), max_file_bytes=10)
        open(self.f, "w").write("x" * 100)
        self.assertIsNone(j.snapshot(self.f))
        j.commit(None)
        j.abort(None)

    def test_binary_content_roundtrips(self):
        open(self.f, "wb").write(bytes(range(256)))
        uid = self.j.snapshot(self.f)
        open(self.f, "wb").write(b"changed")
        self.j.commit(uid)
        self.j.undo()
        self.assertEqual(open(self.f, "rb").read(), bytes(range(256)))


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("PROMETHEUS_FAST_BOOT", "1")
        from test_memory_integration import Redirected
        cls.Base = Redirected

    def run_case(self, body):
        Base = self.Base

        class Case(Base):
            def runTest(inner):
                import prometheus as p
                saved = (p.BASE_DIR, p.UNDO_DIR)
                p.BASE_DIR = inner.tmp
                p.UNDO_DIR = os.path.join(inner.tmp, ".undo")
                try:
                    body(inner, p)
                finally:
                    p.BASE_DIR, p.UNDO_DIR = saved

        import io
        res = unittest.TextTestRunner(stream=io.StringIO()).run(Case())
        self.assertTrue(res.wasSuccessful(), [str(e[1]) for e in res.errors + res.failures])

    def test_denied_tools_never_run_and_are_audited(self):
        def body(t, p):
            json.dump({"deny": {"write_file": "read-only session"}}, open(os.path.join(t.tmp, "permissions.json"), "w"))
            p.policy.reload()
            target = os.path.join(t.tmp, "x.txt")
            res = t.dispatch("write_file", path=target, content="hi")
            t.assertEqual(res["status"], "refused")
            t.assertFalse(os.path.exists(target))
            last = p.audit_log.tail(1)[0]
            t.assertEqual((last["tool"], last["outcome"]), ("write_file", "refused"))
            t.assertEqual(p.tool_stats.summary()["write_file"]["failures"], 0)   # a refusal is not the tool's fault
        self.run_case(body)

    def test_write_and_edit_are_journalled_and_undoable(self):
        def body(t, p):
            f = os.path.join(t.tmp, "notes.txt")
            t.assertEqual(t.dispatch("write_file", path=f, content="v1")["status"], "success")
            t.assertEqual(t.dispatch("edit_file", path=f, old_string="v1", new_string="v2")["status"], "success")
            t.assertEqual(open(f).read(), "v2")
            t.assertEqual(p.undo_journal.undo()["status"], "success")
            t.assertEqual(open(f).read(), "v1")
            t.assertEqual(p.undo_journal.undo()["status"], "success")
            t.assertFalse(os.path.exists(f))
            t.assertTrue(p.audit_log.verify()[0])
        self.run_case(body)

    def test_a_failed_write_leaves_no_journal_entry(self):
        def body(t, p):
            t.dispatch("edit_file", path=os.path.join(t.tmp, "missing.txt"), old_string="a", new_string="b")
            t.assertEqual(p.undo_journal.list(), [])
        self.run_case(body)

    def test_write_scopes_confine_the_workspace_tools(self):
        def body(t, p):
            json.dump({"write_scopes": ["sandbox"]}, open(os.path.join(t.tmp, "permissions.json"), "w"))
            p.policy.reload()
            ok = t.dispatch("write_file", path=os.path.join(t.tmp, "sandbox", "a.txt"), content="x")
            bad = t.dispatch("write_file", path=os.path.join(t.tmp, "other.txt"), content="x")
            t.assertEqual(ok["status"], "success")
            t.assertEqual(bad["status"], "error")
            t.assertFalse(os.path.exists(os.path.join(t.tmp, "other.txt")))
        self.run_case(body)

    def test_the_model_cannot_rewrite_its_own_rules_audit_or_modules(self):
        def body(t, p):
            for name in ("permissions.json", "audit.jsonl", "skills.json", "safety.py", "skill_forge.py", "memory_graph.py"):
                res = t.dispatch("write_file", path=os.path.join(t.tmp, name), content="x")
                t.assertEqual(res["status"], "error", name)
                if name != "audit.jsonl":                # the audit log legitimately exists (the refusals are in it)
                    t.assertFalse(os.path.exists(os.path.join(t.tmp, name)), name)
            t.assertTrue(p.audit_log.verify()[0])
            res = t.dispatch("write_file", path=os.path.join(t.tmp, ".undo", "index.json"), content="{}")
            t.assertEqual(res["status"], "error")
        self.run_case(body)

    def test_ask_rules_extend_the_confirmation_set_but_never_shrink_it(self):
        def body(t, p):
            json.dump({"ask": ["web_search"]}, open(os.path.join(t.tmp, "permissions.json"), "w"))
            p.policy.reload()
            t.assertIn("web_search", p.DANGEROUS_TOOLS)
            for builtin in ("execute_shell", "write_file", "edit_file", "apply_pending_patch"):
                t.assertIn(builtin, p.DANGEROUS_TOOLS)
            json.dump({"ask": [], "deny": []}, open(os.path.join(t.tmp, "permissions.json"), "w"))
            p.policy.reload()
            t.assertIn("execute_shell", p.DANGEROUS_TOOLS)            # an empty policy cannot loosen the built-ins
            t.assertNotIn("web_search", p.DANGEROUS_TOOLS)
        self.run_case(body)

    def test_secrets_in_tool_arguments_do_not_reach_the_audit_log(self):
        def body(t, p):
            t.dispatch("read_file", path=os.path.join(t.tmp, "nope.txt"), api_key="sk-supersecretvalue12345")
            t.assertNotIn("supersecretvalue", open(os.path.join(t.tmp, "audit.jsonl")).read())
        self.run_case(body)


if __name__ == "__main__":
    unittest.main()
