"""Tests for obsidian_memory.py - the vault exporter. Standard library only."""
import datetime
import json
import os
import re
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import memory_graph as mg  # noqa: E402
import obsidian_memory as om  # noqa: E402

NOW = datetime.datetime(2026, 10, 27, 12, 0, 0)


class Clock:
    def __init__(self):
        self.t = datetime.datetime(2026, 10, 25, 9, 0, 0)

    def __call__(self):
        return self.t

    def advance(self, days=1):
        self.t += datetime.timedelta(days=days)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def all_files(base):
    out = []
    for d, _, files in os.walk(base):
        for f in files:
            out.append(os.path.join(d, f))
    return sorted(out)


class VaultCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="obsidian_test_")
        self.vault = os.path.join(self.tmp, "vault")
        os.makedirs(os.path.join(self.vault, ".obsidian"))
        self.clock = Clock()
        self.g = mg.MemoryGraph(os.path.join(self.tmp, "graph.json"), now=self.clock)
        self.m = om.ObsidianMirror(self.vault)
        self.root = self.m.root

    def seed(self):
        self.g.add_fact("Robotic Arm uses Arduino Uno and servos", entities=[
            {"name": "Robotic Arm", "type": "project"}, {"name": "Arduino Uno", "type": "tool"}],
            relations=[{"source": "Robotic Arm", "relation": "uses", "target": "Arduino Uno"}], importance=0.8)
        self.clock.advance(1)
        self.g.add_fact("Prometheus stores memory in a graph", entities=[{"name": "Prometheus", "type": "project"}])
        self.g.add_fact("Lesson: calculate torque before buying servos", kind="lesson",
                        entities=[{"name": "Robotic Arm", "type": "project"}])

    def export(self, **kw):
        return self.m.export(self.g.export_snapshot(), now=NOW, **kw)

    def note(self, rel):
        return read(os.path.join(self.root, *rel.split("/")))


class NameTests(unittest.TestCase):
    def test_forbidden_characters_dots_and_traversal(self):
        self.assertEqual(om.safe_note_name("a/b\\c:d*e?f\"g<h>i|j#k^l[m]n"), "a b c d e f g h i j k l m n")
        self.assertEqual(om.safe_note_name("../../etc/passwd"), "etc passwd")
        self.assertEqual(om.safe_note_name("..."), "Untitled")
        self.assertEqual(om.safe_note_name(""), "Untitled")
        self.assertEqual(om.safe_note_name(None), "Untitled")
        self.assertEqual(om.safe_note_name("name.  "), "name")

    def test_windows_device_names_and_length(self):
        self.assertEqual(om.safe_note_name("CON"), "CON_")
        self.assertEqual(om.safe_note_name("nul.txt"), "nul.txt_")
        self.assertLessEqual(len(om.safe_note_name("x" * 500)), 80)

    def test_unicode_survives(self):
        self.assertEqual(om.safe_note_name("Café ☀ Prometheus 火"), "Café ☀ Prometheus 火")

    def test_names_are_unique_and_stable(self):
        n = om.Names("Prometheus")
        a = n.assign("ent:1", "Index")        # reserved stem
        b = n.assign("ent:2", "C/D")
        c = n.assign("ent:3", "C D")          # collides with the sanitised name above
        self.assertEqual((a, b, c), ("Index (2)", "C D", "C D (2)"))
        again = om.Names("Prometheus", n.map)
        self.assertEqual(again.assign("ent:3", "completely different"), "C D (2)")
        self.assertEqual(again.assign("ent:9", "C D"), "C D (3)")


class FrontmatterTests(unittest.TestCase):
    def test_split_and_merge_preserves_user_properties(self):
        text = '---\nprometheus_id: "x"\ntags: [mine, prometheus]\nmood: happy\nlist_prop:\n  - a\n  - b\n---\nbody'
        props, rest = om.split_frontmatter(text)
        self.assertEqual(rest, "body")
        out = om.render_frontmatter({"prometheus_id": "x", "type": "entity"}, ["prometheus", "new"], [], props)
        self.assertIn('tags: ["prometheus", "new", "mine"]', out)
        self.assertIn("mood: happy", out)
        self.assertIn("  - a\n  - b", out)
        self.assertEqual(out.count("prometheus_id"), 1)

    def test_no_frontmatter(self):
        self.assertEqual(om.split_frontmatter("just text"), (None, "just text"))
        self.assertEqual(om.split_frontmatter("---\nnever closed\n"), (None, "---\nnever closed\n"))

    def test_values_are_yaml_safe(self):
        out = om.render_frontmatter({"title": 'He said "hi": [x]\nnewline', "n": 3, "day": "2026-10-27"}, [], [], None)
        self.assertIn('title: "He said \\"hi\\": [x]\\nnewline"', out)
        self.assertIn("n: 3", out)
        self.assertIn("day: 2026-10-27", out)


class ExportTests(VaultCase):
    def test_structure_and_content(self):
        self.seed()
        rep = self.export()
        self.assertTrue(rep.ok, rep.errors)
        for rel in ("Index.md", "README.md", "Lessons.md", "Current Task.md",
                    "Entities/Robotic Arm.md", "Entities/Arduino Uno.md", "Entities/Prometheus.md"):
            self.assertTrue(os.path.exists(os.path.join(self.root, rel)), rel)
        arm = self.note("Entities/Robotic Arm.md")
        self.assertTrue(arm.startswith("---\n"))
        self.assertIn('entity_type: "project"', arm)
        self.assertIn("[[Prometheus/Entities/Arduino Uno|Arduino Uno]]", arm)
        self.assertIn("**uses** → [[Prometheus/Entities/Arduino Uno|Arduino Uno]]", arm)
        self.assertIn("prometheus/project", arm)
        self.assertEqual(arm.count(om.BEGIN), 1)
        self.assertEqual(arm.count(om.END), 1)
        self.assertIn("calculate torque", self.note("Lessons.md"))

    def test_every_wikilink_points_at_a_real_note(self):
        self.seed()
        self.g.add_fact("Prometheus drives the Robotic Arm over Serial", entities=["Prometheus", "Robotic Arm", "Serial"])
        self.export()
        link = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
        checked = 0
        for path in all_files(self.root):
            if path.endswith(".md"):
                for target in link.findall(read(path)):
                    self.assertTrue(os.path.exists(os.path.join(self.vault, *target.split("/")) + ".md"),
                                    f"dangling link {target!r} in {path}")
                    checked += 1
        self.assertGreater(checked, 15)

    def test_timeline_is_chained_by_date(self):
        self.seed()
        self.export()
        self.assertIn("2026-10-26", self.note("Timeline/2026-10-25.md"))
        self.assertIn("2026-10-25", self.note("Timeline/2026-10-26.md"))

    def test_second_export_changes_nothing(self):
        self.seed()
        self.export()
        before = {p: os.stat(p).st_mtime_ns for p in all_files(self.root)}
        time.sleep(0.02)
        rep = self.export()
        self.assertEqual((rep.created, rep.updated, rep.conflicts), ([], [], []))
        self.assertGreater(len(rep.unchanged), 5)
        self.assertEqual({p: os.stat(p).st_mtime_ns for p in all_files(self.root)}, before)

    def test_only_changed_notes_are_rewritten(self):
        self.seed()
        self.export()
        self.g.add_fact("Prometheus now has an Obsidian exporter", entities=["Prometheus"])
        rep = self.export()
        self.assertIn("Entities/Prometheus.md", rep.updated)
        self.assertNotIn("Entities/Arduino Uno.md", rep.updated)

    def test_unverified_sources_are_flagged(self):
        self.g.add_fact("Servo X is great", entities=["Servo X"], source="web:example.com")
        self.export()
        self.assertIn("unverified source", self.note("Entities/Servo X.md"))

    def test_superseded_facts_move_to_history(self):
        a = self.g.add_fact("Deadline is October 1", entities=["Deadline"])["fact_id"]
        b = self.g.add_fact("Deadline is September 28", entities=["Deadline"])["fact_id"]
        self.g.supersede(a, b)
        self.export()
        note = self.note("Entities/Deadline.md")
        self.assertIn("~~Deadline is October 1~~", note)
        self.assertIn("## History", note)

    def test_skills_and_task_notes(self):
        rep = self.m.export(self.g.export_snapshot(), now=NOW,
                            skills=[{"name": "unit_converter", "description": "Converts units", "version": 2,
                                     "status": "active", "tests": "3/3 passing", "updated": "2026-10-27T10:00:00",
                                     "history": [{"version": 1, "status": "superseded", "created": "2026-10-26T10:00:00"}]}],
                            task_state={"goal": "Build the arm", "status": "in_progress",
                                        "steps": ["CAD", "print"], "notes": [{"note": "buy servos"}]})
        self.assertTrue(rep.ok, rep.errors)
        self.assertIn("Converts units", self.note("Skills/unit_converter.md"))
        self.assertIn("v2", self.note("Skills/unit_converter.md"))
        task = self.note("Current Task.md")
        self.assertIn("**Goal:** Build the arm", task)
        self.assertIn("- [ ] CAD", task)
        self.assertIn("buy servos", task)

    def test_a_skill_that_is_also_an_entity_is_one_note_not_two(self):
        self.g.add_fact("Skill 'adder' installed", entities=[{"name": "adder", "type": "skill"}], auto_extract=False)
        skill = {"name": "adder", "description": "Adds two numbers", "version": 2, "status": "active",
                 "tests": "2/2 passing", "updated": "2026-10-27T10:00:00",
                 "history": [{"version": 1, "status": "superseded", "created": "2026-10-26T10:00:00"}]}
        rep = self.m.export(self.g.export_snapshot(), now=NOW, skills=[skill])
        self.assertTrue(rep.ok, rep.errors)
        self.assertFalse(os.path.exists(os.path.join(self.root, "Skills", "adder.md")))
        note = self.note("Entities/adder.md")
        self.assertIn("## Skill", note)
        self.assertIn("Adds two numbers", note)
        self.assertIn("**Version** v2", note)
        self.assertIn("skill_version: 2", note)
        self.assertIn("prometheus/skill", note)
        self.assertIn("[[Prometheus/Entities/adder|adder]]", self.note("Index.md"))   # the Index links the merged note
        for path in all_files(self.root):                                              # and no link anywhere dangles
            if path.endswith(".md"):
                for target in re.findall(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]", read(path)):
                    self.assertTrue(os.path.exists(os.path.join(self.vault, *target.split("/")) + ".md"), target)

    def test_a_skill_without_an_entity_still_gets_its_own_note(self):
        skill = {"name": "orphan_skill", "description": "No entity", "version": 1, "status": "active",
                 "tests": "1/1 passing", "updated": "2026-10-27T10:00:00", "history": []}
        self.m.export(self.g.export_snapshot(), now=NOW, skills=[skill])
        self.assertIn("No entity", self.note("Skills/orphan_skill.md"))

    def test_a_large_graph_exports_quickly(self):
        with self.g.batch():
            for i in range(300):
                self.g.add_fact(f"Component C{i} connects to Hub H{i % 20} number {i}", entities=[f"C{i}", f"H{i % 20}"], auto_extract=False)
        start = time.time()
        rep = self.export()
        self.assertTrue(rep.ok, rep.errors)
        self.assertLess(time.time() - start, 10)
        self.assertGreater(len(rep.created), 300)


class UserEditTests(VaultCase):
    def test_text_below_the_block_survives_re_export(self):
        self.seed()
        self.export()
        path = os.path.join(self.root, "Entities", "Robotic Arm.md")
        write(path, read(path) + "I think the elbow needs a bearing.\n")
        self.g.add_fact("Robotic Arm gripper is a hobby servo", entities=["Robotic Arm"])
        rep = self.export()
        self.assertIn("Entities/Robotic Arm.md", rep.updated)
        text = read(path)
        self.assertIn("I think the elbow needs a bearing.", text)
        self.assertIn("hobby servo", text)
        self.assertEqual(text.count(om.BEGIN), 1)

    def test_user_frontmatter_properties_and_tags_survive(self):
        self.seed()
        self.export()
        path = os.path.join(self.root, "Entities", "Robotic Arm.md")
        write(path, read(path).replace("\n---\n", '\nmood: excited\ntags: ["prometheus", "my-own-tag"]\n---\n', 1))
        self.g.add_fact("Robotic Arm has four joints", entities=["Robotic Arm"])
        self.export()
        text = read(path)
        self.assertIn("mood: excited", text)
        self.assertIn("my-own-tag", text)
        self.assertIn("prometheus/project", text)
        self.assertEqual(text.count("\ntags:"), 1)

    def test_editing_inside_the_block_is_a_conflict_and_the_note_is_left_alone(self):
        self.seed()
        self.export()
        path = os.path.join(self.root, "Entities", "Robotic Arm.md")
        edited = read(path).replace("## Facts", "## Facts (I renamed this)")
        write(path, edited)
        self.g.add_fact("Robotic Arm weighs 400 grams", entities=["Robotic Arm"])
        rep = self.export()
        self.assertIn("Entities/Robotic Arm.md", rep.conflicts)
        self.assertEqual(read(path), edited)

    def test_force_overwrites_the_block_but_keeps_the_tail(self):
        self.seed()
        self.export()
        path = os.path.join(self.root, "Entities", "Robotic Arm.md")
        write(path, read(path).replace("## Facts", "## Facts (edited)") + "\nMY TAIL\n")
        rep = self.export(force=True)
        self.assertIn("Entities/Robotic Arm.md", rep.updated)
        text = read(path)
        self.assertNotIn("(edited)", text)
        self.assertIn("MY TAIL", text)

    def test_removed_markers_are_reported_not_clobbered(self):
        self.seed()
        self.export()
        path = os.path.join(self.root, "Entities", "Prometheus.md")
        write(path, "I replaced the whole note.\n")
        rep = self.export(force=True)
        self.assertTrue(any("Entities/Prometheus.md" in c for c in rep.conflicts))
        self.assertEqual(read(path), "I replaced the whole note.\n")

    def test_crlf_line_endings_do_not_cause_false_conflicts(self):
        self.seed()
        self.export()
        for path in all_files(self.root):
            if path.endswith(".md"):
                content = read(path)  # read BEFORE opening for write (opening truncates)
                with open(path, "w", encoding="utf-8", newline="\r\n") as f:
                    f.write(content)
        rep = self.export()
        self.assertEqual(rep.conflicts, [])

    def test_corrupt_manifest_adopts_identical_notes_and_protects_others(self):
        self.seed()
        self.export()
        write(self.m.manifest_path, "{ not json")
        path = os.path.join(self.root, "Entities", "Prometheus.md")
        write(path, read(path).replace("## Facts", "## Facts (mine)"))
        rep = self.export()
        self.assertIn("Entities/Prometheus.md", rep.conflicts)       # edited: protected even without a manifest
        self.assertIn("Entities/Robotic Arm.md", rep.unchanged)      # untouched: safely adopted
        self.assertEqual(rep.errors, [])

    def test_your_other_notes_are_never_touched(self):
        mine = os.path.join(self.vault, "My Note.md")
        deep = os.path.join(self.vault, "Projects", "Robotic Arm.md")  # same name as an entity!
        write(mine, "private thoughts\n")
        write(deep, "my own Robotic Arm note\n")
        self.seed()
        self.export()
        self.assertEqual(read(mine), "private thoughts\n")
        self.assertEqual(read(deep), "my own Robotic Arm note\n")
        self.assertIn("[[Prometheus/Entities/Arduino Uno|", self.note("Entities/Robotic Arm.md"))  # path-qualified, can't hit Projects/


class StaleTests(VaultCase):
    def test_untouched_stale_notes_are_deleted(self):
        self.g.add_fact("Old Thing existed", entities=["Old Thing"])
        self.g.add_fact("Keeper exists", entities=["Keeper"])
        self.export()
        self.assertTrue(os.path.exists(os.path.join(self.root, "Entities", "Old Thing.md")))
        self.g.merge_entities("Old Thing", "Keeper")
        rep = self.export()
        self.assertIn("Entities/Old Thing.md", rep.deleted)
        self.assertFalse(os.path.exists(os.path.join(self.root, "Entities", "Old Thing.md")))

    def test_stale_notes_you_wrote_in_are_kept(self):
        self.g.add_fact("Old Thing existed", entities=["Old Thing"])
        self.g.add_fact("Keeper exists", entities=["Keeper"])
        self.export()
        path = os.path.join(self.root, "Entities", "Old Thing.md")
        write(path, read(path) + "my research notes\n")
        self.g.merge_entities("Old Thing", "Keeper")
        rep = self.export()
        self.assertIn("Entities/Old Thing.md", rep.stale_kept)
        self.assertIn("my research notes", read(path))


class SafetyTests(VaultCase):
    def test_hostile_names_and_text_cannot_escape_or_break_notes(self):
        evil = "<!-- prometheus:end -->\n---\n```\n[[../../outside|x]] <script>alert(1)</script> #sneaky ![[x]]"
        self.g.add_fact("Weird: " + evil, entities=[{"name": "../../evil", "type": "tool"}, {"name": "CON", "type": "tool"},
                                                      {"name": "Index", "type": "tool"}], source="web:evil.example")
        before_outside = set(all_files(self.tmp)) - set(all_files(self.vault))
        rep = self.export()
        self.assertTrue(rep.ok, rep.errors)
        for path in all_files(self.vault):  # nothing was written outside <vault>/Prometheus (besides the .obsidian marker)
            # realpath on both sides: Windows may report the temp folder by its 8.3 short name.
            self.assertTrue(os.path.realpath(path).startswith(os.path.realpath(self.root)) or ".obsidian" in path, path)
        self.assertEqual(set(all_files(self.tmp)) - set(all_files(self.vault)), before_outside)
        for name in ("evil.md", "CON_.md", "Index (2).md"):
            self.assertTrue(os.path.exists(os.path.join(self.root, "Entities", name)), name)
        text = self.note("Entities/evil.md")
        self.assertEqual(text.count(om.BEGIN), 1)
        self.assertEqual(text.count(om.END), 1)
        self.assertNotIn("<script", text)
        self.assertNotIn("[[../", text)
        self.assertNotIn("![[", text)
        self.assertNotRegex(text, r"(?<!\\)#sneaky")
        self.assertEqual(text.split("\n")[0], "---")

    def test_vault_must_exist_and_not_be_a_root_or_home(self):
        with self.assertRaises(om.VaultError):
            om.ObsidianMirror(os.path.join(self.tmp, "nope"))
        with self.assertRaises(om.VaultError):
            om.ObsidianMirror("")
        with self.assertRaises(om.VaultError):
            om.ObsidianMirror(os.path.abspath(os.sep))
        with self.assertRaises(om.VaultError):
            om.ObsidianMirror(os.path.expanduser("~"))

    def test_root_folder_name_is_sanitised(self):
        m = om.ObsidianMirror(self.vault, root_name="../../Elsewhere")
        self.assertEqual(os.path.dirname(m.root), os.path.realpath(self.vault))

    def test_a_symlinked_folder_cannot_redirect_writes_outside(self):
        outside = os.path.join(self.tmp, "outside")
        os.makedirs(outside)
        os.makedirs(self.root)
        try:
            os.symlink(outside, os.path.join(self.root, "Entities"))
        except (OSError, NotImplementedError):
            self.skipTest("symlinks not available on this platform")
        self.seed()
        rep = self.export()
        self.assertEqual(os.listdir(outside), [])
        self.assertTrue(rep.errors)  # the entity notes were refused

    def test_unsafe_relative_paths_are_rejected(self):
        for rel in ("../x.md", "a/../../x.md", "/abs.md", "a//b.md", ""):
            with self.assertRaises(om.VaultError):
                self.m._safe_path(rel)

    def test_missing_obsidian_marker_is_reported_not_fatal(self):
        bare = os.path.join(self.tmp, "bare")
        os.makedirs(bare)
        rep = om.ObsidianMirror(bare).export(self.g.export_snapshot(), now=NOW)
        self.assertFalse(rep.vault_marker)
        self.assertTrue(rep.ok)


class InboxTests(VaultCase):
    def inbox(self, name, text):
        write(os.path.join(self.root, "Inbox", name), text)

    def test_notes_become_untrusted_facts_and_are_moved(self):
        self.inbox("idea.md", "---\ntags: [robotics, #ideas]\n---\n# Heading ignored\n\n"
                              "- Use MG996R servos for the [[Robotic Arm]] shoulder\n- [ ] Order a 5V supply for the arm\n\n"
                              "A loose paragraph about torque calculations\nthat spans two lines.\n\n"
                              "```\ncode is dropped\n```\n<!-- hidden -->\n<script>x</script>\nshort\n")
        res = self.m.ingest_inbox(self.g)
        self.assertEqual((res["files"], res["facts"], res["errors"]), (1, 3, []))
        texts = [f["text"] for f in self.g.facts.values()]
        self.assertTrue(any("MG996R" in t for t in texts))
        self.assertTrue(any("torque calculations that spans two lines" in t for t in texts))
        self.assertFalse(any("code is dropped" in t or "hidden" in t or "<script" in t for t in texts))
        self.assertTrue(all(f["source"].startswith("obsidian-inbox:") for f in self.g.facts.values()))
        self.assertTrue(self.g.find_entity("Robotic Arm"))
        self.assertTrue(self.g.find_entity("robotics"))
        self.assertTrue(all(r["untrusted"] for r in self.g.recall("servos", top_k=5)))
        self.assertFalse(os.path.exists(os.path.join(self.root, "Inbox", "idea.md")))
        self.assertTrue(os.path.exists(os.path.join(self.root, "Inbox", "_processed", "idea.md")))

    def test_second_run_does_nothing(self):
        self.inbox("a.md", "- a perfectly fine fact here\n")
        self.m.ingest_inbox(self.g)
        res = self.m.ingest_inbox(self.g)
        self.assertEqual((res["files"], res["facts"]), (0, 0))

    def test_dry_run_changes_nothing(self):
        self.inbox("a.md", "- a perfectly fine fact here\n")
        res = self.m.ingest_inbox(self.g, dry_run=True)
        self.assertEqual((res["files"], res["facts"]), (1, 1))
        self.assertEqual(len(self.g.facts), 0)
        self.assertTrue(os.path.exists(os.path.join(self.root, "Inbox", "a.md")))

    def test_oversized_and_non_markdown_and_symlinked_files_are_skipped(self):
        self.inbox("huge.md", "- fact line number one\n" * 6000)
        self.inbox("notes.txt", "- ignored because it is not markdown\n")
        outside = os.path.join(self.tmp, "secret.md")
        write(outside, "- secret outside the vault\n")
        try:
            os.symlink(outside, os.path.join(self.root, "Inbox", "link.md"))
        except (OSError, NotImplementedError):
            pass
        res = self.m.ingest_inbox(self.g)
        self.assertEqual(res["files"], 0)
        self.assertTrue(any("huge.md" in s for s in res["skipped"]))
        self.assertEqual(len(self.g.facts), 0)

    def test_fact_count_per_file_is_capped(self):
        self.inbox("many.md", "\n".join(f"- unique statement number {i} about subject {i * 7}" for i in range(200)))
        res = self.m.ingest_inbox(self.g)
        self.assertEqual(res["facts"], om.MAX_INBOX_FACTS_PER_FILE)

    def test_parse_inbox_note_directly(self):
        units, tags = om.parse_inbox_note("---\ntags: a, b\n---\nPlain paragraph here.\n\n1. numbered item text\n")
        self.assertEqual(units, ["Plain paragraph here.", "numbered item text"])
        self.assertEqual(tags, ["a", "b"])


if __name__ == "__main__":
    unittest.main()
