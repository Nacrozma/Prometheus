"""Renaissance services: conversations, universal search, memory controls (no GUI needed)."""

import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.services.conversations import ConversationStore, title_from, visible  # noqa: E402
from app.services import search as S  # noqa: E402


class TestConversations(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.store = ConversationStore(self.dir)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_legacy_session_becomes_first_conversation_once_and_is_not_deleted(self):
        legacy = [{"role": "user", "content": "Hello there"}, {"role": "assistant", "content": "Hi."}]
        c = self.store.open_current(legacy)
        self.assertEqual(c["title"], "Hello there")
        self.assertEqual(len(c["messages"]), 2)
        again = self.store.open_current([{"role": "user", "content": "other"}])
        self.assertEqual(again["id"], c["id"], "the open conversation is reopened, legacy is imported once")
        self.assertEqual(len(self.store.list()), 1)

    def test_create_title_rename_search_delete(self):
        a = self.store.create([{"role": "user", "content": "Plan the trajectory model " + "x " * 40}])
        self.assertTrue(a["title"].endswith("…"))
        self.assertLessEqual(len(a["title"]), 49)
        b = self.store.create([{"role": "user", "content": "Groceries"}, {"role": "assistant", "content": "Milk and eggs"}])
        self.assertEqual(self.store.current_id(), b["id"])
        self.assertEqual([c["id"] for c in self.store.list("eggs")], [b["id"]], "search covers message text")
        self.assertTrue(self.store.rename(a["id"], "  Rocket   plan "))
        self.assertEqual(self.store.get(a["id"])["title"], "Rocket plan")
        # a renamed title is kept when messages change
        c = self.store.get(a["id"])
        c["messages"].append({"role": "user", "content": "more"})
        self.store.save(c)
        self.assertEqual(self.store.get(a["id"])["title"], "Rocket plan")
        self.assertTrue(self.store.delete(b["id"]))
        self.assertIsNone(self.store.get(b["id"]))
        self.assertEqual(self.store.current_id(), "")
        self.assertFalse(self.store.delete(b["id"]))

    def test_ids_cannot_escape_the_folder_and_corrupt_files_are_quarantined(self):
        self.assertIsNone(self.store.get("../../etc/passwd"))
        self.assertFalse(self.store.delete("../x"))
        with self.assertRaises(ValueError):
            self.store._path("..")
        bad = os.path.join(self.store.dir, "0" * 32 + ".json")
        with open(bad, "w") as f:
            f.write("{not json")
        self.assertEqual(self.store.list(), [])
        self.assertFalse(os.path.exists(bad), "a corrupt file is moved aside, not read")

    def test_helpers(self):
        self.assertEqual(title_from("   "), "New conversation")
        self.assertEqual(visible([{"role": "tool", "content": "x"}, {"role": "assistant", "content": ""}, {"role": "user", "content": "a"}]), [{"role": "user", "content": "a"}])


class FakeCore:
    def __init__(self, ws):
        self.ws = ws

        class G:
            @staticmethod
            def recall(q, top_k=5, touch=True):
                assert touch is False, "search must not reinforce memories"
                return [{"id": "f1", "text": "Rocket-sim uses Isp 311 s", "kind": "fact", "source": "operator"}] if "rocket" in q else []

        class P:
            memory_graph = G()

        self.p = P()

    def scheduled(self):
        return [{"id": "j1", "text": "Review rocket notes", "status": "scheduled", "next_fire": "2026-11-17T18:00:00"}]

    def audit_tail(self, n):
        return [{"seq": 1, "tool": "web_search", "outcome": "success", "ts": "2026-11-17T10:00:00"}]


class TestSearch(unittest.TestCase):
    def test_every_source_and_workspace_boundary(self):
        tmp = tempfile.mkdtemp()
        try:
            ws = os.path.join(tmp, "ws")
            os.makedirs(os.path.join(ws, "rocket", ".git"))
            os.makedirs(os.path.join(ws, "node_modules"))
            open(os.path.join(ws, "rocket", "rocket_notes.md"), "w").close()
            open(os.path.join(ws, "rocket", ".git", "rocket_secret"), "w").close()
            open(os.path.join(ws, "node_modules", "rocket.js"), "w").close()
            outside = os.path.join(tmp, "rocket_outside.txt")
            open(outside, "w").close()
            try:
                os.symlink(outside, os.path.join(ws, "rocket_link.txt"))
            except OSError:
                pass
            store = ConversationStore(os.path.join(tmp, "data"))
            store.create([{"role": "user", "content": "rocket staging"}])
            res = S.search(FakeCore(ws), store, "rocket", ws)
            kinds = {r["kind"] for r in res}
            self.assertEqual(kinds, {"conversation", "memory", "reminder", "file"})
            files = [r["detail"] for r in res if r["kind"] == "file"]
            self.assertEqual(files, [os.path.join("rocket", "rocket_notes.md")], "hidden, dependency and outside-pointing entries are skipped")
            self.assertEqual(S.search(FakeCore(ws), store, "r", ws), [], "single letters are not searched")
            act = S.search(FakeCore(ws), store, "web_search", ws)
            self.assertTrue(any(r["kind"] == "activity" for r in act))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestMemoryOps(unittest.TestCase):
    """Runs the real core in a throwaway data folder."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["PROMETHEUS_HOME"] = os.path.join(cls.tmp, "home")
        os.environ["PROMETHEUS_WORKSPACE"] = os.path.join(cls.tmp, "ws")
        os.makedirs(os.environ["PROMETHEUS_WORKSPACE"], exist_ok=True)
        import prometheus  # noqa: F401  (loaded once per test process; data dirs from the environment)

        from app.services.memory_ops import MemoryOps

        class Core:
            def __init__(self):
                import prometheus as p
                import memory_graph

                self.p = p
                self.is_untrusted = memory_graph.is_untrusted_source

        cls.core = Core()
        cls.ops = MemoryOps(cls.core)

    def test_add_similar_correct_confirm_forget_and_audit(self):
        p = self.core.p
        if not p.DATA_DIR.startswith(self.tmp):
            # The core was already imported by another test with its own data folder: run this test
            # alone in a fresh interpreter so it always runs against a throwaway folder.
            import subprocess

            if os.environ.get("RENAISSANCE_CHILD"):
                self.fail("child process still sees another data folder")
            r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"{os.path.abspath(__file__)}::TestMemoryOps"], cwd=ROOT, capture_output=True, text=True, timeout=300, env={**os.environ, "RENAISSANCE_CHILD": "1"})
            self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-2000:])
            return
        self.assertEqual(self.ops.add("x")["status"], "error")
        self.assertEqual(self.ops.add("The test rig uses a 24 V supply.", "fact")["status"], "success")
        row = next(r for r in self.ops.rows() if r["text"] == "The test rig uses a 24 V supply.")
        self.assertEqual(row["provenance"], "You")
        self.assertTrue(self.ops.similar("The test rig uses a 24 V supply.")[0]["same"])
        self.assertTrue(self.ops.similar("The test rig uses a 12 V supply.") and not self.ops.similar("The test rig uses a 12 V supply.")[0]["same"])

        # a suggestion from Prometheus is labelled as such until confirmed
        p.update_memory_fact("Prefers metric units.", kind="preference", source="assistant")
        sug = next(r for r in self.ops.rows(kinds=["preference"]) if r["text"] == "Prefers metric units.")
        self.assertEqual(sug["provenance"], "Prometheus (suggested)")
        self.assertEqual(self.ops.confirm(sug["id"])["status"], "success")
        self.assertEqual(next(r for r in self.ops.rows() if r["id"] == sug["id"])["provenance"], "Confirmed by you")

        # correcting supersedes the old fact and removes its old text from retrieval
        res = self.ops.correct(row["id"], "The test rig uses a 48 V supply.")
        self.assertEqual(res["status"], "success")
        texts = [r["text"] for r in self.ops.rows()]
        self.assertIn("The test rig uses a 48 V supply.", texts)
        self.assertNotIn("The test rig uses a 24 V supply.", texts)
        self.assertEqual(p.memory_graph.get_fact(row["id"])["status"], "superseded")
        self.assertFalse(any(d.get("content") == "Memory Fact: The test rig uses a 24 V supply." for d in p.rag_store.documents))
        self.assertNotIn("The test rig uses a 24 V supply.", p.load_memory(p.MEMORY_FILE).get("facts", []))

        # forgetting archives and removes the text everywhere it would be retrieved
        new = next(r for r in self.ops.rows() if r["text"] == "The test rig uses a 48 V supply.")
        self.assertEqual(self.ops.forget(new["id"])["status"], "success")
        self.assertNotIn("The test rig uses a 48 V supply.", [r["text"] for r in self.ops.rows()])
        self.assertEqual(p.memory_graph.recall("test rig supply", touch=False), [])
        self.assertEqual(self.ops.forget(new["id"])["status"], "error")

        # every owner action is in the hash-chained audit log, without the memory text
        tail = p.audit_log.tail(50)
        kinds = [e["tool"] for e in tail]
        for k in ("desktop.memory_add", "desktop.memory_confirm", "desktop.memory_correct", "desktop.memory_forget"):
            self.assertIn(k, kinds)
        self.assertNotIn("24 V", json.dumps([e for e in tail if e["tool"].startswith("desktop.memory")]))
        self.assertTrue(p.audit_log.verify()[0])


if __name__ == "__main__":
    unittest.main()


class TestForgeDisciplines(unittest.TestCase):
    def test_boundaries(self):
        from app.services import forge_missions as F

        ws = tempfile.mkdtemp()
        try:
            open(os.path.join(ws, "existing.md"), "w").close()
            self.assertFalse(F.decide("architect", "write_file", {"path": "x.md"}, ws)[0])
            self.assertFalse(F.decide("architect", "execute_shell", {"command": "ls"}, ws)[0])
            self.assertTrue(F.decide("architect", "read_file", {"path": "x"}, ws)[0])
            self.assertTrue(F.decide("reconstructor", "write_file", {"path": "proj/RECOVERY/ARCH.md"}, ws)[0])
            self.assertFalse(F.decide("reconstructor", "write_file", {"path": "existing.md"}, ws)[0], "never overwrite an existing file")
            self.assertFalse(F.decide("reconstructor", "write_file", {"path": "new.md", "append": True}, ws)[0])
            self.assertFalse(F.decide("reconstructor", "edit_file", {"path": "new.md"}, ws)[0])
            self.assertFalse(F.decide("reconstructor", "run_code_forge", {}, ws)[0])
            for d in ("builder", "debugger"):
                self.assertTrue(F.decide(d, "write_file", {"path": "existing.md"}, ws)[0], "builders still go to the approval card")
            log = F.MissionLog(ws)
            m = log.start("architect", "proj", "Review it", "c" * 32)
            log.count_refusal(m["id"])
            self.assertEqual(log.list()[0]["refused"], 1)
            with self.assertRaises(ValueError):
                log.start("wizard", "p", "o", "c")
            self.assertIn("proj", F.prompt("reconstructor", "proj", "recover"))
        finally:
            shutil.rmtree(ws, ignore_errors=True)


class TestExportAndWorkspace(unittest.TestCase):
    def test_backup_never_contains_keys_or_logs(self):
        import zipfile

        from app.services import export as E

        tmp = tempfile.mkdtemp()
        try:
            data = os.path.join(tmp, "data")
            os.makedirs(os.path.join(data, "conversations"))
            for name, body in ((".env", "OPENROUTER_API_KEY=sk-or-123"), ("memory_graph.json", "{}"), ("desktop_crash.log", "trace"), ("my_token.txt", "x"), ("state.json.corrupt.1", "x")):
                with open(os.path.join(data, name), "w") as f:
                    f.write(body)
            with open(os.path.join(data, "conversations", "a.json"), "w") as f:
                f.write("{}")
            res = E.export(data, os.path.join(tmp, "b.zip"))
            names = set(zipfile.ZipFile(res["path"]).namelist())
            self.assertEqual(names, {"memory_graph.json", os.path.join("conversations", "a.json"), "PROMETHEUS_BACKUP.txt"})
            self.assertEqual(res["skipped"], 4)
            with self.assertRaises(ValueError):
                E.export(data, os.path.join(data, "inside.zip"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_workspace_info_projects_git_and_boundaries(self):
        import subprocess

        from app.services import workspace_info as W

        tmp = tempfile.mkdtemp()
        try:
            ws = os.path.join(tmp, "ws")
            proj = os.path.join(ws, "proj")
            os.makedirs(proj)
            os.makedirs(os.path.join(ws, ".hidden"))
            with open(os.path.join(proj, "a.py"), "w") as f:
                f.write("x = 1\n")
            names = [p["name"] for p in W.projects(ws)]
            self.assertEqual(names, ["proj"])
            self.assertEqual(W.git_status(ws, tmp), {"error": "outside the workspace"})
            self.assertEqual(W.git_status(ws, proj), {"git": False})
            if shutil.which("git"):
                env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e")
                subprocess.run(["git", "init", "-q", proj], check=True, env=env)
                subprocess.run(["git", "-C", proj, "add", "."], check=True, env=env)
                subprocess.run(["git", "-C", proj, "-c", "commit.gpgsign=false", "commit", "-qm", "first"], check=True, env=env)
                with open(os.path.join(proj, "b.py"), "w") as f:
                    f.write("y = 2\n")
                st = W.git_status(ws, proj)
                self.assertTrue(st["git"])
                self.assertEqual([c["path"] for c in st["changes"]], ["b.py"])
                self.assertEqual(st["commits"][0]["subject"], "first")
            self.assertEqual([f["rel"] for f in W.recent_files(ws)][:1] in (["proj/b.py"], ["proj/a.py"], [os.path.join("proj", "b.py")], [os.path.join("proj", "a.py")]), True)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestReflectionSuggestions(unittest.TestCase):
    def test_suggestions_come_from_numbers(self):
        try:
            from app.ui.pages.reflection import suggestions
        except Exception as e:  # PyQt6 missing
            self.skipTest(str(e))
        out = suggestions({"web_search": {"calls": 10, "failures": 5, "refused": 0, "avg_ms": 100, "last_error": "timeout"}, "read_file": {"calls": 20, "failures": 0, "refused": 4, "avg_ms": 5}}, {"web_search": None})
        self.assertTrue(any("web_search failed 5 of 10" in s and "timeout" in s for s in out))
        self.assertTrue(any("read_file was refused 4 times" in s for s in out))
        self.assertEqual(suggestions({"x": {"calls": 2, "failures": 2}}, {}), [], "too few calls to say anything")
