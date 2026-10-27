"""Regression guards on the synthetic benchmarks in evals/run_evals.py (quick mode).

Thresholds are deliberately below the measured values: they catch regressions, they do not
claim general accuracy. See evals/run_evals.py for what the corpora are.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "evals"))
os.environ.setdefault("PROMETHEUS_FAST_BOOT", "1")
import run_evals  # noqa: E402


class QuickEvals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = cls._run()

    @staticmethod
    def _run():
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            return run_evals.main(["--quick", "--no-write"])

    def test_recall_is_reasonable_and_not_worse_than_the_baseline_by_much(self):
        g, b = self.r["memory_recall"]["memory_graph"], self.r["memory_recall"]["legacy_vector_rag"]
        self.assertGreaterEqual(g["mrr"], 0.65)
        self.assertGreaterEqual(g["mrr"], b["mrr"] - 0.10)

    def test_dedupe_never_merges_contradictory_statements(self):
        d = self.r["dedupe"]
        self.assertEqual(d["false_merges"], 0, d["false_merge_examples"])
        self.assertEqual(d["missed_merges"], 0)

    def test_entity_extraction(self):
        self.assertGreaterEqual(self.r["entity_extraction"]["precision"], 0.8)
        self.assertGreaterEqual(self.r["entity_extraction"]["f1"], 0.7)

    def test_skill_gate_blocks_every_bad_skill_and_passes_good_ones(self):
        s = self.r["skill_gate"]
        self.assertEqual(s["bad_rejected"], s["bad_skills"])
        self.assertEqual(s["good_accepted"], s["good_skills"])


if __name__ == "__main__":
    unittest.main()
