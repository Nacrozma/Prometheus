"""Voice input set up from inside Prometheus (whisper.cpp): downloads, checksums, extraction, transcription."""

import hashlib
import io
import os
import sys
import tempfile
import threading
import unittest
import zipfile
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.services import local_stt as L  # noqa: E402


class FakeResponse(io.BytesIO):
    def __init__(self, data: bytes):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def opener_for(payloads):
    def op(req, timeout=60):
        return FakeResponse(payloads[req.full_url])

    return op


def asset(data: bytes, url="https://huggingface.co/x/model.bin", size_mb=1):
    return L.Asset("t", "Test file", url, hashlib.sha256(data).hexdigest(), size_mb)


def engine_zip(extra=None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Release/whisper-cli.exe", b"MZ fake")
        z.writestr("Release/whisper.dll", b"dll")
        z.writestr("Release/readme.txt", b"not copied")
        z.writestr("Release/../../evil.exe", b"escape")
        z.writestr("Other/tool.exe", b"outside Release")
        for k, v in (extra or {}).items():
            z.writestr(k, v)
    return buf.getvalue()


class TestDownloads(unittest.TestCase):
    def test_good_download_is_verified_and_moved_into_place(self):
        data = b"model bytes" * 1000
        a = asset(data)
        with tempfile.TemporaryDirectory() as d:
            seen = []
            dest = L.download(a, os.path.join(d, "m.bin"), lambda g, t: seen.append((g, t)), opener=opener_for({a.url: data}))
            self.assertEqual(open(dest, "rb").read(), data)
            self.assertEqual(seen[-1], (len(data), len(data)))
            self.assertFalse(os.path.exists(dest + ".part"))

    def test_checksum_mismatch_deletes_everything(self):
        a = asset(b"expected")
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(L.SetupError, "checksum"):
                L.download(a, os.path.join(d, "m.bin"), opener=opener_for({a.url: b"tampered"}))
            self.assertEqual(os.listdir(d), [])

    def test_unknown_host_cancel_and_oversize(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(L.SetupError, "unknown host"):
                L.download(L.Asset("x", "x", "http://example.com/x", "0" * 64, 1), os.path.join(d, "x"))
            data = b"x" * 200_000
            a = asset(data)
            ev = threading.Event()
            ev.set()
            with self.assertRaises(L.Cancelled):
                L.download(a, os.path.join(d, "m.bin"), cancel=ev, opener=opener_for({a.url: data}))
            big = b"y" * (66 * 1024 * 1024)
            with self.assertRaisesRegex(L.SetupError, "larger than expected"):
                L.download(asset(big, size_mb=1), os.path.join(d, "b.bin"), opener=opener_for({asset(big).url: big}))
            self.assertEqual(os.listdir(d), [])

    def test_every_pinned_asset_is_https_on_a_known_host_with_sha256(self):
        for a in [L.ENGINE_WINDOWS, *L.MODELS.values()]:
            self.assertTrue(a.url.startswith(L.ALLOWED_HOSTS), a.url)
            self.assertEqual(len(a.sha256), 64)


class TestEngine(unittest.TestCase):
    def test_extraction_keeps_only_release_binaries(self):
        with tempfile.TemporaryDirectory() as d:
            z = os.path.join(d, "e.zip")
            open(z, "wb").write(engine_zip())
            with mock.patch.object(L, "copy_runtime", return_value=[]):
                exe = L.extract_engine(z, d)
            self.assertTrue(exe.endswith("whisper-cli.exe"))
            self.assertEqual(sorted(os.listdir(L.engine_dir(d))), ["whisper-cli.exe", "whisper.dll"])
            self.assertFalse(os.path.exists(os.path.join(d, "evil.exe")))

    def test_runtime_dlls_are_copied_only_by_name_from_given_folders(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "app", "Qt6", "bin")
            os.makedirs(src)
            for n in ("MSVCP140.dll", "vcruntime140.dll", "vcruntime140_1.dll", "other.dll"):
                open(os.path.join(src, n), "wb").write(b"x")
            dst = os.path.join(d, "engine")
            os.makedirs(dst)
            copied = L.copy_runtime(dst, [os.path.join(d, "app")])
            self.assertEqual(sorted(copied), sorted(L.RUNTIME_DLLS))
            self.assertNotIn("other.dll", os.listdir(dst))

    def test_archive_without_the_cli_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as zf:
                zf.writestr("Release/main.exe", b"x")
            z = os.path.join(d, "e.zip")
            open(z, "wb").write(buf.getvalue())
            with self.assertRaisesRegex(L.SetupError, "whisper-cli"):
                L.extract_engine(z, d)
            self.assertFalse(os.path.exists(L.engine_dir(d)))

    def test_full_setup_on_windows_downloads_engine_then_model(self):
        zdata = engine_zip()
        model = b"ggml" * 500
        eng = L.Asset("e", "engine", "https://github.com/x/e.zip", hashlib.sha256(zdata).hexdigest(), 1)
        mod = L.Asset("tiny", "Tiny", "https://huggingface.co/x/tiny.bin", hashlib.sha256(model).hexdigest(), 1)
        with tempfile.TemporaryDirectory() as d, mock.patch.object(L.sys, "platform", "win32"), mock.patch.object(L, "ENGINE_WINDOWS", eng), mock.patch.dict(L.MODELS, {"tiny": mod}), mock.patch.object(L.shutil, "which", return_value=None):
            stages = []
            st = L.setup(d, "tiny", lambda s, g, t: stages.append(s), opener=opener_for({eng.url: zdata, mod.url: model}))
            self.assertTrue(st["ready"])
            self.assertEqual(st["model"], "tiny")
            self.assertEqual(sorted(set(stages)), ["engine", "model"])
            self.assertFalse(os.path.exists(os.path.join(L.folder(d), "downloads", "whisper-bin-x64.zip")), "the zip is removed after extraction")
            L.remove(d)
            self.assertFalse(L.status(d)["ready"])

    def test_other_systems_need_whisper_cli_on_path(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(L.sys, "platform", "linux"), mock.patch.object(L.shutil, "which", return_value=None):
            with self.assertRaisesRegex(L.SetupError, "PATH"):
                L.setup(d, "base")
            self.assertIn("PATH", L.status(d)["text"])


class TestTranscribe(unittest.TestCase):
    def test_runs_the_engine_on_a_temporary_wav_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.dirname(L.model_path(d, "base")))
            open(L.model_path(d, "base"), "wb").write(b"m")
            seen = {}

            def runner(cmd, **kw):
                seen["cmd"] = cmd
                wav = cmd[cmd.index("-f") + 1]
                seen["wav"] = wav
                self.assertTrue(os.path.getsize(wav) > 44)
                open(cmd[cmd.index("-of") + 1] + ".txt", "w").write(" Hello there. [BLANK_AUDIO] (music)\n")
                return mock.Mock(returncode=0, stdout="", stderr="")

            with mock.patch.object(L, "find_engine", return_value="/bin/whisper-cli"):
                text = L.transcribe(d, [0.0, 0.5, -0.5] * 8000, runner=runner)
            self.assertEqual(text, "Hello there.")
            self.assertIn("-nt", seen["cmd"])
            self.assertFalse(os.path.exists(seen["wav"]), "the recording is deleted")

    def test_failure_and_missing_setup_are_reported(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(L.SetupError, "not set up"):
                L.transcribe(d, [0.0])
            os.makedirs(os.path.dirname(L.model_path(d, "tiny")))
            open(L.model_path(d, "tiny"), "wb").write(b"m")
            with mock.patch.object(L, "find_engine", return_value="/bin/whisper-cli"):
                with self.assertRaisesRegex(L.SetupError, "exit 3"):
                    L.transcribe(d, [0.0] * 100, runner=lambda cmd, **kw: mock.Mock(returncode=3, stdout="", stderr="bad model"))


try:
    import PyQt6  # noqa: F401

    HAVE_QT = True
except Exception:
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, "PyQt6 not installed")
class TestDialog(unittest.TestCase):
    def test_dialog_offers_models_and_voice_input_falls_back_cleanly(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        from app.ui.voice_setup import LocalVoiceThread, VoiceSetupDialog, make_voice_input, voice_input_text

        with tempfile.TemporaryDirectory() as d:
            dlg = VoiceSetupDialog(d)
            self.assertEqual(dlg.model_id(), "base", "Base is preselected")
            self.assertEqual(len(dlg.group.buttons()), 3)
            os.makedirs(os.path.dirname(L.model_path(d, "tiny")))
            open(L.model_path(d, "tiny"), "wb").write(b"m")
            with mock.patch.object(L, "find_engine", return_value="/bin/whisper-cli"):
                v = make_voice_input(d)
            self.assertIsInstance(v, LocalVoiceThread)
            self.assertIn("whisper.cpp", voice_input_text(v))
            self.assertIn("Set up voice input", voice_input_text(None))
        app.processEvents()


if __name__ == "__main__":
    unittest.main()
