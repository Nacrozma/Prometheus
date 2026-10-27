"""Tests for memory_graph.py - typed, linked, decaying memory. Standard library only."""
import datetime
import json
import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import memory_graph as mg  # noqa: E402


class Clock:
    def __init__(self, start=datetime.datetime(2026, 10, 27, 12, 0, 0)):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, days=0, hours=0):
        self.t += datetime.timedelta(days=days, hours=hours)


class GraphTestCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="memgraph_test_")
        self.path = os.path.join(self.dir, "memory_graph.json")
        self.clock = Clock()
        self.g = mg.MemoryGraph(self.path, now=self.clock)

    def reload(self):
        return mg.MemoryGraph(self.path, now=self.clock)


class ExtractionTests(unittest.TestCase):
    def names(self, text, known=()):
        return {n for n, _ in mg.extract_entities(text, known)}

    def test_capitalised_phrases_are_found_and_stopwords_are_not(self):
        got = self.names("The Robotic Arm uses an Arduino Uno and it works.")
        self.assertIn("Robotic Arm", got)
        self.assertIn("Arduino Uno", got)
        self.assertNotIn("The", got)
        self.assertNotIn("The Robotic Arm", got)

    def test_sentence_initial_common_words_are_ignored(self):
        self.assertEqual(self.names("This is fine. However it works. Maybe later."), set())

    def test_a_lone_sentence_initial_word_is_not_a_name_unless_it_looks_like_one(self):
        self.assertEqual(self.names("Lesson: calculate torque before buying servos."), set())
        self.assertEqual(self.names("Remember to charge it. Torque matters."), set())
        self.assertIn("MemoryGraph", self.names("MemoryGraph handles the dedupe."))
        self.assertIn("GPT", self.names("GPT is a model family."))
        self.assertIn("Prometheus", self.names("Prometheus will send angles.", known=["Prometheus"]))
        self.assertIn("Prometheus", self.names("we run Prometheus daily"))   # mid-sentence: accepted

    def test_wikilinks_and_tags(self):
        got = mg.extract_entities("see [[Memory Bug|the bug]] and #robotics-arm now")
        self.assertIn(("Memory Bug", "other"), got)
        self.assertIn(("robotics arm", "topic"), got)

    def test_known_names_are_matched_case_insensitively(self):
        self.assertIn("servo torque", self.names("we computed the SERVO TORQUE yesterday", known=["servo torque"]))

    def test_wikilink_traversal_is_neutralised(self):
        for n in self.names("[[../../etc/passwd]] and [[a]]b"):
            self.assertNotIn("[[", n)


class FactTests(GraphTestCase):
    def test_add_and_reload(self):
        r = self.g.add_fact("Prometheus uses a Memory Graph", entities=[{"name": "Prometheus", "type": "project"}])
        self.assertTrue(r["created"])
        g2 = self.reload()
        self.assertEqual(len(g2.facts), 1)
        self.assertEqual(g2.find_entity("prometheus")["type"], "project")

    def test_exact_duplicate_refreshes_instead_of_duplicating(self):
        a = self.g.add_fact("The arm uses MG996R servos", importance=0.4)
        self.clock.advance(days=2)
        b = self.g.add_fact("the arm uses  MG996R servos!", importance=0.9)
        self.assertEqual(a["fact_id"], b["fact_id"])
        self.assertFalse(b["created"])
        self.assertEqual(len(self.g.facts), 1)
        self.assertEqual(self.g.facts[a["fact_id"]]["importance"], 0.9)

    def test_near_duplicate_is_detected(self):
        a = self.g.add_fact("The robotic arm payload target is one hundred grams total")
        b = self.g.add_fact("The robotic arm payload target is one hundred grams total.")
        c = self.g.add_fact("The robotic arm payload target is one hundred gram total")
        self.assertEqual(a["fact_id"], b["fact_id"])
        self.assertEqual(a["fact_id"], c["fact_id"])
        self.assertEqual(len(self.g.facts), 1)

    def test_facts_that_differ_by_a_number_or_a_negation_are_kept_apart(self):
        """These look 95%+ alike as strings - merging them would silently lose information."""
        pairs = [("The robotic arm has four joints and a gripper", "The robotic arm has five joints and a gripper"),
                 ("The robotic arm payload is 100 grams total here", "The robotic arm payload is 150 grams total here"),
                 ("The servo can hold the load at the shoulder joint", "The servo cannot hold the load at the shoulder joint"),
                 ("The arm is wired to the Arduino power supply now", "The arm is not wired to the Arduino power supply now"),
                 ("alpha note one", "alpha note two")]
        for a, b in pairs:
            self.g.add_fact(a, auto_extract=False)
            self.g.add_fact(b, auto_extract=False)
        self.assertEqual(len(self.g.facts), 2 * len(pairs))

    def test_different_facts_are_not_merged(self):
        self.g.add_fact("The arm has four joints")
        self.g.add_fact("The deadline is September 28")
        self.assertEqual(len(self.g.facts), 2)

    def test_entities_are_linked_and_counted(self):
        self.g.add_fact("Robotic Arm uses Arduino Uno")
        self.g.add_fact("Robotic Arm needs a 5V supply")
        arm = self.g.neighbors("robotic arm")
        self.assertEqual(len(arm["facts"]), 2)
        self.assertEqual(arm["entity"]["mentions"], 2)
        self.assertIn(("Arduino Uno", 1), arm["related"])

    def test_relations_are_deduplicated_and_reject_self_links(self):
        self.g.add_fact("x", entities=["A", "B"], relations=[{"source": "A", "relation": "uses", "target": "B"},
                                                             {"source": "a", "relation": "USES", "target": "b"},
                                                             {"source": "A", "relation": "is", "target": "A"}])
        self.assertEqual(len(self.g.relations), 1)

    def test_invalid_input_is_rejected_or_clamped(self):
        with self.assertRaises(ValueError):
            self.g.add_fact("   ")
        r = self.g.add_fact("clamped", confidence=9, importance=-3, kind="nonsense")
        f = self.g.facts[r["fact_id"]]
        self.assertEqual((f["confidence"], f["importance"], f["kind"]), (1.0, 0.0, "fact"))

    def test_entity_count_per_fact_is_capped(self):
        self.g.add_fact("x", entities=[f"Thing{i}" for i in range(30)], auto_extract=False)
        self.assertLessEqual(len(list(self.g.facts.values())[0]["entities"]), mg.MAX_ENTITIES_PER_FACT)

    def test_supersede_and_archive_keep_the_data(self):
        a = self.g.add_fact("Deadline is October 1")["fact_id"]
        b = self.g.add_fact("Deadline is September 28")["fact_id"]
        self.assertTrue(self.g.supersede(a, b))
        self.assertEqual(self.g.facts[a]["status"], "superseded")
        self.assertEqual([r["id"] for r in self.g.recall("deadline")], [b])
        self.assertTrue(self.g.archive(b))
        self.assertEqual(self.g.recall("deadline"), [])
        self.assertIn(b, self.reload().facts)

    def test_specific_entity_type_beats_a_vague_one(self):
        self.g.get_or_create_entity("Arduino", "other")
        self.assertEqual(self.g.get_or_create_entity("arduino", "tool")["type"], "tool")
        self.assertEqual(self.g.get_or_create_entity("arduino", "other")["type"], "tool")

    def test_merge_entities_moves_facts_relations_and_names(self):
        self.g.add_fact("Arm Project is cool", entities=[{"name": "Arm Project", "type": "project"}])
        self.g.add_fact("Robotic Arm uses Servos", entities=["Robotic Arm", "Servos"],
                        relations=[{"source": "Robotic Arm", "relation": "uses", "target": "Servos"}])
        self.assertTrue(self.g.merge_entities("Arm Project", "Robotic Arm"))
        self.assertIsNone(self.g.find_entity("Arm Project") and None)  # alias now resolves to the target
        self.assertEqual(self.g.find_entity("arm project")["name"], "Robotic Arm")
        self.assertEqual(len(self.g.neighbors("Robotic Arm")["facts"]), 2)
        self.assertFalse(self.g.merge_entities("nope", "Robotic Arm"))


class RecallAndDecayTests(GraphTestCase):
    def test_recall_ranks_relevant_facts_first(self):
        self.g.add_fact("The robotic arm uses servo motors for each joint")
        self.g.add_fact("Lunch was pasta")
        self.g.add_fact("Servo torque must exceed the load")
        out = self.g.recall("which servo motors does the arm use")
        self.assertTrue(out)
        self.assertIn("servo", out[0]["text"].lower())
        self.assertNotIn("pasta", " ".join(r["text"] for r in out))

    def test_entity_name_in_query_boosts_facts(self):
        self.g.add_fact("It is sealed", entities=[{"name": "Code Forge", "type": "tool"}], auto_extract=False)
        self.assertEqual(len(self.g.recall("tell me about Code Forge")), 1)

    def test_neighbour_entities_surface_related_facts(self):
        self.g.add_fact("Arm uses Arduino", entities=["Arm", "Arduino"],
                        relations=[{"source": "Arm", "relation": "uses", "target": "Arduino"}])
        self.g.add_fact("Fits on the breadboard", entities=["Arduino"], auto_extract=False)
        texts = [r["text"] for r in self.g.recall("Arm", top_k=5)]
        self.assertIn("Fits on the breadboard", texts)

    def test_empty_or_stopword_query_returns_nothing(self):
        self.g.add_fact("something stored")
        self.assertEqual(self.g.recall(""), [])
        self.assertEqual(self.g.recall("the and of"), [])

    def test_importance_decays_without_use_and_recall_reinforces(self):
        a = self.g.add_fact("alpha note", importance=0.8, auto_extract=False)["fact_id"]
        b = self.g.add_fact("beta note", importance=0.8, auto_extract=False)["fact_id"]
        self.clock.advance(days=mg.HALF_LIFE_DAYS)
        self.assertAlmostEqual(self.g.effective_importance(self.g.facts[a]), 0.4, places=2)
        self.g.recall("alpha")                     # touches a only
        self.clock.advance(days=mg.HALF_LIFE_DAYS / 2)
        self.assertGreater(self.g.effective_importance(self.g.facts[a]), self.g.effective_importance(self.g.facts[b]))

    def test_pinned_facts_never_decay_or_get_pruned(self):
        a = self.g.add_fact("keep me forever", importance=0.9, pinned=True, auto_extract=False)["fact_id"]
        self.clock.advance(days=3650)
        self.assertEqual(self.g.effective_importance(self.g.facts[a]), 0.9)
        self.assertEqual(self.g.prune(), 0)

    def test_prune_archives_faded_facts_but_keeps_them(self):
        a = self.g.add_fact("old and unimportant note", importance=0.2, auto_extract=False)["fact_id"]
        self.clock.advance(days=400)
        b = self.g.add_fact("fresh note", importance=0.5, auto_extract=False)["fact_id"]
        self.assertEqual(self.g.prune(), 1)
        self.assertEqual((self.g.facts[a]["status"], self.g.facts[b]["status"]), ("archived", "active"))

    def test_prune_enforces_a_size_cap_by_dropping_the_weakest(self):
        ids = [self.g.add_fact(f"unique topic number {i} zeta", importance=0.1 * (i + 1) / 2, auto_extract=False)["fact_id"]
               for i in range(6)]
        self.g.prune(min_effective=0.0, max_active=4)
        active = [i for i in ids if self.g.facts[i]["status"] == "active"]
        self.assertEqual(len(active), 4)
        self.assertNotIn(ids[0], active)

    def test_standing_top_facts_exclude_untrusted_sources(self):
        self.g.add_fact("trusted note about servos", importance=0.5, source="operator", auto_extract=False)
        self.g.add_fact("web claim about servos", importance=0.99, source="web:example.com", auto_extract=False)
        self.g.add_fact("imported claim about servos", importance=0.99, source="obsidian-inbox:x.md", auto_extract=False)
        self.assertEqual(self.g.top_facts(), ["trusted note about servos"])
        self.assertEqual(len(self.g.top_facts(include_untrusted=True)), 3)

    def test_untrusted_sources_are_flagged(self):
        self.g.add_fact("web claim about servos", source="web:example.com")
        self.g.add_fact("my own note about servos", source="operator")
        flags = {r["source"]: r["untrusted"] for r in self.g.recall("servos")}
        self.assertEqual(flags, {"web:example.com": True, "operator": False})


class PersistenceTests(GraphTestCase):
    def test_corrupt_file_is_quarantined_and_graph_starts_empty(self):
        self.g.add_fact("will be corrupted")
        with open(self.path, "w") as f:
            f.write('{"entities": [')
        g2 = self.reload()
        self.assertEqual(len(g2.facts), 0)
        self.assertTrue(any(".corrupt." in n for n in os.listdir(self.dir)))
        g2.add_fact("fresh start")  # and it can save again
        self.assertEqual(len(self.reload().facts), 1)

    def test_unreadable_file_is_never_overwritten(self):
        os.remove(self.path) if os.path.exists(self.path) else None
        os.mkdir(self.path)  # exists, but opening it fails with an OSError (a directory)
        g2 = mg.MemoryGraph(self.path, now=self.clock)
        self.assertTrue(g2._unsafe_to_save)
        g2.add_fact("must not be written")
        self.assertTrue(os.path.isdir(self.path))  # untouched

    def test_non_object_json_is_left_alone(self):
        with open(self.path, "w") as f:
            f.write("[1, 2, 3]")
        g2 = self.reload()
        g2.add_fact("nope")
        with open(self.path) as f:
            self.assertEqual(json.load(f), [1, 2, 3])

    def test_malformed_records_are_dropped_not_fatal(self):
        with open(self.path, "w") as f:
            json.dump({"entities": [{"id": "a", "name": "A"}, "junk", {"id": "b"}],
                       "facts": [{"id": "f1", "text": "ok", "entities": ["a", "ghost"]}, {"id": "f2", "text": 5}],
                       "relations": [{"source": "a", "target": "ghost", "relation": "x"}]}, f)
        g2 = self.reload()
        self.assertEqual((len(g2.entities), len(g2.facts), len(g2.relations)), (1, 1, 0))
        self.assertEqual(g2.facts["f1"]["entities"], ["a"])

    def test_batch_writes_once(self):
        calls = []
        orig = mg.atomic_write_json
        mg.atomic_write_json = lambda *a, **k: (calls.append(1), orig(*a, **k))[1]
        try:
            with self.g.batch():
                for i in range(20):
                    self.g.add_fact(f"batched fact number {i} quartz")
            self.assertEqual(len(calls), 1)
        finally:
            mg.atomic_write_json = orig
        self.assertEqual(len(self.reload().facts), 20)

    def test_legacy_import_is_idempotent(self):
        legacy = ["The user likes Python", "Deadline is September 28", "The user likes Python", ""]
        self.assertEqual(self.g.import_legacy_facts(legacy), 2)
        self.assertEqual(self.g.import_legacy_facts(legacy), 0)

    def test_no_temp_files_left_behind(self):
        for i in range(5):
            self.g.add_fact(f"fact {i} onyx")
        self.assertEqual([n for n in os.listdir(self.dir) if n.endswith(".tmp")], [])


class ConcurrencyTests(GraphTestCase):
    def test_parallel_writers_lose_nothing_and_the_file_stays_valid(self):
        errors = []

        def writer(w):
            try:
                for i in range(15):
                    self.g.add_fact(f"worker {w} observation {i} marker{w}x{i}", entities=[f"Worker {w}"], auto_extract=False)
            except Exception as e:  # pragma: no cover
                errors.append(e)

        def reader():
            for _ in range(30):
                self.g.recall("worker observation")
                self.g.stats()

        threads = [threading.Thread(target=writer, args=(w,)) for w in range(6)] + \
                  [threading.Thread(target=reader) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        g2 = self.reload()
        self.assertEqual(len(g2.facts), 6 * 15)
        self.assertEqual(len(g2.entities), 6)


class SnapshotTests(GraphTestCase):
    def test_snapshot_is_a_detached_copy_with_importances(self):
        self.g.add_fact("Robotic Arm exists", entities=[{"name": "Robotic Arm", "type": "project"}])
        snap = self.g.export_snapshot()
        snap["facts"].clear()
        self.assertEqual(len(self.g.facts), 1)
        self.assertTrue(all("importance" in e for e in self.g.export_snapshot()["entities"].values()))


if __name__ == "__main__":
    unittest.main()
