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
            self.assertEqual(names, {"memory_graph.json", "conversations/a.json", "PROMETHEUS_BACKUP.txt"})  # zip entries always use /
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


class TestExperienceServices(unittest.TestCase):
    def test_mission_progress_comes_only_from_recorded_events(self):
        from app.services import forge_missions as F

        self.assertEqual(F.progress("builder", [])["reached"], 0)
        msgs = [{"role": "user", "content": "go"}]
        self.assertEqual(F.progress("builder", msgs)["reached"], 1, "started, nothing else claimed")

        def call(i, tool, args, status):
            return [{"role": "assistant", "content": "", "tool_calls": [{"id": f"c{i}", "type": "function", "function": {"name": tool, "arguments": json.dumps(args)}}]},
                    {"role": "tool", "tool_call_id": f"c{i}", "name": tool, "content": json.dumps({"status": status})}]

        msgs += call(1, "read_file", {"path": "a.py"}, "success")
        msgs += call(2, "edit_file", {"path": "a.py"}, "refused")
        p = F.progress("builder", msgs)
        self.assertEqual((p["reached"], p["refused"], p["files"]), (3, 1, [{"path": "a.py", "tool": "edit_file", "status": "refused"}]))
        self.assertEqual(p["report"], "", "no report until the mission ends with text")
        msgs += call(3, "run_code_forge", {}, "success")
        msgs.append({"role": "assistant", "content": "Done: a.py changed."})
        p = F.progress("builder", msgs)
        self.assertEqual(p["reached"], 5)
        self.assertEqual(p["report"], "Done: a.py changed.")
        arch = F.progress("architect", msgs[:3] + [{"role": "assistant", "content": "Plan: …"}])
        self.assertEqual(arch["stages"][arch["reached"] - 1], "Plan written")
        self.assertEqual(F.recommend("the importer crashes on empty files"), "debugger")
        self.assertEqual(F.recommend("review the architecture"), "architect")
        self.assertEqual(F.recommend("document this undocumented legacy tool"), "reconstructor")
        self.assertEqual(F.recommend("add a CSV export"), "builder")

    def test_vault_reader_links_backlinks_search_and_boundary(self):
        from app.services import vault_reader as V

        tmp = tempfile.mkdtemp()
        try:
            v = os.path.join(tmp, "vault")
            os.makedirs(os.path.join(v, ".obsidian"))
            os.makedirs(os.path.join(v, "sub"))
            with open(os.path.join(v, "A.md"), "w") as f:
                f.write("Links to [[B]] and [[sub/C|see C]] and [[Missing#part]].")
            with open(os.path.join(v, "B.md"), "w") as f:
                f.write("Back to [[A]]. Rocket.")
            with open(os.path.join(v, "sub", "C.md"), "w") as f:
                f.write("Nothing.")
            with open(os.path.join(v, ".obsidian", "x.md"), "w") as f:
                f.write("[[A]]")
            notes = V.notes(v)
            self.assertEqual(sorted(n["name"] for n in notes), ["A", "B", "C"])
            self.assertEqual(V.links(open(os.path.join(v, "A.md")).read()), ["B", "sub/C", "Missing"])
            self.assertEqual([n["name"] for n in V.backlinks(v, "A", notes)], ["B"])
            self.assertEqual([n["name"] for n in V.backlinks(v, "C", notes)], ["A"])
            self.assertEqual([n["name"] for n in V.search(v, "rocket", notes)], ["B"])
            with self.assertRaises(ValueError):
                V.read(v, os.path.join(tmp, "outside.md"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_project_intel_summary_tests_and_grep(self):
        from app.services import project_intel as P

        tmp = tempfile.mkdtemp()
        try:
            ws = os.path.join(tmp, "ws")
            proj = os.path.join(ws, "p")
            os.makedirs(os.path.join(proj, "tests"))
            os.makedirs(os.path.join(proj, "node_modules"))
            with open(os.path.join(proj, "main.py"), "w") as f:
                f.write("def delta_v():\n    return 1\n")
            with open(os.path.join(proj, "tests", "test_main.py"), "w") as f:
                f.write("from main import delta_v\n")
            with open(os.path.join(proj, "node_modules", "x.js"), "w") as f:
                f.write("delta_v\n")
            s = P.summary(ws, proj)
            self.assertEqual(s["tests"], [os.path.join("tests", "test_main.py")])
            self.assertIn("main.py", s["entry"])
            self.assertEqual(dict(s["languages"])["Python"], 2)
            hits = P.grep(ws, proj, "DELTA_V")
            self.assertEqual(sorted((h["rel"], h["line"]) for h in hits), [("main.py", 1), (os.path.join("tests", "test_main.py"), 1)])
            self.assertEqual(P.summary(ws, tmp), {"error": "outside the workspace"})
            self.assertEqual(P.grep(ws, proj, "x"), [], "one character is too short")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_previews_drop_markdown_and_list_items_found(self):
        from app.services.conversations import plain

        self.assertEqual(plain("**Bold** and `code`\n```py\nx = 1\n```\nend"), "Bold and code end")
        try:
            from app.ui.pages.companion import list_items
            from app.ui.pages.tasks import classify
        except Exception as e:  # PyQt6 missing
            self.skipTest(str(e))
        self.assertEqual(list_items("Plan:\n1. Add drag\n2. Write a **test**\n- Compare"), ["Add drag", "Write a test", "Compare"])
        self.assertEqual(list_items("Just one:\n- item"), [])
        import datetime as dt

        now = dt.datetime(2026, 11, 17, 12, 0)
        jobs = [{"id": "a", "status": "scheduled", "next_fire": "2026-11-17T18:00:00"}, {"id": "b", "status": "scheduled", "next_fire": "2026-11-17T09:00:00", "recurrence_seconds": 3600}, {"id": "c", "status": "scheduled", "next_fire": "2026-11-20T09:00:00"}, {"id": "d", "status": "delivered", "next_fire": "x"}]
        g = classify(jobs, now)
        self.assertEqual({k: [j["id"] for j in v] for k, v in g.items()}, {"today": ["a"], "upcoming": ["c"], "overdue": ["b"], "repeating": ["b"], "done": ["d"], "cancelled": []})


class TestSecondBirth(unittest.TestCase):
    def test_approval_describes_real_effects_and_diffs(self):
        from app.services.approval import describe

        tmp = tempfile.mkdtemp()
        try:
            with open(os.path.join(tmp, "a.py"), "w") as f:
                f.write("x = 1\ny = 2\n")
            d = describe("edit_file", {"path": "a.py", "old_string": "y = 2", "new_string": "y = 3"}, tmp)
            self.assertIn("-y = 2", d["diff"])
            self.assertIn("+y = 3", d["diff"])
            self.assertIn("found 1 time", d["what"])
            self.assertIn("undo journal", d["reversible"])
            d = describe("edit_file", {"path": "a.py", "old_string": "zzz", "new_string": "q"}, tmp)
            self.assertIn("will refuse", d["what"], "a passage that is not in the file is called out")
            d = describe("write_file", {"path": "new.md", "content": "a\nb\n"}, tmp)
            self.assertEqual((d["title"], d["preview"]), ("Create new.md", "a\nb\n"))
            d = describe("write_file", {"path": "a.py", "content": "x = 9\n"}, tmp)
            self.assertTrue(d["title"].startswith("Replace") and any(l.startswith("-y = 2") for l in d["diff"]))
            d = describe("write_file", {"path": "../escape.txt", "content": "x"}, tmp)
            self.assertIn("outside the workspace", d["what"])
            d = describe("execute_shell", {"command": "ls"}, tmp)
            self.assertEqual(d["preview"], "ls")
            self.assertIn("Not reversible", d["reversible"])
            self.assertTrue(describe("unknown_tool", {}, tmp)["if_denied"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_memory_graph_only_from_stored_entities_and_layout_is_bounded(self):
        from app.services.memory_ops import graph_data, layout

        snap = {
            "entities": {"e1": {"name": "Rocket", "type": "project", "importance": 0.9}, "e2": {"name": "Lena", "type": "person", "importance": 0.5}, "e3": {"name": "Kai", "type": "person", "importance": 0.4}, "e4": {"name": "Unused", "type": "topic", "importance": 0.9}},
            "facts": {"f1": {"status": "active", "entities": ["e1", "e2"]}, "f2": {"status": "active", "entities": ["e1", "e3"]}, "f3": {"status": "archived", "entities": ["e3", "e2"]}},
            "relations": [{"source": "e2", "relation": "owns", "target": "e1"}],
        }
        g = graph_data(snap)
        self.assertEqual({n["name"] for n in g["nodes"]}, {"Rocket", "Lena", "Kai"}, "entities in no active fact or relation are left out")
        labels = {(e["a"], e["b"]): e["label"] for e in g["edges"]}
        self.assertEqual(labels[("e1", "e2")], "owns", "a stored relation wins over 'mentioned together'")
        self.assertEqual(labels[("e1", "e3")], "mentioned together")
        self.assertNotIn(("e2", "e3"), labels, "archived facts do not link")
        pos = layout(g["nodes"], g["edges"])
        self.assertEqual(pos, layout(g["nodes"], g["edges"]), "deterministic")
        self.assertTrue(all(-1 <= x <= 1 and -1 <= y <= 1 for x, y in pos.values()))

    def test_credential_explanation_and_display_paths(self):
        from app.credentials import explain_unavailable

        for plat, word in (("windows", "Credential Manager"), ("macos", "Keychain"), ("linux", "Secret Service")):
            info = explain_unavailable(plat, "")
            self.assertIn(word, info["why"])
            self.assertIn("will not write keys to a plain file", info["meanwhile"])
        try:
            from app.ui.widgets import display_path
        except Exception as e:
            self.skipTest(str(e))
        home = os.path.expanduser("~")
        self.assertEqual(display_path(os.path.join(home, "Documents")), "~" + os.sep + "Documents")
        self.assertEqual(display_path("/opt/x"), "/opt/x")

    def test_launch_wordmark_timing(self):
        try:
            from app.ui.launch import WORDMARK_FROM, wordmark_alpha
        except Exception as e:
            self.skipTest(str(e))
        self.assertEqual(wordmark_alpha(0.5), 0.0)
        self.assertEqual(wordmark_alpha(WORDMARK_FROM), 0.0)
        self.assertEqual(wordmark_alpha(1.0), 1.0)
        self.assertTrue(0 < wordmark_alpha(0.9) < 1)
