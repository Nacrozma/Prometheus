#!/usr/bin/env python3
"""
Reproducible evaluation of Prometheus's new components.

    python evals/run_evals.py            # full run (adds the patch-gate benchmark; ~1 min)
    python evals/run_evals.py --quick    # seconds; what tests/test_evals.py runs

Everything is deterministic (fixed corpora, fixed seed, no network, no LLM) and writes
evals/results.json. IMPORTANT: these are SYNTHETIC benchmarks written by the author of
the code under test. They show the components behave as designed on hand-made cases;
they are not evidence about real-world performance, and the corpora are small. Read the
numbers as regression guards, not as claims of general accuracy.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("PROMETHEUS_FAST_BOOT", "1")

import memory_graph as mg  # noqa: E402
import skill_forge  # noqa: E402
import patch_gate  # noqa: E402

# --------------------------------------------------------------------------- memory recall
# (fact, query that paraphrases it with partly different words)
RECALL_CASES = [
    ("The user's name is Alex and they are applying to college for mechanical engineering.", "which major does the applicant want"),
    ("The aerospace minor is planned alongside the mechanical engineering degree.", "what minor is planned"),
    ("The application deadline is September 28 2027.", "when is the application due"),
    ("Prometheus stores memory in a JSON file that used to corrupt under concurrent writes.", "why did the memory file get corrupted"),
    ("The race condition was fixed with a shared lock and atomic os.replace writes.", "how was the race fixed"),
    ("The robotic arm will be controlled by hand gestures seen through a webcam.", "gesture controlled arm camera"),
    ("The arm uses an Arduino Nano as its microcontroller board.", "which microcontroller board for the arm"),
    ("The user has no 3D printer access so parts must be bought or laser cut.", "can the user print parts"),
    ("The user can spend one to two hours per day on projects.", "how much time per day is available"),
    ("The cyberdeck is a long term project costing three hundred to five hundred dollars.", "expensive portable computer project"),
    ("Groq and Cerebras are fast inference providers used by the router.", "which providers does the router use"),
    ("The old WiFi router is disconnected so cloud providers need a fallback.", "what happens when the network is down"),
    ("Obsidian vault notes mirror the memory graph with wikilinks.", "how do notes link to each other"),
    ("Skills written by Prometheus run in a Docker sandbox without network access.", "where do generated skills execute"),
    ("The patch gate runs the test suite before any self modification is applied.", "what checks self modification"),
    ("Atlas and Iapetus are planned future modules and do not exist yet.", "which modules are only planned"),
    ("The GUI renders an animated orb with OpenGL shaders.", "what draws the glowing sphere"),
    ("Speech recognition uses Whisper and speech output uses edge tts.", "voice input and output engines"),
    ("The user prefers concise answers without filler.", "preferred answer style"),
    ("Tavily provides web search results for research tasks.", "which service searches the web"),
    ("Importance of a memory decays over time unless it is recalled again.", "do old unused memories fade"),
    ("Confirmation is required before running shell commands or writing files.", "which actions need approval"),
    ("Corrupt state files are quarantined with a timestamp suffix instead of overwritten.", "what happens to a damaged state file"),
    ("The essay will tell the memory drift bug story in the first person.", "what is the college essay about"),
    ("Every AI assisted part of the project must be disclosed in the application.", "must the use of AI be mentioned"),
]

# --------------------------------------------------------------------------- dedupe
SHOULD_MERGE = [
    ("The deadline is September 28 2027.", "the deadline is september 28 2027"),
    ("The user likes strong black coffee.", "The user likes strong black coffee!"),
    ("Prometheus runs on a Windows PC.", "Prometheus   runs on a Windows PC"),
]
MUST_NOT_MERGE = [
    ("The deadline is September 28 2027.", "The deadline is September 29 2027."),
    ("The user likes coffee.", "The user does not like coffee."),
    ("The arm has 5 servos.", "The arm has 6 servos."),
    ("The router is connected.", "The router is not connected."),
    ("The user wants to study aerospace engineering.", "The user wants to study mechanical engineering."),
    ("Budget is 300 dollars.", "Budget is 3000 dollars."),
    ("The build passed all tests.", "The build failed all tests."),
    ("Always confirm shell commands.", "Never confirm shell commands."),
]

# --------------------------------------------------------------------------- entity extraction
ENTITY_CASES = [
    ("The Arduino Nano controls the Robotic Arm.", {"Arduino Nano", "Robotic Arm"}),
    ("Alex asked Prometheus to open [[Cyberdeck Plan]].", {"Alex", "Prometheus", "Cyberdeck Plan"}),
    ("this is a note about #aerospace and nothing else", set()),
    ("The weather is nice today and the sky is blue.", set()),
    ("MIT and Georgia Tech are on the college list.", {"MIT", "Georgia Tech"}),
    ("Remember to buy servos and a breadboard.", set()),
    ("Docker blocks network access for skills.", {"Docker"}),
    ("Please remember that things change.", set()),
]

# --------------------------------------------------------------------------- skill gate
GOOD_SKILLS = [
    "def execute(**kw):\n    return {'status': 'success', 'value': 2 * float(kw.get('x', 1))}\n",
    "import math\n\ndef execute(**kw):\n    r = float(kw.get('r', 1))\n    return {'status': 'success', 'area': math.pi * r * r}\n",
    "import json\nimport re\n\nK = 3\n\ndef helper(s):\n    return re.sub(r'\\s+', ' ', s)\n\ndef execute(**kw):\n    return {'status': 'success', 'v': helper(str(kw.get('s', '')))}\n",
]
BAD_SKILLS = [
    "import os\n\ndef execute(**kw):\n    return os.listdir('.')\n",
    "import subprocess\n\ndef execute(**kw):\n    return subprocess.run(['id'])\n",
    "def execute(**kw):\n    return eval(kw['e'])\n",
    "def execute(**kw):\n    exec(kw['c'])\n",
    "def execute(**kw):\n    return open('/etc/passwd').read()\n",
    "def execute(**kw):\n    return __import__('os').getcwd()\n",
    "import socket\n\ndef execute(**kw):\n    return socket.gethostname()\n",
    "print('side effect at import')\n\ndef execute(**kw):\n    return 1\n",
    "def helper():\n    return 1\n",
    "def execute(**kw):\n    return ().__class__.__bases__[0].__subclasses__()\n",
    "from os import path\n\ndef execute(**kw):\n    return path.sep\n",
    "def execute(**kw)\n    return 1\n",
    "import requests\n\ndef execute(**kw):\n    return requests.get('http://x')\n",
    "async def execute(**kw):\n    return 1\n",
]

# --------------------------------------------------------------------------- patch gate
CORE = '''"""stand-in core"""
CASES = [1, 2, 3]
DANGEROUS = frozenset({"shell", "write_file"})


def dispatch(x):
    return x * 2


def main():
    return "ok"
'''
CORE_TEST = '''import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core


class T(unittest.TestCase):
    def test_dispatch(self):
        self.assertEqual(core.dispatch(2), 4)

    def test_main(self):
        self.assertEqual(core.main(), "ok")


for _n in core.CASES:
    setattr(T, f"test_case_{_n}", lambda self, n=_n: self.assertTrue(n))
'''
GOOD_PATCHES = [
    CORE + "\n\ndef helper():\n    return 1\n",
    CORE.replace('"write_file"}', '"write_file", "extra"}'),
    CORE.replace('"""stand-in core"""', '"""stand-in core, documented better"""'),
]
BAD_PATCHES = [
    "def broken(:\n",                                                                         # syntax
    CORE.replace('def main():\n    return "ok"\n', ""),                                       # symbol removed
    CORE.replace('frozenset({"shell", "write_file"})', 'frozenset({"write_file"})'),          # safety list weakened
    CORE.replace("return x * 2", "return x * 3"),                                             # behaviour break
    CORE.replace("CASES = [1, 2, 3]", "CASES = [1]"),                                         # silently drops tests
    CORE + "\nimport definitely_not_a_real_module_xyz\n",                                     # import error
    "x = 1\n" * 400_000,                                                                      # oversized
]


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def eval_recall():
    import prometheus as p
    tmp = tempfile.mkdtemp(prefix="eval_recall_")
    try:
        graph = mg.MemoryGraph(os.path.join(tmp, "g.json"))
        rag = p.VectorRAGStore(filepath=os.path.join(tmp, "v.json"))
        for text, _ in RECALL_CASES:
            graph.add_fact(text)
            rag.add_document(text)
        out = {}
        for name, search in (("memory_graph", lambda q: [f["text"] for f in graph.recall(q, top_k=3, touch=False)]),
                             ("legacy_vector_rag", lambda q: [d["content"] for _, d in rag.search(q, top_k=3)])):
            hit1 = hit3 = rr = 0.0
            for gold, query in RECALL_CASES:
                ranked = search(query)
                if ranked and ranked[0] == gold:
                    hit1 += 1
                if gold in ranked:
                    hit3 += 1
                    rr += 1.0 / (ranked.index(gold) + 1)
            n = len(RECALL_CASES)
            out[name] = {"p_at_1": round(hit1 / n, 3), "p_at_3": round(hit3 / n, 3), "mrr": round(rr / n, 3)}
        out["queries"] = len(RECALL_CASES)
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def eval_dedupe():
    def merged(a, b):
        tmp = tempfile.mkdtemp(prefix="eval_dedupe_")
        try:
            g = mg.MemoryGraph(os.path.join(tmp, "g.json"))
            g.add_fact(a)
            return not g.add_fact(b)["created"]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    false_merges = [pair for pair in MUST_NOT_MERGE if merged(*pair)]
    missed = [pair for pair in SHOULD_MERGE if not merged(*pair)]
    return {"must_not_merge_pairs": len(MUST_NOT_MERGE), "false_merges": len(false_merges),
            "false_merge_examples": false_merges, "should_merge_pairs": len(SHOULD_MERGE),
            "missed_merges": len(missed)}


def eval_entities():
    tp = fp = fn = 0
    for text, gold in ENTITY_CASES:
        got = {name for name, _ in mg.extract_entities(text)}
        got_l, gold_l = {g.lower() for g in got}, {g.lower() for g in gold}
        tp += len(got_l & gold_l)
        fp += len(got_l - gold_l)
        fn += len(gold_l - got_l)
    p, r, f1 = prf(tp, fp, fn)
    return {"sentences": len(ENTITY_CASES), "precision": round(p, 3), "recall": round(r, 3), "f1": round(f1, 3)}


def eval_skill_gate():
    accepted_good = sum(1 for c in GOOD_SKILLS if not skill_forge.check_policy(c))
    rejected_bad = sum(1 for c in BAD_SKILLS if skill_forge.check_policy(c))
    return {"good_skills": len(GOOD_SKILLS), "good_accepted": accepted_good,
            "bad_skills": len(BAD_SKILLS), "bad_rejected": rejected_bad}


def eval_patch_gate():
    repo = tempfile.mkdtemp(prefix="eval_gate_")
    try:
        os.makedirs(os.path.join(repo, "tests"))
        open(os.path.join(repo, "core.py"), "w").write(CORE)
        open(os.path.join(repo, "tests", "test_core.py"), "w").write(CORE_TEST)
        kw = dict(required_symbols={"dispatch", "main", "DANGEROUS"}, protected_assignments=["DANGEROUS"], timeout=60)
        good_ok = sum(1 for c in GOOD_PATCHES if patch_gate.validate_patch(repo, "core.py", c, **kw)["accepted"])
        bad_rej = sum(1 for c in BAD_PATCHES if not patch_gate.validate_patch(repo, "core.py", c, **kw)["accepted"])
        return {"good_patches": len(GOOD_PATCHES), "good_accepted": good_ok,
                "bad_patches": len(BAD_PATCHES), "bad_rejected": bad_rej}
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def eval_state_stress(rounds):
    t0 = time.time()
    proc = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "stress_state.py"), "--rounds", str(rounds)],
                          capture_output=True, text=True, timeout=900, env={**os.environ, "PROMETHEUS_FAST_BOOT": "1"})
    failed = None
    for line in proc.stdout.splitlines():
        if line.startswith("failed rounds:"):
            failed = int(line.split(":")[1].split("/")[0])
    return {"rounds": rounds, "failed_rounds": failed, "exit_code": proc.returncode, "seconds": round(time.time() - t0, 1)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true", help="skip the slow benchmarks (patch gate, large stress run)")
    ap.add_argument("--out", default=os.path.join(ROOT, "evals", "results.json"))
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)

    results = {"synthetic_benchmarks": True, "quick": args.quick,
               "memory_recall": eval_recall(), "dedupe": eval_dedupe(), "entity_extraction": eval_entities(),
               "skill_gate": eval_skill_gate()}
    if not args.quick:
        results["patch_gate"] = eval_patch_gate()
        results["state_stress"] = eval_state_stress(100)
    if not args.no_write:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
            f.write("\n")
    print(json.dumps(results, indent=2))
    return results


if __name__ == "__main__":
    main()
