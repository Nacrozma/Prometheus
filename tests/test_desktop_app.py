"""The desktop layer (app/): start-up path rules, credentials, settings, single instance, and an
offscreen smoke test of the whole window run in a separate process with throwaway folders."""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import bootstrap  # noqa: E402
from app.credentials import KNOWN_KEYS, SERVICE, CredentialError, CredentialStore, mask  # noqa: E402
from app.platform.base import Platform  # noqa: E402
from app.settings import DesktopSettings  # noqa: E402

try:
    import PyQt6  # noqa: F401

    HAVE_QT = True
except ImportError:
    HAVE_QT = False


class FakePlatform(Platform):
    name = "test"

    def __init__(self, root):
        self.root = root

    def data_dir(self):
        return self._ensure(os.path.join(self.root, "userdata"))

    def default_workspace(self):
        return self._ensure(os.path.join(self.root, "Documents", "Prometheus Workspace"))

    def credential_backend(self):
        return "test store"

    def launch_at_login(self):
        return False

    def set_launch_at_login(self, enabled, command):
        pass


class FakeKeyring:
    def __init__(self):
        self.store = {}

    def get_password(self, service, name):
        return self.store.get((service, name))

    def set_password(self, service, name, value):
        self.store[(service, name)] = value

    def delete_password(self, service, name):
        self.store.pop((service, name), None)


class EnvGuard(unittest.TestCase):
    KEYS = ("PROMETHEUS_HOME", "PROMETHEUS_WORKSPACE", *KNOWN_KEYS)

    def setUp(self):
        self.saved = {k: os.environ.get(k) for k in self.KEYS}
        for k in self.KEYS:
            os.environ.pop(k, None)
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class TestPaths(EnvGuard):
    def test_fresh_install_uses_per_user_folder_and_documents(self):
        src = os.path.join(self.tmp, "src")
        os.makedirs(src)
        p = bootstrap.resolve_paths(FakePlatform(self.tmp), source_dir=src, is_frozen=False)
        self.assertEqual(p.data_dir, os.path.join(self.tmp, "userdata"))
        self.assertTrue(p.workspace.endswith("Prometheus Workspace"))
        self.assertEqual(p.data_reason, "per-user folder")

    def test_source_checkout_with_existing_data_stays_in_place(self):
        src = os.path.join(self.tmp, "src")
        os.makedirs(src)
        with open(os.path.join(src, "memory.json"), "w") as f:
            f.write("[]")
        p = bootstrap.resolve_paths(FakePlatform(self.tmp), source_dir=src, is_frozen=False)
        self.assertEqual((p.data_dir, p.workspace), (src, src))
        self.assertTrue(p.notes)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "userdata")), "nothing created or copied elsewhere")

    def test_packaged_app_ignores_its_install_folder(self):
        src = os.path.join(self.tmp, "src")
        os.makedirs(src)
        open(os.path.join(src, "memory.json"), "w").close()
        p = bootstrap.resolve_paths(FakePlatform(self.tmp), source_dir=src, is_frozen=True)
        self.assertEqual(p.data_dir, os.path.join(self.tmp, "userdata"))

    def test_environment_wins_then_chosen_workspace(self):
        os.environ["PROMETHEUS_HOME"] = os.path.join(self.tmp, "envhome")
        chosen = os.path.join(self.tmp, "chosen")
        p = bootstrap.resolve_paths(FakePlatform(self.tmp), chosen_workspace=chosen, source_dir=self.tmp, is_frozen=False)
        self.assertEqual(p.data_dir, os.path.join(self.tmp, "envhome"))
        self.assertEqual((p.workspace, p.workspace_reason), (chosen, "chosen in Settings"))
        os.environ["PROMETHEUS_WORKSPACE"] = os.path.join(self.tmp, "envws")
        p = bootstrap.resolve_paths(FakePlatform(self.tmp), chosen_workspace=chosen, source_dir=self.tmp, is_frozen=False)
        self.assertEqual(p.workspace, os.path.join(self.tmp, "envws"))


class TestCredentials(EnvGuard):
    def test_round_trip_sets_environment_and_never_returns_plain_status(self):
        kr = FakeKeyring()
        c = CredentialStore(kr)
        c.set("GROQ_API_KEY", "  gsk_abcdefghijklmnop1234 ")
        self.assertEqual(kr.store[(SERVICE, "GROQ_API_KEY")], "gsk_abcdefghijklmnop1234")
        self.assertEqual(os.environ["GROQ_API_KEY"], "gsk_abcdefghijklmnop1234")
        st = c.status()["GROQ_API_KEY"]
        self.assertEqual(st["source"], "credential store")
        self.assertNotIn("abcdefghijklmnop", json.dumps(c.status()))
        c.delete("GROQ_API_KEY")
        self.assertNotIn("GROQ_API_KEY", os.environ)
        self.assertEqual(c.status()["GROQ_API_KEY"]["source"], "not set")

    def test_environment_or_dotenv_key_wins_over_store(self):
        kr = FakeKeyring()
        kr.store[(SERVICE, "OPENROUTER_API_KEY")] = "stored-key-000000000"
        os.environ["OPENROUTER_API_KEY"] = "env-key-1111111111111"
        loaded = CredentialStore(kr).load_into_environ()
        self.assertEqual(loaded, [])
        self.assertEqual(os.environ["OPENROUTER_API_KEY"], "env-key-1111111111111")
        os.environ.pop("OPENROUTER_API_KEY")
        self.assertEqual(CredentialStore(kr).load_into_environ(), ["OPENROUTER_API_KEY"])

    def test_dotenv_in_data_folder_wins_over_store_at_start(self):
        from app.application import load_keys

        kr = FakeKeyring()
        kr.store[(SERVICE, "GROQ_API_KEY")] = "stored-key-000000000"
        kr.store[(SERVICE, "CEREBRAS_API_KEY")] = "stored-cerebras-0000"
        with open(os.path.join(self.tmp, ".env"), "w") as f:
            f.write("GROQ_API_KEY=dotenv-key-111111111\n")
        load_keys(self.tmp, CredentialStore(kr))
        self.assertEqual(os.environ["GROQ_API_KEY"], "dotenv-key-111111111")
        self.assertEqual(os.environ["CEREBRAS_API_KEY"], "stored-cerebras-0000", "the store fills gaps")

    def test_rejects_bad_input_unknown_names_and_reports_unavailable_store(self):
        c = CredentialStore(FakeKeyring())
        for bad in ("", "has space", "x" * 600):
            with self.assertRaises(CredentialError):
                c.set("GROQ_API_KEY", bad)
        with self.assertRaises(CredentialError):
            c.set("PATH", "abc")
        broken = CredentialStore.__new__(CredentialStore)
        broken._kr, broken.error = None, "no store"
        self.assertFalse(broken.available)
        with self.assertRaises(CredentialError):
            broken.set("GROQ_API_KEY", "abcdef")
        self.assertEqual(broken.load_into_environ(), [])

    def test_errors_do_not_echo_the_key(self):
        class Exploding(FakeKeyring):
            def set_password(self, *a):
                raise RuntimeError("backend says " + a[2])

        with self.assertRaises(CredentialError) as cm:
            CredentialStore(Exploding()).set("GROQ_API_KEY", "secret-value-123456")
        self.assertNotIn("secret-value", str(cm.exception))
        self.assertEqual(mask("short"), "••••")
        self.assertEqual(mask("abcd1234567890wxyz"), "abcd…wxyz")


class TestSettings(EnvGuard):
    def test_defaults_types_and_persistence(self):
        s = DesktopSettings(self.tmp)
        self.assertFalse(s.get("auto_approve"), "auto-approve is never on by default")
        self.assertFalse(s.get("launch_at_login"))
        s.set("close_to_tray", True)
        with self.assertRaises(TypeError):
            s.set("close_to_tray", "yes")
        with self.assertRaises(KeyError):
            s.set("api_key", "x")
        self.assertTrue(DesktopSettings(self.tmp).get("close_to_tray"))
        with open(s.path) as f:
            self.assertNotIn("api_key", f.read())

    def test_corrupt_file_is_quarantined_not_deleted(self):
        path = os.path.join(self.tmp, "desktop_settings.json")
        with open(path, "w") as f:
            f.write("{not json")
        s = DesktopSettings(self.tmp)
        self.assertTrue(s.load_error)
        self.assertFalse(s.get("close_to_tray"))
        kept = [n for n in os.listdir(self.tmp) if n.startswith("desktop_settings.json") and n != "desktop_settings.json"]
        self.assertTrue(kept, "the unreadable file is kept for recovery")

    def test_wrong_types_in_file_fall_back_to_defaults(self):
        with open(os.path.join(self.tmp, "desktop_settings.json"), "w") as f:
            json.dump({"auto_approve": "true", "close_to_tray": True, "unknown": 1}, f)
        s = DesktopSettings(self.tmp)
        self.assertIs(s.get("auto_approve"), False)
        self.assertIs(s.get("close_to_tray"), True)


@unittest.skipUnless(HAVE_QT, "PyQt6 not installed")
class TestSingleInstance(unittest.TestCase):
    def test_second_launch_activates_first(self):
        from PyQt6.QtCore import QCoreApplication, QElapsedTimer

        from app.single_instance import SingleInstance

        app = QCoreApplication.instance() or QCoreApplication([])
        name = f"prometheus-test-{os.getpid()}"
        first = SingleInstance(name)
        self.assertFalse(first.already_running())
        self.assertTrue(first.listen())
        hits = []
        first.activated.connect(lambda: hits.append(1))
        self.assertTrue(SingleInstance(name).already_running())
        t = QElapsedTimer()
        t.start()
        while not hits and t.elapsed() < 3000:
            app.processEvents()
        first.close()
        self.assertEqual(hits, [1])


class TestImport(unittest.TestCase):
    def setUp(self):
        from app import migration

        self.m = migration
        self.src, self.dst = tempfile.mkdtemp(), tempfile.mkdtemp()
        files = {"memory_graph.json": '{"facts": [1]}', "audit.jsonl": '{"a":1}\n', "sessions/s1.json": "[]", "skills.json": "{broken", ".env": "GROQ_API_KEY=secret"}
        for rel, body in files.items():
            os.makedirs(os.path.dirname(os.path.join(self.src, rel)), exist_ok=True)
            with open(os.path.join(self.src, rel), "w") as f:
                f.write(body)
        with open(os.path.join(self.dst, "memory_graph.json"), "w") as f:
            f.write('{"facts": ["old"]}')

    def snapshot(self, root):
        out = {}
        for d, _, names in os.walk(root):
            for n in names:
                with open(os.path.join(d, n)) as f:
                    out[os.path.relpath(os.path.join(d, n), root)] = f.read()
        return out

    def test_import_backs_up_copies_verifies_and_leaves_source_alone(self):
        before = self.snapshot(self.src)
        plan = self.m.plan(self.src, self.dst)
        self.assertIn("skills.json", plan.invalid)
        self.assertTrue(plan.skipped_env)
        self.assertEqual(plan.replaces, ["memory_graph.json"])
        backup = self.m.apply(plan)
        with open(os.path.join(backup, "memory_graph.json")) as f:
            self.assertIn("old", f.read())
        after = self.snapshot(self.dst)
        self.assertEqual(after["memory_graph.json"], '{"facts": [1]}')
        self.assertIn(os.path.join("sessions", "s1.json"), after)
        self.assertNotIn(".env", after, "keys are never copied")
        self.assertNotIn("skills.json", after, "unreadable state is not imported")
        self.assertEqual(self.snapshot(self.src), before, "the source is never changed")

    def test_failed_copy_rolls_back(self):
        plan = self.m.plan(self.src, self.dst)
        real = self.m._sha
        calls = {"n": 0}

        def flaky(path):
            calls["n"] += 1
            if path.endswith(".importing") and calls["n"] > 4:
                return "mismatch"
            return real(path)

        self.m._sha = flaky
        try:
            with self.assertRaises(self.m.MigrationError):
                self.m.apply(plan)
        finally:
            self.m._sha = real
        after = self.snapshot(self.dst)
        self.assertEqual(after["memory_graph.json"], '{"facts": ["old"]}')
        self.assertFalse([k for k in after if k.endswith(".importing") or k.startswith("sessions")])

    def test_refuses_same_folder_and_empty_folder(self):
        with self.assertRaises(self.m.MigrationError):
            self.m.plan(self.dst, self.dst)
        with self.assertRaises(self.m.MigrationError):
            self.m.plan(tempfile.mkdtemp(), self.dst)


class TestChildPython(unittest.TestCase):
    """The packaged exe must act as Python for the core's child processes (run_code, Forge tests)."""

    def test_script_and_module_forms(self):
        from app.launcher import _child_python

        tmp = tempfile.mkdtemp()
        script = os.path.join(tmp, "child.py")
        out = os.path.join(tmp, "out.txt")
        with open(script, "w") as f:
            f.write("import sys\nopen(sys.argv[1], 'w').write('ran')\nsys.exit(3)\n")
        saved = list(sys.argv)
        try:
            self.assertEqual(_child_python(["Prometheus.exe", "-I", script, out]), 3)
            with open(out) as f:
                self.assertEqual(f.read(), "ran")
            self.assertIsNone(_child_python(["Prometheus.exe"]))
            self.assertIsNone(_child_python(["Prometheus.exe", "--self-test=x"]))
            self.assertEqual(_child_python(["Prometheus.exe", "-m", "json.tool", "--help"]), 0)
        finally:
            sys.argv = saved


@unittest.skipUnless(HAVE_QT, "PyQt6 not installed")
class TestLauncherScript(unittest.TestCase):
    def test_launcher_run_as_a_script_passes_its_self_test(self):
        # The source-mode "start at sign-in" entry runs app/launcher.py directly; app/platform must
        # not hide the standard library's platform module, and the self-test must never block.
        tmp = tempfile.mkdtemp()
        env = dict(os.environ, PROMETHEUS_HOME=os.path.join(tmp, "h"), PROMETHEUS_WORKSPACE=os.path.join(tmp, "w"))
        for k in KNOWN_KEYS:
            env.pop(k, None)
        report = os.path.join(tmp, "r.json")
        r = subprocess.run([sys.executable, os.path.join(ROOT, "app", "launcher.py"), f"--self-test={report}"], env=env, capture_output=True, text=True, timeout=180, cwd=tmp)
        self.assertTrue(os.path.exists(report), r.stderr[-2000:])
        with open(report) as f:
            out = json.load(f)
        self.assertTrue(out["ok"], out)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(out["calc"]["results"]["value"], 25.4)

    def test_queued_import_runs_at_start_before_the_core_loads(self):
        tmp = tempfile.mkdtemp()
        home, src = os.path.join(tmp, "h"), os.path.join(tmp, "old")
        os.makedirs(home)
        os.makedirs(os.path.join(src, "sessions"))
        with open(os.path.join(src, "memory_graph.json"), "w") as f:
            json.dump({"facts": [], "marker": "imported"}, f)
        with open(os.path.join(src, "sessions", "s.json"), "w") as f:
            f.write("[]")
        with open(os.path.join(home, "desktop_settings.json"), "w") as f:
            json.dump({"pending_import": src}, f)
        env = dict(os.environ, PROMETHEUS_HOME=home, PROMETHEUS_WORKSPACE=os.path.join(tmp, "w"))
        r = subprocess.run([sys.executable, "-m", "app.launcher", f"--self-test={os.path.join(tmp, 'r.json')}"], env=env, capture_output=True, text=True, timeout=180, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        with open(os.path.join(home, "memory_graph.json")) as f:
            self.assertIn("imported", f.read(), "the core kept the imported memory")
        self.assertTrue(os.path.exists(os.path.join(home, "sessions", "s.json")))
        with open(os.path.join(home, "desktop_settings.json")) as f:
            self.assertEqual(json.load(f)["pending_import"], "", "an import is attempted once")


SMOKE = textwrap.dedent(
    """
    import json, os, sys
    sys.path.insert(0, {root!r})
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication
    import app.application as A
    out = {{}}
    def check():
        app = QApplication.instance()
        win = [w for w in app.topLevelWidgets() if w.__class__.__name__ == "MainWindow"][0]
        out["pages"] = list(win.pages)
        errors = []
        for name in win.pages:
            win.go(name)
            app.processEvents()
            msg = win.statusBar().currentMessage()
            if msg.startswith("Could not refresh"):
                errors.append(msg)
        out["errors"] = errors
        # A dangerous tool must still raise an approval card and wait; denying it is passed to the worker.
        comp = win.companion
        class W:
            answer = None
            def provide_confirmation(self, ok): self.answer = ok
            def isRunning(self): return True
            def request_stop(self): pass
        comp.worker = W()
        comp._confirm("write_file", json.dumps({{"path": "x.txt", "content": "<b>hi</b>"}}))
        out["card"] = comp.card is not None
        comp.card.answered.emit(False)
        out["denied_passed"] = comp.worker.answer is False
        comp.worker = None
        out["dangerous"] = win.core.is_dangerous("write_file") and win.core.is_dangerous("execute_shell")
        out["auto_default"] = win.settings.get("auto_approve")
        print("RESULT" + json.dumps(out))
        win.quit()
    _orig = QApplication.exec
    QApplication.exec = lambda self: (QTimer.singleShot(1500, check), _orig())[1]
    sys.exit(A.main(["prometheus"]))
    """
)


@unittest.skipUnless(HAVE_QT, "PyQt6 not installed")
class TestWindowSmoke(unittest.TestCase):
    def test_every_page_opens_and_approvals_still_gate_tools(self):
        tmp = tempfile.mkdtemp()
        env = dict(os.environ, PROMETHEUS_HOME=os.path.join(tmp, "home"), PROMETHEUS_WORKSPACE=os.path.join(tmp, "ws"), QT_QPA_PLATFORM="offscreen")
        for k in KNOWN_KEYS:
            env.pop(k, None)
        script = os.path.join(tmp, "smoke.py")
        with open(script, "w") as f:
            f.write(SMOKE.format(root=ROOT))
        r = subprocess.run([sys.executable, script], env=env, capture_output=True, text=True, timeout=180, cwd=tmp)
        line = next((l for l in r.stdout.splitlines() if l.startswith("RESULT")), None)
        self.assertIsNotNone(line, f"no result; exit {r.returncode}\n{r.stdout[-2000:]}\n{r.stderr[-3000:]}")
        out = json.loads(line[6:])
        self.assertEqual(len(out["pages"]), 11)
        self.assertEqual(out["errors"], [])
        self.assertTrue(out["card"])
        self.assertTrue(out["denied_passed"])
        self.assertTrue(out["dangerous"])
        self.assertFalse(out["auto_default"])
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        # nothing was written next to the source code
        self.assertFalse(os.path.exists(os.path.join(tmp, "home", ".env")))


if __name__ == "__main__":
    unittest.main()
