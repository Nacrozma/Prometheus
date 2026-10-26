"""
Headless tests for PrometheusWorker (the streaming + tool-calling loop), the
router-settings glue, and the console helpers in gui_orb.py.

The worker's run() is called directly on the test thread with a scripted fake
router, so no LLM, network, audio or display is involved. Skipped automatically
if PyQt6 (or its system libraries) isn't available.
"""
import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

g = None
SKIP_REASON = None
try:
    import _gui_stubs
    _gui_stubs.install()
    from PyQt6.QtCore import QCoreApplication
    app = QCoreApplication.instance() or QCoreApplication([])
    import gui_orb as g  # noqa: E402
    import gui_config  # noqa: E402
    import gui_session  # noqa: E402
except Exception as e:  # PyQt6 missing, or libEGL etc. not installed
    SKIP_REASON = f"{type(e).__name__}: {e}"


def chunk(content=None, tool_calls=None, finish=None):
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=finish)])


def tc(index, call_id=None, name=None, args=None):
    return SimpleNamespace(index=index, id=call_id, function=SimpleNamespace(name=name, arguments=args))


class FakeRouter:
    provider = "groq"

    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.calls = []

    def completion(self, **kwargs):
        self.calls.append(kwargs)
        nxt = self.scripts.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt  # an iterable of chunks (a list or a generator)


class Recorder:
    def __init__(self, worker):
        self.states, self.statuses, self.responses = [], [], []
        self.tools, self.deltas, self.spoken = [], [], []
        worker.state_changed.connect(self.states.append)
        worker.status_updated.connect(lambda text, color: self.statuses.append(text))
        worker.response_received.connect(self.responses.append)
        worker.tool_executed.connect(lambda n, a, r: self.tools.append((n, a, r)))
        worker.text_delta.connect(self.deltas.append)
        worker.partial_text.connect(self.spoken.append)


@unittest.skipIf(g is None, f"PyQt6 GUI stack unavailable: {SKIP_REASON}")
class WorkerTests(unittest.TestCase):
    def setUp(self):
        self._orig = (g.dispatch_tool, g.build_context_block)
        self.dispatched = []
        g.build_context_block = lambda text: ""  # keep the tests off the real memory files

        def fake_dispatch(name, args):
            self.dispatched.append((name, args))
            return {"status": "success", "echo": name}
        g.dispatch_tool = fake_dispatch

    def tearDown(self):
        g.dispatch_tool, g.build_context_block = self._orig

    def make(self, scripts, auto_approve=False):
        router = FakeRouter(scripts)
        messages = [{"role": "user", "content": "do the thing"}]
        worker = g.PrometheusWorker(router, messages, auto_approve=auto_approve, fallback_models=["x/y"])
        return worker, router, messages, Recorder(worker)

    def assert_history_valid(self, messages):
        self.assertEqual(gui_session.sanitize_messages(messages), messages, "history has orphaned tool calls/results")

    # ---------------------------------------------------------------- happy paths
    def test_plain_answer(self):
        w, router, msgs, rec = self.make([[chunk("Hello there. "), chunk("Second sentence.", finish="stop")]])
        w.run()
        self.assertEqual(rec.responses, ["Hello there. Second sentence."])
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant"])
        self.assertEqual(rec.deltas[-1], "Hello there. Second sentence.")
        self.assertTrue(rec.spoken)  # sentences were handed to TTS as they streamed
        self.assertEqual(router.calls[0]["fallback_models"], ["x/y"])

    def test_tool_round_trip_with_fragmented_arguments(self):
        w, router, msgs, rec = self.make([
            [chunk(tool_calls=[tc(0, "c1", "get_system_telemetry", "{")]),
             chunk(tool_calls=[tc(0, None, None, '"a": 1}')])],
            [chunk("All done.")],
        ])
        w.run()
        self.assertEqual(self.dispatched, [("get_system_telemetry", {"a": 1})])
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant", "tool", "assistant"])
        self.assertEqual(msgs[2]["tool_call_id"], "c1")
        self.assertEqual(rec.responses, ["All done."])
        self.assert_history_valid(msgs)

    # ---------------------------------------------------------------- safety
    def test_invalid_json_arguments_are_not_executed(self):
        # e.g. a long tool call cut off by the token limit
        w, _, msgs, rec = self.make([
            [chunk(tool_calls=[tc(0, "c1", "write_file", '{"path": "x", "content": "unfinished')], finish="length")],
            [chunk("Sorry about that.")],
        ])
        w.run()
        self.assertEqual(self.dispatched, [])
        self.assertIn("not valid JSON", msgs[2]["content"])
        self.assertTrue(any("TOKEN LIMIT" in s for s in rec.statuses))
        self.assert_history_valid(msgs)

    def test_dangerous_tool_denied_is_not_executed(self):
        w, _, msgs, rec = self.make([
            [chunk(tool_calls=[tc(0, "c1", "write_file", '{"path": "a", "content": "b"}')])],
            [chunk("Understood.")],
        ])
        asked = []
        w.confirmation_requested.connect(lambda name, args: (asked.append(name), w.provide_confirmation(False)))
        w.run()
        self.assertEqual(asked, ["write_file"])
        self.assertEqual(self.dispatched, [])
        self.assertIn("refused", msgs[2]["content"])
        self.assert_history_valid(msgs)

    def test_dangerous_tool_approved_runs(self):
        w, _, msgs, _ = self.make([
            [chunk(tool_calls=[tc(0, "c1", "execute_shell", '{"command": "echo hi"}')])],
            [chunk("Done.")],
        ])
        w.confirmation_requested.connect(lambda name, args: w.provide_confirmation(True))
        w.run()
        self.assertEqual(self.dispatched, [("execute_shell", {"command": "echo hi"})])

    def test_auto_approve_skips_the_prompt(self):
        w, _, _, _ = self.make([
            [chunk(tool_calls=[tc(0, "c1", "write_file", '{"path": "a", "content": "b"}')])],
            [chunk("Done.")],
        ], auto_approve=True)
        asked = []
        w.confirmation_requested.connect(lambda n, a: asked.append(n))
        w.run()
        self.assertEqual(asked, [])
        self.assertEqual(len(self.dispatched), 1)

    def test_a_synthesized_tool_file_requires_confirmation(self):
        probe = os.path.join(g._prometheus_core.DYNAMIC_TOOLS_DIR, "zz_worker_probe.py")
        with open(probe, "w") as f:
            f.write("def execute(**k):\n    return 1\n")
        try:
            w, _, _, _ = self.make([[chunk(tool_calls=[tc(0, "c1", "zz_worker_probe", "{}")])], [chunk("ok")]])
            asked = []
            w.confirmation_requested.connect(lambda n, a: (asked.append(n), w.provide_confirmation(False)))
            w.run()
            self.assertEqual(asked, ["zz_worker_probe"])
            self.assertEqual(self.dispatched, [])
        finally:
            os.remove(probe)

    # ---------------------------------------------------------------- stopping
    def test_stop_mid_tool_loop_leaves_a_valid_history(self):
        """The old code broke out of the tool loop and saved an assistant message whose
        tool calls had no results - after which every later request was rejected."""
        w, _, msgs, rec = self.make([
            [chunk(tool_calls=[tc(0, "c1", "get_system_telemetry", "{}"), tc(1, "c2", "get_router_status", "{}")])],
        ])

        def stop_on_first(name, args):
            self.dispatched.append(name)
            w.request_stop()
            return {"status": "success"}
        g.dispatch_tool = stop_on_first
        w.run()
        self.assertEqual(self.dispatched, ["get_system_telemetry"])  # the second call never ran...
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant", "tool", "tool"])
        self.assertIn("cancelled", msgs[3]["content"])               # ...but it was answered
        self.assert_history_valid(msgs)
        self.assertEqual(rec.states[-1], "IDLE")

    def test_stop_during_streaming_drops_half_streamed_tool_calls(self):
        w, _, msgs, rec = self.make([[]])

        def stream():
            yield chunk("Hello ")
            w.request_stop()
            yield chunk("world")
            yield chunk(tool_calls=[tc(0, "c1", "write_file", '{"path": "a"}')])
        w.router.scripts = [stream()]
        w.run()
        self.assertEqual(self.dispatched, [])
        self.assertEqual(msgs[-1], {"role": "assistant", "content": "Hello "})
        self.assertTrue(any("STOPPED" in s for s in rec.statuses))
        self.assert_history_valid(msgs)

    # ---------------------------------------------------------------- robustness
    def test_router_failure_reports_and_returns_to_idle(self):
        w, _, msgs, rec = self.make([RuntimeError("all providers are down")])
        w.run()
        self.assertTrue(any("CORE ERROR" in s and "all providers are down" in s for s in rec.statuses))
        self.assertEqual(rec.states[-1], "IDLE")
        self.assertEqual(len(msgs), 1)

    def test_unexpected_exception_is_contained(self):
        w, _, msgs, rec = self.make([[chunk("hi")]])
        original = g.adaptation_engine.mutate_prompt
        g.adaptation_engine.mutate_prompt = lambda *a, **k: (_ for _ in ()).throw(ValueError("boom"))
        try:
            w.run()  # must not raise out of the thread
        finally:
            g.adaptation_engine.mutate_prompt = original
        self.assertTrue(any("boom" in s for s in rec.statuses))
        self.assertEqual(rec.states[-1], "IDLE")

    def test_huge_tool_result_is_capped_in_history(self):
        g.dispatch_tool = lambda name, args: {"status": "success", "blob": "x" * 50000}
        w, _, msgs, rec = self.make([[chunk(tool_calls=[tc(0, "c1", "read_file", '{"path": "a"}')])], [chunk("ok")]])
        w.run()
        content = msgs[2]["content"]
        self.assertLess(len(content), gui_session.TOOL_RESULT_CHAR_CAP + 100)
        self.assertIn("truncated", content)

    def test_non_json_serializable_tool_result_does_not_crash(self):
        g.dispatch_tool = lambda name, args: {"status": "success", "obj": object()}
        w, _, msgs, _ = self.make([[chunk(tool_calls=[tc(0, "c1", "read_file", '{"path": "a"}')])], [chunk("ok")]])
        w.run()
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant", "tool", "assistant"])

    def test_live_rendering_is_throttled_but_ends_complete(self):
        pieces = ["w "] * 300
        w, _, _, rec = self.make([[chunk(p) for p in pieces]])
        w.run()
        full = "".join(pieces)
        self.assertLess(len(rec.deltas), 60)     # was one re-render per token
        self.assertEqual(rec.deltas[-1], full)   # but the last render is the whole text

    def test_unnamed_tool_call_gets_a_placeholder_name(self):
        w, _, msgs, _ = self.make([[chunk(tool_calls=[tc(0, "c1", None, "{}")])], [chunk("ok")]])
        w.run()
        self.assertEqual(msgs[1]["tool_calls"][0]["function"]["name"], "unknown_tool")
        self.assert_history_valid(msgs)


@unittest.skipIf(g is None, f"PyQt6 GUI stack unavailable: {SKIP_REASON}")
class RouterSettingsTests(unittest.TestCase):
    def make_config(self, **values):
        path = os.path.join(tempfile.mkdtemp(prefix="gui_orb_cfg_"), "c.json")
        with open(path, "w") as f:
            json.dump(values, f)
        return gui_config.AppConfig(path)

    def tearDown(self):
        g.apply_router_settings(self.make_config())  # restore defaults for other tests

    def test_priority_and_overrides_are_applied_and_reversible(self):
        core = g._prometheus_core
        default_priority = list(core.PROVIDER_PRIORITY)
        notes = g.apply_router_settings(self.make_config(
            provider_priority=["cerebras", "groq", "bogus"], model_overrides={"ollama": "llama9", "nokey": "m"}))
        self.assertEqual(core.PROVIDER_PRIORITY, ["cerebras", "groq"])
        self.assertTrue(any("bogus" in n for n in notes))
        self.assertTrue(any("nokey" in n for n in notes))
        self.assertEqual(g.llm_router._clients["ollama"].default_model, "llama9")

        g.apply_router_settings(self.make_config())
        self.assertEqual(core.PROVIDER_PRIORITY, default_priority)
        self.assertNotEqual(g.llm_router._clients["ollama"].default_model, "llama9")


if __name__ == "__main__":
    unittest.main()
