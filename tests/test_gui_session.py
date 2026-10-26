"""Tests for gui_session.py - persistence and history hygiene. No Qt, no network."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gui_session as gs  # noqa: E402


def user(text="hi"):
    return {"role": "user", "content": text}


def asst(text="", calls=None):
    m = {"role": "assistant", "content": text}
    if calls:
        m["tool_calls"] = [{"id": c, "type": "function", "function": {"name": "t", "arguments": "{}"}} for c in calls]
    return m


def tool(call_id, content="{}"):
    return {"role": "tool", "tool_call_id": call_id, "name": "t", "content": content}


class SanitizeTests(unittest.TestCase):
    def test_valid_history_is_unchanged(self):
        h = [user(), asst("", ["a"]), tool("a"), asst("done"), user("again"), asst("ok")]
        self.assertEqual(gs.sanitize_messages(h), h)

    def test_orphan_tool_result_is_dropped(self):
        h = [tool("ghost"), user(), asst("ok")]
        self.assertEqual(gs.sanitize_messages(h), [user(), asst("ok")])

    def test_unanswered_tool_call_is_removed_but_content_kept(self):
        # Stop pressed mid tool loop: the assistant message has a call and no result.
        h = [user(), asst("let me check", ["a"])]
        out = gs.sanitize_messages(h)
        self.assertEqual(out, [user(), asst("let me check")])
        self.assertNotIn("tool_calls", out[1])

    def test_unanswered_tool_call_with_no_content_drops_the_message(self):
        self.assertEqual(gs.sanitize_messages([user(), asst("", ["a"])]), [user()])

    def test_partially_answered_calls_keep_only_the_answered_one(self):
        h = [user(), asst("", ["a", "b"]), tool("a")]
        out = gs.sanitize_messages(h)
        self.assertEqual([c["id"] for c in out[1]["tool_calls"]], ["a"])
        self.assertEqual([m["role"] for m in out], ["user", "assistant", "tool"])

    def test_garbage_entries_are_ignored(self):
        h = ["junk", None, 5, {"role": "wizard", "content": "x"}, {"no_role": 1}, user()]
        self.assertEqual(gs.sanitize_messages(h), [user()])

    def test_not_a_list(self):
        self.assertEqual(gs.sanitize_messages({"a": 1}), [])
        self.assertEqual(gs.sanitize_messages(None), [])

    def test_does_not_mutate_input(self):
        h = [user(), asst("x", ["a"])]
        snapshot = json.dumps(h)
        gs.sanitize_messages(h)
        self.assertEqual(json.dumps(h), snapshot)


class TrimTests(unittest.TestCase):
    def test_under_cap_is_untouched(self):
        h = [user(), asst("a")]
        self.assertEqual(gs.trim_messages(h, 10), 0)
        self.assertEqual(len(h), 2)

    def test_cut_lands_on_a_user_message(self):
        h = []
        for i in range(10):
            h += [user(f"q{i}"), asst(f"a{i}")]
        removed = gs.trim_messages(h, 7)
        self.assertGreater(removed, 0)
        self.assertEqual(h[0]["role"], "user")
        self.assertLessEqual(len(h), 8)

    def test_never_splits_a_tool_exchange(self):
        h = [user("q0"), asst("", ["a"]), tool("a"), asst("r0"),
             user("q1"), asst("", ["b"]), tool("b"), asst("r1")]
        gs.trim_messages(h, 5)  # naive cut at index 3 would start on 'asst r0'
        self.assertEqual(h[0]["role"], "user")
        self.assertEqual(gs.sanitize_messages(h), h)  # still a valid history

    def test_no_safe_cut_point_keeps_everything(self):
        h = [asst("a")] * 10
        self.assertEqual(gs.trim_messages(h, 4), 0)
        self.assertEqual(len(h), 10)


class CapTextTests(unittest.TestCase):
    def test_short_text_untouched(self):
        self.assertEqual(gs.cap_text("abc", 10), "abc")

    def test_long_text_is_cut_and_marked(self):
        out = gs.cap_text("x" * 100, 10)
        self.assertTrue(out.startswith("x" * 10))
        self.assertIn("truncated 90 chars", out)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="gui_session_test_")
        self.path = os.path.join(self.dir, "session.json")

    def listing(self):
        return sorted(os.listdir(self.dir))

    def test_round_trip(self):
        h = [user("hello"), asst("héllo wörld ✓")]
        self.assertTrue(gs.save_session(self.path, h))
        self.assertEqual(gs.load_session(self.path), h)

    def test_missing_file_is_empty(self):
        self.assertEqual(gs.load_session(self.path), [])

    def test_truncated_file_is_quarantined_not_overwritten(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write('[{"role": "user", "content": "precious"')  # what a crash mid-write used to leave behind
        self.assertEqual(gs.load_session(self.path), [])
        kept = [n for n in self.listing() if ".corrupt." in n]
        self.assertEqual(len(kept), 1)
        with open(os.path.join(self.dir, kept[0]), encoding="utf-8") as f:
            self.assertIn("precious", f.read())
        self.assertFalse(os.path.exists(self.path))

    def test_non_list_json_is_quarantined(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"oops": True}, f)
        self.assertEqual(gs.load_session(self.path), [])
        self.assertTrue(any(".corrupt." in n for n in self.listing()))

    def test_load_repairs_an_orphaned_tool_call(self):
        gs.save_session(self.path, [user(), asst("", ["a"])])
        self.assertEqual(gs.load_session(self.path), [user()])

    def test_save_leaves_no_temp_files(self):
        gs.save_session(self.path, [user()])
        self.assertEqual(self.listing(), ["session.json"])

    def test_failed_save_returns_false_and_leaves_no_temp_file(self):
        self.assertFalse(gs.atomic_write_json(os.path.join(self.dir, "missing_dir", "x.json"), {"a": 1}))
        self.assertEqual(self.listing(), [])

    def test_unserializable_data_fails_cleanly_and_keeps_the_old_file(self):
        gs.save_session(self.path, [user("old")])
        self.assertFalse(gs.atomic_write_json(self.path, {"bad": object()}))
        self.assertEqual(gs.load_session(self.path), [user("old")])
        self.assertEqual(self.listing(), ["session.json"])


if __name__ == "__main__":
    unittest.main()
