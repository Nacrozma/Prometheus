"""Core changes for the desktop app: a separate data folder and workspace (opt-in through the
environment, defaults unchanged), and a router that can be rebuilt after keys change."""
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEYS = ("OPENROUTER_API_KEY", "GROQ_API_KEY", "CEREBRAS_API_KEY")


def run(code: str, **env) -> dict:
    """Import prometheus in a fresh interpreter (its import has side effects) and return JSON."""
    e = {k: v for k, v in os.environ.items() if k not in KEYS and not k.startswith("PROMETHEUS_")}
    e.update({"PROMETHEUS_FAST_BOOT": "1", "PYTHONPATH": HERE, **env})
    out = subprocess.run([sys.executable, "-c", textwrap.dedent(code)], env=e, capture_output=True, text=True, timeout=120, cwd=env.get("CWD", HERE))
    if out.returncode != 0:
        raise AssertionError(out.stderr[-2000:])
    return json.loads(out.stdout.strip().splitlines()[-1])


class DataAndWorkspaceFolders(unittest.TestCase):
    def test_defaults_are_unchanged(self):
        r = run("import json, prometheus as p; print(json.dumps([p.DATA_DIR, p.WORKSPACE_DIR, p.BASE_DIR, p.MEMORY_FILE]))")
        self.assertEqual(r[0], r[2])
        self.assertEqual(r[1], r[2])
        self.assertEqual(r[3], os.path.join(r[2], "memory.json"))

    def test_state_goes_to_the_data_folder_and_tools_stay_in_the_workspace(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as ws:
            r = run(
                """
                import json, os, prometheus as p
                inside = p.dispatch_tool("write_file", {"path": "notes/a.txt", "content": "hi"})
                outside = p.dispatch_tool("write_file", {"path": os.path.join(p.BASE_DIR, "planted.txt"), "content": "x"})
                files = {k: getattr(p, k) for k in ("MEMORY_FILE", "AUDIT_FILE", "SESSIONS_DIR", "PERMISSIONS_FILE", "SCHEDULE_FILE", "USAGE_LOG_FILE", "LOG_FILE")}
                print(json.dumps({"inside": inside["status"], "outside": outside["status"], "files": files, "ws": p.WORKSPACE_DIR}))
                """,
                PROMETHEUS_HOME=home,
                PROMETHEUS_WORKSPACE=ws,
            )
            for name, path in r["files"].items():
                self.assertTrue(os.path.realpath(path).startswith(os.path.realpath(home)), (name, path))
            self.assertEqual(os.path.realpath(r["ws"]), os.path.realpath(ws))
            self.assertEqual(r["inside"], "success")
            self.assertEqual(open(os.path.join(ws, "notes", "a.txt")).read(), "hi")
            self.assertNotEqual(r["outside"], "success", "the source folder is outside the workspace")
            self.assertFalse(os.path.exists(os.path.join(HERE, "planted.txt")))
            self.assertTrue(os.path.exists(os.path.join(home, "prometheus.log")), "the log is written in the data folder")


class RouterReload(unittest.TestCase):
    def test_a_key_added_later_takes_effect_without_a_restart(self):
        r = run(
            """
            import json, os, prometheus as p
            from prometheus import llm_router as held  # how gui_orb.py imports it
            before = list(p.llm_router.active_providers)
            os.environ["GROQ_API_KEY"] = "gsk_test_placeholder"
            p.llm_router.reload()
            print(json.dumps({"before": before, "after": held.active_providers, "same": held is p.llm_router, "configured": held.configured}))
            """
        )
        self.assertEqual(r["before"], ["ollama"], "with no keys only local Ollama is assumed")
        self.assertIn("groq", r["after"])
        self.assertTrue(r["same"] and r["configured"])

    def test_the_unconfigured_stand_in_answers_status_and_refuses_calls(self):
        r = run(
            """
            import json, prometheus as p
            u = p._UnconfiguredRouter("no providers")
            status = [u.active_providers, u._ranked_candidates(), u.cooldowns_remaining(), u.usage_summary(), u.configured]
            try:
                u.chat_completion([])
                refused = False
            except RuntimeError as e:
                refused = str(e) == "no providers"
            print(json.dumps({"status": status, "refused": refused}))
            """
        )
        self.assertEqual(r["status"], [[], [], {}, {}, False])
        self.assertTrue(r["refused"])


if __name__ == "__main__":
    unittest.main()
