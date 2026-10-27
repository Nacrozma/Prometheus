"""Tests for gui_config.py, gui_markdown.py and gui_birth.py. No Qt, no network."""
import copy
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gui_birth as birth  # noqa: E402
import gui_config as cfg  # noqa: E402
import gui_markdown as md  # noqa: E402


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="gui_config_test_")
        self.path = os.path.join(self.dir, "prometheus_config.json")

    def test_defaults_when_file_missing(self):
        c = cfg.AppConfig(self.path)
        self.assertEqual(c.data, cfg.DEFAULTS)
        self.assertEqual(c.load_error, "")

    def test_values_are_coerced(self):
        with open(self.path, "w") as f:
            json.dump({"speech_rate": 999, "voice": "not a voice!!", "max_console_entries": 1,
                       "speech_enabled": "yes", "fallback_models": "nope"}, f)
        c = cfg.AppConfig(self.path)
        self.assertEqual(c["speech_rate"], 100)
        self.assertEqual(c["voice"], cfg.DEFAULTS["voice"])
        self.assertEqual(c["max_console_entries"], 50)
        self.assertEqual(c["speech_enabled"], cfg.DEFAULTS["speech_enabled"])
        self.assertEqual(c["fallback_models"], cfg.DEFAULTS["fallback_models"])

    def test_invalid_value_does_not_alias_the_defaults(self):
        before = copy.deepcopy(cfg.DEFAULTS)
        c = cfg.AppConfig(self.path)
        c.set("fallback_models", "garbage")          # falls back to the default list...
        c.data["fallback_models"].append("mutated")  # ...which must be a COPY
        self.assertEqual(cfg.DEFAULTS, before)

    def test_corrupt_file_is_quarantined_and_surfaced(self):
        with open(self.path, "w") as f:
            f.write('{"voice": "en-US-Chris')  # truncated
        c = cfg.AppConfig(self.path)
        self.assertEqual(c.data, cfg.DEFAULTS)
        self.assertIn("JSONDecodeError", c.load_error)
        self.assertIn("kept as", c.load_error)
        c.save()  # saving the defaults must NOT destroy the original
        kept = [n for n in os.listdir(self.dir) if ".corrupt." in n]
        self.assertEqual(len(kept), 1)
        with open(os.path.join(self.dir, kept[0])) as f:
            self.assertIn("en-US-Chris", f.read())

    def test_non_object_json_is_rejected(self):
        with open(self.path, "w") as f:
            f.write("[1, 2, 3]")
        c = cfg.AppConfig(self.path)
        self.assertEqual(c.data, cfg.DEFAULTS)
        self.assertTrue(c.load_error)

    def test_save_round_trip_and_unknown_keys_survive(self):
        with open(self.path, "w") as f:
            json.dump({"voice": "en-GB-SoniaNeural", "future_setting": {"a": 1}}, f)
        c = cfg.AppConfig(self.path)
        self.assertTrue(c.save())
        again = cfg.AppConfig(self.path)
        self.assertEqual(again["voice"], "en-GB-SoniaNeural")
        self.assertEqual(again["future_setting"], {"a": 1})
        self.assertEqual([n for n in os.listdir(self.dir) if n.endswith(".tmp")], [])

    def test_obsidian_vault_setting_is_validated(self):
        with open(self.path, "w") as f:
            json.dump({"obsidian_vault": "C:\\Users\\me\\Vault"}, f)
        self.assertEqual(cfg.AppConfig(self.path)["obsidian_vault"], "C:\\Users\\me\\Vault")
        for bad in ("evil\x00path", "x" * 501, 7, None, ["a"]):
            c = cfg.AppConfig(self.path)
            c.set("obsidian_vault", bad)
            self.assertEqual(c["obsidian_vault"], "")

    def test_parse_helpers(self):
        self.assertEqual(cfg.parse_csv("a, b,, c ,"), ["a", "b", "c"])
        self.assertEqual(cfg.parse_model_overrides("groq=llama-x, bad, =nope, or=meta/llama=2, empty="),
                         {"groq": "llama-x", "or": "meta/llama=2"})


class MarkdownTests(unittest.TestCase):
    def test_html_in_model_output_is_escaped(self):
        out = md.render_markdown('<script>alert(1)</script> <img src="file:///etc/passwd"> **ok**')
        self.assertNotIn("<script", out)
        self.assertNotIn("<img", out)
        self.assertIn("&lt;script&gt;", out)
        self.assertIn("<b>ok</b>", out)

    def test_code_block_content_is_escaped_too(self):
        out = md.render_markdown("```html\n<b onclick=x>hi</b>\n```")
        self.assertNotIn("<b onclick", out)

    def test_link_with_underscores_keeps_a_valid_href(self):
        out = md.render_markdown("see [docs](https://a.com/_foo_/b_c_d?x=1&y=2) now")
        self.assertIn('href="https://a.com/_foo_/b_c_d?x=1&amp;y=2"', out)
        self.assertNotIn("<i>", out)

    def test_emphasis_inside_link_text_still_works(self):
        out = md.render_markdown("[**bold** text](https://a.com)")
        self.assertIn("<b>bold</b> text</a>", out)

    def test_nul_bytes_cannot_forge_link_placeholders(self):
        out = md.render_markdown("evil \x000\x00 and [x](https://a.com)")
        self.assertIn('href="https://a.com"', out)

    def test_fenced_code_is_registered_for_copy(self):
        reg = {}
        out = md.render_markdown("```python\nprint('hi')\n```", code_registry=reg, id_prefix="t")
        self.assertEqual(reg, {"t-0": "print('hi')"})
        self.assertIn(md.COPY_PREFIX + "t-0", out)

    def test_unterminated_fence_does_not_crash_while_streaming(self):
        reg = {}
        out = md.render_markdown("Here:\n```python\ndef f():\n    return 1", code_registry=reg)
        self.assertIn("def", out)
        self.assertEqual(len(reg), 1)

    def test_table_and_list_render(self):
        out = md.render_markdown("| a | b |\n|---|---|\n| 1 | 2 |\n\n- one\n- two")
        self.assertIn("<table", out)
        self.assertIn("&bull;", out)

    def test_highlighter_survives_odd_input(self):
        for lang in ("python", "js", "json", "bash", "nonsense", ""):
            md.highlight_code('"unterminated \\ \x00 # ``` \'\'\'', lang, md.DEFAULT_THEME)


class SpeechTests(unittest.TestCase):
    def test_markup_urls_and_emoji_are_not_spoken(self):
        spoken = md.clean_for_speech("## Title\n**Bold** and `code` see https://example.com/a_b 🚀 [site](https://x.io)")
        for junk in ("**", "`", "##", "https://", "🚀"):
            self.assertNotIn(junk, spoken)
        self.assertIn("link", spoken)
        self.assertIn("site", spoken)

    def test_code_block_is_announced_once_and_not_read_out(self):
        spoken = md.clean_for_speech("Intro.\n```python\nprint('secret_code')\n```\nOutro.")
        self.assertIn(md.CODE_ANNOUNCEMENT, spoken)
        self.assertNotIn("secret_code", spoken)
        self.assertIn("Outro", spoken)

    def test_fence_state_persists_across_streamed_chunks(self):
        f = md.SpeechFilter()
        parts = [f.feed("Before. "), f.feed("```python\nx = 1\n"), f.feed("y = 2\n"), f.feed("```\nAfter. ")]
        joined = " ".join(parts)
        self.assertNotIn("x = 1", joined)
        self.assertNotIn("y = 2", joined)
        self.assertEqual(joined.count(md.CODE_ANNOUNCEMENT), 1)
        self.assertIn("After", joined)


class BirthTimelineTests(unittest.TestCase):
    def run_until_done(self, tl, dt=0.05, limit=100000):
        for _ in range(limit):
            if tl.tick(dt):
                return True
        return False

    def test_waits_at_the_hold_point_until_ready(self):
        tl = birth.BirthTimeline()
        tl.start(ready=False)
        for _ in range(int(birth.DURATION * 40)):  # far longer than the animation
            tl.tick(0.05)
        self.assertTrue(tl.holding)
        self.assertAlmostEqual(tl.t, birth.HOLD_T, places=3)
        self.assertEqual(tl.phase_label, "AWAITING SPEECH CORE")
        tl.mark_ready()
        self.assertTrue(self.run_until_done(tl))
        self.assertEqual(tl.t, 1.0)

    def test_already_ready_runs_straight_through(self):
        tl = birth.BirthTimeline()
        tl.start(ready=True)
        self.assertTrue(self.run_until_done(tl))
        self.assertFalse(tl.timed_out)

    def test_hold_gives_up_after_the_timeout(self):
        tl = birth.BirthTimeline()
        tl.start(ready=False)
        self.assertTrue(self.run_until_done(tl, dt=0.25, limit=10000))
        self.assertTrue(tl.timed_out)

    def test_skip_fast_forwards_even_while_holding(self):
        tl = birth.BirthTimeline()
        tl.start(ready=False)
        while not tl.holding:
            tl.tick(0.05)
        tl.skip()
        self.assertFalse(tl.holding)
        self.assertTrue(self.run_until_done(tl))

    def test_finish_is_reported_exactly_once(self):
        tl = birth.BirthTimeline()
        tl.start(ready=True)
        finishes = sum(1 for _ in range(2000) if tl.tick(0.05))
        self.assertEqual(finishes, 1)
        self.assertFalse(tl.active)

    def test_inactive_timeline_never_reports_a_finish(self):
        self.assertFalse(birth.BirthTimeline().tick(1.0))

    def test_scale_energy_and_t_stay_in_range(self):
        tl = birth.BirthTimeline()
        tl.start(ready=True)
        while tl.active:
            tl.tick(0.02)
            self.assertTrue(0.0 <= tl.t <= 1.0)
            self.assertTrue(0.0 <= tl.scale <= 1.0 + 1e-9)
            self.assertTrue(0.0 <= tl.energy < 10.0)
        self.assertAlmostEqual(tl.scale, 1.0, places=6)
        self.assertAlmostEqual(tl.energy, birth.BASE_ENERGY, places=6)

    def test_start_resets_a_finished_timeline(self):
        tl = birth.BirthTimeline()
        tl.start(ready=True)
        self.run_until_done(tl)
        tl.start(ready=False)
        self.assertTrue(tl.active)
        self.assertEqual(tl.t, 0.0)
        self.assertFalse(tl.timed_out)


if __name__ == "__main__":
    unittest.main()
