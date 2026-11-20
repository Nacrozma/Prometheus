"""ORBIT universe (Prometheus): stages from real state, panels with real content only, real connections,
layout clamping, the animation state engine, effects, adaptive quality and the optional sounds."""

import os
import sys
import tempfile
import math
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.services import orbit as O  # noqa: E402
from app.services import orbit_motion as M  # noqa: E402
from app.services import orbit_sound as SND  # noqa: E402
from app.services import orbit_space as SP  # noqa: E402


def session_with_plan():
    s = O.new_session("Site")
    s["conversation_id"] = "c1"
    O.add_version(s, O.normalise_plan({"title": "Site", "objective": "Ship", "brief": "A small site.", "ideas": ["Static", "Blog"],
                                       "phases": ["A", "B"], "tasks": [{"id": "a1", "title": "Write", "phase": "A"}, {"id": "b1", "title": "Ship", "phase": "B", "operation": "manual"}],
                                       "deps": [{"from": "a1", "to": "b1"}], "questions": ["Domain?"], "risks": ["Late"]}), "prometheus", "Proposed")
    return s


class TestStages(unittest.TestCase):
    def test_empty_session_is_at_overview_and_nothing_is_done(self):
        st = SP.stages(O.new_session())
        self.assertEqual([x["state"] for x in st], ["current"] + ["open"] * 6)

    def test_stages_follow_real_progress_and_review_needs_completion(self):
        s = session_with_plan()
        self.assertEqual(SP.current_stage(s), "plan", "ideas and brief exist; plan not approved yet")
        s["approved_version"] = s["active_version"]
        self.assertEqual(SP.current_stage(s), "design")
        s["workflow"] = O.make_workflow(O.current_plan(s), s["approved_version"])
        self.assertEqual(SP.current_stage(s), "build")
        with self.assertRaises(SP.StageError):
            SP.mark_reviewed(s)
        with self.assertRaises(SP.StageError):
            SP.mark_complete(s)
        for n in s["workflow"]["nodes"]:
            O.transition(s["workflow"], n["id"], "running") if n["status"] == "ready" else None
        O.transition(s["workflow"], "a1", "completed")
        O.transition(s["workflow"], "b1", "running")
        O.transition(s["workflow"], "b1", "completed")
        self.assertEqual(SP.current_stage(s), "review")
        SP.mark_reviewed(s)
        SP.mark_complete(s)
        self.assertTrue(all(x["state"] == "done" for x in SP.stages(s)))
        self.assertEqual(SP.stage_environment("build"), ("operations", "operations"))


class TestPanelsAndConnections(unittest.TestCase):
    def test_panels_show_only_real_data_or_say_what_fills_them(self):
        empty = O.new_session()
        for env in SP.ENVIRONMENTS.values():
            for pid in env["panels"]:
                c = SP.panel_content(empty, pid)
                self.assertTrue(c["items"] == [] and c["empty"], pid) if pid != "activity" else None
        s = session_with_plan()
        self.assertEqual([i["text"] for i in SP.panel_content(s, "ideas")["items"]], ["Static", "Blog"])
        self.assertIn("A small site.", [i["text"] for i in SP.panel_content(s, "brief")["items"]])
        self.assertEqual(SP.panel_content(s, "structure")["items"][0]["text"], "Write → Ship")
        nxt = [i["text"] for i in SP.panel_content(s, "next")["items"]]
        self.assertIn("Review and approve the plan", nxt)
        self.assertIn("Domain?", nxt)

    def test_connections_only_for_real_relationships(self):
        s = O.new_session()
        self.assertEqual([c for c in SP.connections(s, "command") if c["from"] == "core"], [])
        s = session_with_plan()
        cmd = SP.connections(s, "command")
        self.assertIn({"from": "core", "to": "brief", "kind": "context"}, cmd)
        self.assertNotIn("files", [c["to"] for c in cmd], "no files yet: no line to Files")
        self.assertIn({"from": "ideas", "to": "brief", "kind": "informs"}, cmd)

    def test_files_stay_inside_the_workspace(self):
        ws = tempfile.mkdtemp()
        open(os.path.join(ws, "notes.md"), "w").write("hello")
        s = session_with_plan()
        self.assertIsNotNone(SP.add_file(s, ws, "notes.md", "written", "a1"))
        self.assertIsNone(SP.add_file(s, ws, "../../etc/passwd", "attached"))
        self.assertIsNone(SP.add_file(s, ws, "/etc/passwd", "attached"))
        if hasattr(os, "symlink"):
            os.symlink("/etc", os.path.join(ws, "link"))
            self.assertIsNone(SP.add_file(s, ws, "link/passwd", "attached"), "symlinks out of the workspace are refused")
        self.assertEqual(SP.read_preview(ws, "notes.md"), "hello")
        with self.assertRaises(FileNotFoundError):
            SP.read_preview(ws, "../x")
        s["approved_version"] = s["active_version"]
        s["workflow"] = O.make_workflow(O.current_plan(s), 1)
        self.assertIn("written by", [c["kind"] for c in SP.connections(s, "operations")])


class TestLayout(unittest.TestCase):
    def test_layout_is_clamped_and_persisted_per_environment(self):
        s = O.new_session()
        r = SP.set_rect(s, "command", "brief", x=5.0, y=-3.0, w=0.01, h=9)
        self.assertTrue(r["x"] <= 0.94 and r["y"] >= 0 and r["w"] >= SP.MIN_W and r["h"] <= 0.9)
        self.assertEqual(SP.layout(s, "command")["brief"], r)
        self.assertNotEqual(SP.layout(s, "design")["brief"], r, "each environment keeps its own layout")
        s["layout"]["command"]["ideas"] = {"x": "nan", "w": None}
        self.assertGreaterEqual(SP.layout(s, "command")["ideas"]["w"], SP.MIN_W)
        with self.assertRaises(ValueError):
            SP.set_rect(s, "command", "operations", x=0.1)
        SP.reset_layout(s, "command")
        self.assertEqual(SP.layout(s, "command")["brief"], SP.clamp_rect(SP.default_rect("command", "brief")))


class TestMotion(unittest.TestCase):
    def test_states_map_to_distinct_visuals_and_unknown_is_idle(self):
        self.assertEqual(M.visual("nonsense"), M.visual("IDLE"))
        self.assertGreater(M.visual("LISTENING")["inflow"], 0)
        self.assertLess(M.visual("SPEAKING")["inflow"], 0)
        self.assertEqual(M.visual("WARNING")["tone"], "approval")
        self.assertEqual(M.visual("ERROR")["tone"], "error")
        self.assertLess(M.visual("WARNING")["ring_speed"], M.visual("THINKING")["ring_speed"], "approval suspends motion")

    def test_settings_really_change_budgets(self):
        store = {"orbit_fx_intensity": "subtle", "orbit_fx_particles": "low", "orbit_fx_volume": 3, "reduced_motion": False, "orbit_fx_energy": True, "orbit_fx_cinematic": True, "orbit_fx_sound": False}
        subtle = M.Settings.from_store(store.get)
        full = M.Settings.from_store({**store, "orbit_fx_intensity": "spectacular", "orbit_fx_particles": "high"}.get)
        self.assertLess(subtle.particle_count(), full.particle_count())
        self.assertLess(subtle.ring_count(), full.ring_count())
        self.assertEqual(subtle.volume, 1.0)
        self.assertLess(full.particle_count(0.25), full.particle_count(1.0))
        rm = M.Settings.from_store({**store, "reduced_motion": True}.get)
        self.assertFalse(rm.animate())
        self.assertEqual(M.Settings.from_store({"orbit_fx_intensity": "bogus"}.get).intensity, "spectacular")

    def test_effects_age_out_and_energy_off_keeps_only_structural_effects(self):
        fx = M.Effects()
        fx.start("shockwave")
        fx.start("materialise", "brief")
        fx.tick(0.8)
        self.assertEqual([e.kind for e in fx.active()], ["shockwave"])
        fx.tick(1.0)
        self.assertEqual(fx.active(), [])
        calm = M.Effects(energy=False)
        self.assertIsNone(calm.start("celebrate"))
        self.assertIsNotNone(calm.start("scan", "files"))
        with self.assertRaises(ValueError):
            fx.start("explode")
        self.assertTrue(M.effects_for("workflow.completed"))
        self.assertEqual(M.effects_for("nothing"), [])

    def test_frame_monitor_degrades_and_recovers(self):
        fm = M.FrameMonitor(window=5)
        for _ in range(10):
            fm.add(60)
        self.assertEqual(fm.quality, 0.5)
        for _ in range(20):
            fm.add(10)
        self.assertGreater(fm.quality, 0.5)

    def test_particles_flow_in_when_listening_and_out_when_speaking(self):
        ps = M.spawn(20)
        r0 = sum(p.radius for p in ps)
        M.advance(ps, 0.1, 0.5, 1.0)
        self.assertLess(sum(p.radius for p in ps), r0)
        ps = M.spawn(20)
        M.advance(ps, 0.1, 0.5, -1.0)
        self.assertGreater(sum(p.radius for p in ps), r0)


class TestCoreGeometryAndHud(unittest.TestCase):
    def test_geodesic_shell_and_bounded_torus(self):
        verts, edges = M.geodesic(1)
        self.assertEqual((len(verts), len(edges)), (42, 120))
        for v in verts:
            self.assertAlmostEqual(math.sqrt(sum(c * c for c in v)), 1.0, places=9)
        self.assertEqual(M.torus(10), M.torus(10))
        full = M.Settings()
        self.assertLess(M.Settings(particles="low").torus_count(), full.torus_count())
        self.assertLess(full.torus_count(0.25), full.torus_count())
        self.assertLess(M.Settings(reduced_motion=True).torus_count(), full.torus_count() + 1)

    def test_tilted_ring_near_side_faces_the_viewer(self):
        near = M.rotate(M.torus_point(math.pi / 2, 0, 0, 2, 0.4), 0, 0.37)
        far = M.rotate(M.torus_point(-math.pi / 2, 0, 0, 2, 0.4), 0, 0.37)
        self.assertGreater(near[2], 0)
        self.assertLess(far[2], 0)

    def test_curves_bow_away_from_the_core_and_pulses_stay_on_them(self):
        c = M.curve_ctrl((0, 0), (10, 0), (5, 5))
        self.assertLess(c[1], 0)
        self.assertEqual(M.bezier((0, 0), c, (10, 0), 0), (0, 0))
        self.assertEqual(M.bezier((0, 0), c, (10, 0), 1), (10, 0))

    def test_caption_is_one_clean_line_of_real_text(self):
        from app.ui.orbit_universe import caption_text

        self.assertEqual(caption_text("Prometheus", "**Here** is ```orbit-plan {}``` the plan"), "Prometheus: Here is the plan")
        self.assertLessEqual(len(caption_text("Prometheus", "x" * 500)), 194)
        self.assertEqual(caption_text("You", "   "), "")


class TestSound(unittest.TestCase):
    def test_sounds_are_synthesised_quiet_and_never_over_speech(self):
        played = []
        snd = SND.Sounds(lambda: True, lambda: 0.5, lambda: False, player=lambda d, sr: played.append((len(d), sr)))
        self.assertTrue(snd.play("panel"))
        self.assertEqual(played[0][1], SND.SR)
        data = SND.synth("milestone", 1.0)
        self.assertLessEqual(float(abs(data).max()), 0.351)
        self.assertFalse(SND.Sounds(lambda: True, lambda: 0.5, lambda: True, player=lambda d, sr: None).play("panel"), "never while speaking")
        self.assertFalse(SND.Sounds(lambda: False, lambda: 0.5, lambda: False, player=lambda d, sr: None).play("panel"), "off by default")
        self.assertFalse(snd.play("unknown"))


if __name__ == "__main__":
    unittest.main()
