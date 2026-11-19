"""ORBIT (Prometheus): plans, versions, edit commands, workflows, recovery and turn-taking."""

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.services import orbit as O  # noqa: E402
from app.services.orbit_voice import TurnTaker  # noqa: E402


def sample():
    return O.normalise_plan({
        "title": "Launch the site", "objective": "Ship v1",
        "phases": ["Research", "Build", "Release"],
        "tasks": [
            {"id": "r1", "title": "Survey hosting", "phase": "Research"},
            {"id": "b1", "title": "Write pages", "phase": "Build", "priority": "high"},
            {"id": "b2", "title": "Write tests", "phase": "Build"},
            {"id": "x1", "title": "Publish", "phase": "Release", "operation": "manual"},
        ],
        "deps": [{"from": "r1", "to": "b1"}, {"from": "b1", "to": "x1"}, {"from": "b2", "to": "x1"}],
        "questions": ["Which domain?"],
    })


class TestPlanModel(unittest.TestCase):
    def test_normalise_drops_cycles_unknowns_and_bounds_text(self):
        p = O.normalise_plan({"title": "x" * 500, "tasks": [{"id": "a", "title": "A"}, {"id": "b", "title": "B"}, {"title": ""}, "junk"],
                              "deps": [["a", "b"], ["b", "a"], ["a", "zzz"], ["a", "a"]], "priority": "urgent"})
        self.assertEqual(len(p["title"]), 120)
        self.assertEqual([t["id"] for t in p["tasks"]], ["a", "b"])
        self.assertEqual(p["deps"], [{"from": "a", "to": "b"}])
        self.assertTrue(all(t["status"] == "proposed" for t in p["tasks"]), "plans from Prometheus are proposals")

    def test_extract_complete_and_partial_blocks(self):
        reply = 'Here is a plan.\n```orbit-plan {"title":"T","phases":["A"],"tasks":[{"id":"1","title":"Do it","phase":"A"}]}```\nThoughts?'
        self.assertEqual(O.extract_plan(reply)["tasks"][0]["title"], "Do it")
        self.assertEqual(O.strip_plan_blocks(reply), "Here is a plan.\n\nThoughts?")
        self.assertIsNone(O.extract_plan("```orbit-plan {not json}```"))
        part = O.partial_plan('ok ```orbit-plan {"phases":["A","B"],"tasks":[{"id":"1","title":"First","phase":"A"},{"id":"2","title":"Sec')
        self.assertEqual(part, {"phases": ["A", "B"], "tasks": ["First"]})
        self.assertEqual(O.strip_plan_blocks('Talking ```orbit-plan {"pha'), "Talking")

    def test_edits(self):
        p = sample()
        p, _ = O.edit(p, "add_task", title="Buy domain", phase="Release")
        self.assertEqual(O.task(p, "buy domain")["status"], "confirmed")
        p, _ = O.edit(p, "rename_task", ref="Survey hosting", title="Compare hosts")
        p, _ = O.edit(p, "set_priority", ref="Write tests", priority="high")
        p, _ = O.edit(p, "move_to_phase", ref="Write tests", phase="QA")
        self.assertIn("QA", p["phases"])
        p, _ = O.edit(p, "move_phase_before", phase="QA", other="Build")
        self.assertLess(p["phases"].index("QA"), p["phases"].index("Build"))
        p, _ = O.edit(p, "move_before", ref="Write tests", other="Write pages")
        self.assertEqual([t["title"] for t in p["tasks"]].index("Write tests") + 1, [t["title"] for t in p["tasks"]].index("Write pages"))
        with self.assertRaises(O.PlanError):
            O.edit(p, "add_dep", before="Publish", after="Compare hosts")  # Compare → Write pages → Publish: a loop
        with self.assertRaises(O.PlanError):
            O.edit(p, "remove_task", ref="write")  # ambiguous fragment: never guess
        p, _ = O.edit(p, "remove_task", ref="Write pages")
        self.assertFalse(any("b1" in (d["from"], d["to"]) for d in p["deps"]), "removing a task removes its links")
        with self.assertRaises(O.PlanError):
            O.edit(p, "set_priority", ref="Publish", priority="urgent")

    def test_spoken_commands(self):
        p = sample()
        self.assertEqual(O.parse_command("Move Release before Build.", p), {"op": "move_phase_before", "phase": "Release", "other": "Build"})
        self.assertEqual(O.parse_command("add task Check links to Release", p), {"op": "add_task", "title": "Check links", "phase": "Release"})
        self.assertEqual(O.parse_command("make write tests high priority", p)["priority"], "high")
        self.assertEqual(O.parse_command("Publish must come after Survey hosting", p), {"op": "add_dep", "before": "Survey hosting", "after": "Publish"})
        self.assertEqual(O.parse_command("undo that", p), {"undo": True})
        self.assertEqual(O.parse_command("Stop", None), {"control": "stop_speaking"})
        self.assertEqual(O.parse_command("pause the workflow", p), {"control": "pause"})
        self.assertIsNone(O.parse_command("What should we do about hosting costs?", p), "questions go to Prometheus")
        self.assertIsNone(O.parse_command("make it faster high priority", p), "no task called that: not an edit")

    def test_versions_compare_and_session_store(self):
        with tempfile.TemporaryDirectory() as d:
            store = O.OrbitStore(d)
            s = O.new_session("Site")
            O.add_version(s, sample(), "prometheus", "Proposed")
            new, why = O.edit(O.current_plan(s), "rename_task", ref="Publish", title="Go live")
            O.add_version(s, new, "you", why)
            self.assertEqual([v["author"] for v in s["plan_versions"]], ["prometheus", "you"])
            self.assertIn("renamed: Publish → Go live", O.compare(s["plan_versions"][0]["plan"], s["plan_versions"][1]["plan"]))
            self.assertTrue(store.save(s))
            back = store.get(s["id"])
            self.assertEqual(back["active_version"], 2)
            self.assertEqual([r["id"] for r in store.list()], [s["id"]])
            self.assertIsNone(store.get("../../etc/passwd"))
            with open(os.path.join(d, "orbit", s["id"] + ".json"), "w") as f:
                f.write("{broken")
            self.assertIsNone(store.get(s["id"]), "a damaged session is quarantined, not half-read")
            self.assertTrue(any(n.startswith(s["id"]) and n != s["id"] + ".json" for n in os.listdir(os.path.join(d, "orbit"))) or not os.path.exists(os.path.join(d, "orbit", s["id"] + ".json")))


class TestWorkflow(unittest.TestCase):
    def test_order_states_and_dependencies(self):
        p = sample()
        wf = O.make_workflow(p, 1, "approval_first")
        self.assertEqual([n["id"] for n in wf["nodes"]], ["r1", "b1", "b2", "x1"])
        self.assertEqual({n["id"]: n["status"] for n in wf["nodes"]}, {"r1": "ready", "b1": "waiting", "b2": "ready", "x1": "waiting"})
        O.transition(wf, "r1", "running")
        with self.assertRaises(ValueError):
            O.transition(wf, "x1", "running")  # waiting for its dependencies: cannot start
        O.transition(wf, "r1", "completed")
        self.assertEqual(O._node_status(wf, "b1") if hasattr(O, "_node_status") else next(n for n in wf["nodes"] if n["id"] == "b1")["status"], "ready")
        O.transition(wf, "b1", "running")
        O.transition(wf, "b1", "failed", "boom")
        self.assertEqual(next(n for n in wf["nodes"] if n["id"] == "x1")["status"], "blocked")
        self.assertEqual(wf["state"], "failed")
        O.transition(wf, "b1", "ready")  # retry
        self.assertEqual(next(n for n in wf["nodes"] if n["id"] == "x1")["status"], "waiting")
        with self.assertRaises(ValueError):
            O.transition(wf, "r1", "running")  # completed is final

    def test_autonomy_never_skips_manual_and_balanced_holds_changes(self):
        p = sample()
        p, _ = O.edit(p, "set_operation", ref="Write tests", operation="forge:builder")
        nodes = {n["id"]: n for n in O.make_workflow(p, 1)["nodes"]}
        af = O.make_workflow(p, 1, "approval_first")
        bal = O.make_workflow(p, 1, "balanced")
        adv = O.make_workflow(p, 1, "advanced", ["think", "change"])
        self.assertTrue(all(O.needs_go_ahead(af, n) for n in nodes.values()))
        self.assertFalse(O.needs_go_ahead(bal, nodes["r1"]))
        self.assertTrue(O.needs_go_ahead(bal, nodes["b2"]), "balanced: file changes wait for you")
        self.assertFalse(O.needs_go_ahead(adv, nodes["b2"]))
        self.assertTrue(all(O.needs_go_ahead(w, nodes["x1"]) for w in (af, bal, adv)), "a manual step is always yours")

    def test_recovery_pauses_and_never_reruns(self):
        with tempfile.TemporaryDirectory() as d:
            store = O.OrbitStore(d)
            s = O.new_session("x")
            O.add_version(s, sample(), "you", "v1")
            s["workflow"] = O.make_workflow(O.current_plan(s), 1, "balanced")
            O.transition(s["workflow"], "r1", "running")
            store.save(s)
            back = store.get(s["id"])
            n = next(n for n in back["workflow"]["nodes"] if n["id"] == "r1")
            self.assertEqual(n["status"], "paused")
            self.assertIn("not repeated", n["history"][-1]["event"])
            self.assertTrue(back["workflow"]["paused"])
            self.assertIsNone(O.next_node(back["workflow"]), "nothing starts by itself after a restart")
            self.assertEqual(back["events"][-1]["kind"], "session.restored")

    def test_no_secret_or_tool_text_in_plan_fields(self):
        p = O.normalise_plan({"title": "t", "tasks": [{"title": "a", "operation": "execute_shell rm -rf /"}]})
        self.assertEqual(p["tasks"][0]["operation"], "assistant", "unknown operations never map to a raw tool")
        json.dumps(p)


class TestTurnTaking(unittest.TestCase):
    def run_levels(self, tt, seq, dt=0.04):
        t, events = 0.0, []
        for level, secs in seq:
            for _ in range(int(secs / dt)):
                e = tt.feed(level, t)
                if e:
                    events.append((e, round(t, 2)))
                t += dt
        return events

    def test_end_of_turn_after_speech_then_silence(self):
        ev = self.run_levels(TurnTaker(silence=1.0), [(0.01, 1.0), (0.4, 1.5), (0.01, 1.5)])
        self.assertEqual([e for e, _ in ev], ["speech", "end"])

    def test_cough_is_not_a_turn_and_pauses_inside_speech_do_not_end_it(self):
        ev = self.run_levels(TurnTaker(silence=1.0), [(0.01, 0.5), (0.5, 0.2), (0.01, 1.5)])
        self.assertNotIn("end", [e for e, _ in ev])
        ev = self.run_levels(TurnTaker(silence=1.0), [(0.4, 1.0), (0.01, 0.6), (0.4, 1.0), (0.01, 1.2)])
        self.assertEqual([e for e, _ in ev].count("end"), 1)

    def test_idle_timeout_closes_the_microphone(self):
        ev = self.run_levels(TurnTaker(idle_timeout=3.0), [(0.0, 4.0)])
        self.assertEqual([e for e, _ in ev], ["idle"])

    def test_threshold_follows_the_room(self):
        tt = TurnTaker(sensitivity=0.5)
        self.run_levels(tt, [(0.12, 3.0)])
        self.assertGreater(tt.threshold(), 0.12, "steady background noise raises the bar instead of counting as speech")


if __name__ == "__main__":
    unittest.main()
