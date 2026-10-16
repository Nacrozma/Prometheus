#!/usr/bin/env python3
"""
Concurrency stress test for Prometheus's JSON state files.

Each round, several writer threads add facts through update_memory_fact()
(which also indexes each fact into the vector store) while reader threads
hammer the files. After the threads finish, the round FAILS if any of these
happened:

  * a fact is missing from memory.json            (lost update)
  * memory.json / vector_store.json won't parse   (corruption)
  * a reader saw a half-written vector_store.json (torn read)
  * any thread raised an exception

Run the fixed code:      python tests/stress_state.py
Run 'before' behaviour:  python tests/stress_state.py --legacy

--legacy switches OFF the shared lock and restores the old non-atomic
VectorRAGStore.save() that wrote straight into the live file. It reproduces
the original failure mode; it is a simulation of the old code, not the old
code itself.

Nothing here touches your real memory.json or vector_store.json: every round
works in its own temporary directory.
"""
import argparse
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import prometheus as p  # noqa: E402  (importing starts nothing that calls an LLM)


class _NullLock:
    """Stand-in for the shared lock in --legacy mode."""
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _legacy_vector_save(self):
    # The pre-fix behaviour: open the live file with "w" (truncating it) and
    # write into it directly, with no temp file and no lock.
    with open(self.filepath, "w", encoding="utf-8") as f:
        json.dump(self.documents, f, ensure_ascii=False, indent=2)


def run_round(workdir, writers, per_writer, readers):
    mem_path = os.path.join(workdir, "memory.json")
    vec_path = os.path.join(workdir, "vector_store.json")
    p.rag_store = p.VectorRAGStore(filepath=vec_path)  # update_memory_fact indexes into this

    expected = {f"w{w} fact {i}" for w in range(writers) for i in range(per_writer)}
    problems = {"lost_update": 0, "memory_corrupt": 0, "vector_corrupt": 0,
                "torn_read": 0, "exception": 0}
    problem_lock = threading.Lock()
    stop = threading.Event()

    def bump(kind):
        with problem_lock:
            problems[kind] += 1

    def writer(w):
        for i in range(per_writer):
            try:
                p.update_memory_fact(f"w{w} fact {i}", filepath=mem_path)
            except Exception:
                bump("exception")

    def reader():
        while not stop.is_set():
            try:
                p.load_memory(mem_path, strict=True)
            except Exception:
                bump("exception")
            try:  # raw read, deliberately outside any lock: what would a crash/other process see?
                with open(vec_path, "r", encoding="utf-8") as f:
                    json.load(f)
            except FileNotFoundError:
                pass
            except PermissionError:
                pass  # Windows: file briefly held during replace - not corruption
            except json.JSONDecodeError:
                bump("torn_read")

    writer_threads = [threading.Thread(target=writer, args=(w,)) for w in range(writers)]
    reader_threads = [threading.Thread(target=reader) for _ in range(readers)]
    for th in reader_threads + writer_threads:
        th.start()
    for th in writer_threads:
        th.join()
    stop.set()
    for th in reader_threads:
        th.join()

    # Final verification straight from disk.
    try:
        with open(mem_path, "r", encoding="utf-8") as f:
            facts = set(json.load(f).get("facts", []))
        if not expected <= facts:
            bump("lost_update")
    except Exception:
        bump("memory_corrupt")
    try:
        with open(vec_path, "r", encoding="utf-8") as f:
            docs = json.load(f)
        if len(docs) != len(expected):
            bump("lost_update")
    except Exception:
        bump("vector_corrupt")

    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rounds", type=int, default=500)
    ap.add_argument("--writers", type=int, default=4)
    ap.add_argument("--per-writer", type=int, default=3)
    ap.add_argument("--readers", type=int, default=2)
    ap.add_argument("--legacy", action="store_true", help="simulate the pre-fix behaviour (no lock, non-atomic vector save)")
    args = ap.parse_args()

    if args.legacy:
        p._STATE_LOCK = _NullLock()
        p.VectorRAGStore.save = _legacy_vector_save

    totals = {"lost_update": 0, "memory_corrupt": 0, "vector_corrupt": 0, "torn_read": 0, "exception": 0}
    failed_rounds = 0
    for r in range(args.rounds):
        workdir = tempfile.mkdtemp(prefix="prom_stress_")
        try:
            with contextlib.redirect_stdout(io.StringIO()):  # update_memory_fact prints per fact
                problems = run_round(workdir, args.writers, args.per_writer, args.readers)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        if any(problems.values()):
            failed_rounds += 1
        for k, v in problems.items():
            totals[k] += v

    mode = "LEGACY (simulated old behaviour)" if args.legacy else "FIXED (current code)"
    print(f"mode: {mode}")
    print(f"rounds: {args.rounds}  writers: {args.writers}  facts/writer: {args.per_writer}  readers: {args.readers}")
    print(f"failed rounds: {failed_rounds} / {args.rounds}")
    for k, v in totals.items():
        print(f"  {k}: {v}")
    if failed_rounds and not args.legacy:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS" if not failed_rounds else "RESULT: (legacy mode - failures are the expected demonstration)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
