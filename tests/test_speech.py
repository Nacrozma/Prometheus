"""Spoken replies: local engine setup (downloads, checksums, safe extraction), text preparation, the shared
speech service (queue, stop, no fallback, honest test), and preference migration."""

import hashlib
import io
import os
import sys
import tarfile
import tempfile
import threading
import time
import unittest
import wave
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.services import speech as S  # noqa: E402
from app.services.local_stt import Asset  # noqa: E402


class FakeResponse(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def tar_bytes(entries, links=()):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:bz2") as t:
        for name, data in entries.items():
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            ti.mode = 0o755
            t.addfile(ti, io.BytesIO(data))
        for name, target in links:
            ti = tarfile.TarInfo(name)
            ti.type = tarfile.SYMTYPE
            ti.linkname = target
            t.addfile(ti)
    return buf.getvalue()


def wav_bytes(seconds=0.5, sr=22050):
    import array
    import math

    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(array.array("h", (int(8000 * math.sin(i / 10)) for i in range(int(sr * seconds)))).tobytes())
    return b.getvalue()


def runtime_archive(top, exe):
    return tar_bytes({f"{top}/bin/{exe}": b"ELF", f"{top}/lib/libonnxruntime.so": b"so", f"{top}/lib/x.dll": b"dll", f"{top}/README": b"no", f"{top}/../evil": b"x"}, links=[(f"{top}/lib/link.so", "/etc/passwd")])


def voice_archive(vid):
    return tar_bytes({f"vits-piper-{vid}/{vid}.onnx": b"model", f"vits-piper-{vid}/tokens.txt": b"a 1", f"vits-piper-{vid}/espeak-ng-data/phontab": b"p", f"vits-piper-{vid}/other.bin": b"no"})


class TestLocalSetup(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        top = "sherpa-onnx-v1.12.40-linux-x64-shared"
        self.rt_data = runtime_archive(top, "sherpa-onnx-offline-tts")
        self.rt = Asset("rt", "engine", f"https://github.com/x/{top}.tar.bz2", hashlib.sha256(self.rt_data).hexdigest(), 1)
        self.vid = "en_GB-alba-medium"
        self.v_data = voice_archive(self.vid)
        v = S.LOCAL_VOICES[self.vid]
        self.voice = S.LocalVoice(v.id, v.name, v.language, v.character, Asset(self.vid, "voice", f"https://github.com/x/vits-piper-{self.vid}.tar.bz2", hashlib.sha256(self.v_data).hexdigest(), 1), v.licence)
        self.patches = [mock.patch.object(S.sys, "platform", "linux"), mock.patch.dict(S.RUNTIMES, {"linux": self.rt}), mock.patch.dict(S.LOCAL_VOICES, {self.vid: self.voice})]
        for p in self.patches:
            p.start()
        self.opener = lambda req, timeout=60: FakeResponse({self.rt.url: self.rt_data, self.voice.asset.url: self.v_data}[req.full_url])

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_setup_installs_only_expected_files_and_reports_ready(self):
        stages = []
        st = S.setup_local(self.d, [self.vid], lambda s, g, t: stages.append(s), opener=self.opener)
        self.assertTrue(st["ready"], st)
        self.assertEqual(st["voices"], [self.vid])
        self.assertEqual(sorted(set(stages)), sorted(["engine", self.vid]))
        eng = S.runtime_dir(self.d)
        self.assertTrue(os.path.isfile(os.path.join(eng, "bin", "sherpa-onnx-offline-tts")))
        self.assertFalse(os.path.exists(os.path.join(eng, "README")))
        self.assertFalse(os.path.lexists(os.path.join(eng, "lib", "link.so")), "links are never extracted")
        self.assertFalse(os.path.exists(os.path.join(self.d, "evil")))
        self.assertFalse(os.path.exists(os.path.join(S.voice_dir(self.d, self.vid), "other.bin")))
        self.assertFalse(os.listdir(os.path.join(S.folder(self.d), "downloads")), "archives are removed after install")

    def test_checksum_mismatch_installs_nothing(self):
        bad = lambda req, timeout=60: FakeResponse(b"tampered")  # noqa: E731
        with self.assertRaisesRegex(S.SetupError, "checksum"):
            S.setup_local(self.d, [self.vid], opener=bad)
        self.assertFalse(S.local_status(self.d)["engine"])

    def test_cancel_keeps_nothing_half_downloaded(self):
        ev = threading.Event()
        ev.set()
        with self.assertRaises(S.Cancelled):
            S.setup_local(self.d, [self.vid], cancel=ev, opener=self.opener)
        self.assertFalse(S.local_status(self.d)["ready"])
        self.assertFalse([f for f in os.listdir(os.path.join(S.folder(self.d), "downloads")) if f.endswith(".part")])

    def test_not_enough_disk_space(self):
        with mock.patch.object(S.shutil, "disk_usage", return_value=mock.Mock(free=1024)):
            with self.assertRaisesRegex(S.SetupError, "disk space"):
                S.setup_local(self.d, [self.vid], opener=self.opener)

    def test_remove_one_voice_or_everything_without_touching_voice_input(self):
        S.setup_local(self.d, [self.vid], opener=self.opener)
        stt = os.path.join(self.d, "voice", "models")
        os.makedirs(stt)
        open(os.path.join(stt, "ggml-base.bin"), "wb").write(b"m")
        S.remove_local(self.d, self.vid)
        self.assertEqual(S.installed_voices(self.d), [])
        self.assertTrue(S.local_status(self.d)["engine"])
        S.remove_local(self.d)
        self.assertFalse(os.path.exists(S.folder(self.d)))
        self.assertTrue(os.path.exists(os.path.join(stt, "ggml-base.bin")), "Whisper files are not deleted")

    def test_every_pinned_asset_is_https_github_with_sha256(self):
        for a in [*S.RUNTIMES.values(), *(v.asset for v in S.LOCAL_VOICES.values())]:
            self.assertTrue(a.url.startswith("https://github.com/"), a.url)
            self.assertEqual(len(a.sha256), 64)


class TestText(unittest.TestCase):
    def test_speakable_drops_code_links_markup_and_payloads(self):
        t = S.speakable('## Plan\nHere is **the** plan.\n```orbit-plan {"title": "x"}```\nSee [docs](https://x.y) or https://a.b/c.\n- run `pytest`\n{"a": 1, "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb": 2}')
        self.assertEqual(t, "Plan Here is the plan. See docs or a link. run pytest")
        self.assertEqual(S.speakable("Talking ```py\nprint(1)"), "Talking")

    def test_chunks_respect_the_limit_and_keep_every_word(self):
        text = "First sentence. " + "word " * 200 + "end. Short one."
        cs = S.chunks(text, 120)
        self.assertTrue(all(len(c) <= 120 for c in cs))
        self.assertEqual(" ".join(cs).split(), text.split())

    def test_speed_is_clamped(self):
        self.assertEqual(S.clamp_speed(5), S.SPEED_MAX)
        self.assertEqual(S.clamp_speed("x"), 1.0)
        self.assertEqual(S.clamp_speed(0.1), S.SPEED_MIN)


class TestLocalEngine(unittest.TestCase):
    def test_synth_runs_the_engine_with_the_voice_and_speed_and_cleans_up(self):
        d = tempfile.mkdtemp()
        vid = "en_GB-alba-medium"
        vd = S.voice_dir(d, vid)
        os.makedirs(os.path.join(vd, "espeak-ng-data"))
        open(os.path.join(vd, f"{vid}.onnx"), "wb").write(b"m")
        open(os.path.join(vd, "tokens.txt"), "w").write("a")
        seen = {}

        def runner(cmd, **kw):
            seen["cmd"] = cmd
            out = next(a for a in cmd if a.startswith("--output-filename=")).split("=", 1)[1]
            seen["out"] = out
            open(out, "wb").write(wav_bytes())
            return mock.Mock(returncode=0)

        with mock.patch.object(S, "find_runtime", return_value="/x/sherpa-onnx-offline-tts"), mock.patch.object(S.sys, "platform", "linux"):
            audio, sr = S.LocalEngine(d, runner).synth("Hello there.", vid, 2.0)
        self.assertEqual(sr, 22050)
        self.assertGreater(len(audio), 10000)
        self.assertIn("--vits-length-scale=0.500", seen["cmd"])
        self.assertEqual(seen["cmd"][-1], "Hello there.")
        self.assertFalse(os.path.exists(seen["out"]))

    def test_missing_engine_voice_and_failures_are_explained(self):
        d = tempfile.mkdtemp()
        with mock.patch.object(S.sys, "platform", "linux"):
            with self.assertRaisesRegex(S.SpeechError, "not set up"):
                S.LocalEngine(d).synth("x", "en_GB-alba-medium", 1)
            with mock.patch.object(S, "find_runtime", return_value="/x/tts"):
                with self.assertRaisesRegex(S.SpeechError, "not installed"):
                    S.LocalEngine(d).synth("x", "en_GB-alba-medium", 1)
                with mock.patch.object(S, "voice_files", return_value={"model": "m", "tokens": "t", "data": "d"}):
                    with self.assertRaisesRegex(S.SpeechError, "exit 7"):
                        S.LocalEngine(d, lambda c, **k: mock.Mock(returncode=7)).synth("x", "en_GB-alba-medium", 1)
                    with self.assertRaisesRegex(S.SpeechError, "too long"):
                        S.LocalEngine(d, mock.Mock(side_effect=S.subprocess.TimeoutExpired("x", 1))).synth("x", "en_GB-alba-medium", 1)


class FakeEngine:
    def __init__(self, name, online=False, fail=None, delay=0.0):
        self.name, self.online, self.fail, self.delay, self.calls = name, online, fail, delay, []

    def voices(self):
        return [("v", "Voice")]

    def check(self, voice):
        if self.fail:
            raise S.SpeechError(self.fail)

    def synth(self, text, voice, speed):
        import numpy as np

        self.check(voice)
        time.sleep(self.delay)
        self.calls.append((text, voice, speed))
        return np.ones(2205, dtype="float32") * 0.1, 22050


class FakePlayer:
    def __init__(self, seconds=0.05):
        self.played, self.seconds, self.aborted = [], seconds, threading.Event()

    def abort(self):
        self.aborted.set()

    def play(self, data, sr, level):
        self.aborted.clear()
        level(0.5)
        end = time.time() + self.seconds
        while time.time() < end:
            if self.aborted.is_set():
                return 0
            time.sleep(0.005)
        self.played.append(len(data))
        level(0.0)
        return len(data)


def wait_for(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


class TestService(unittest.TestCase):
    def make(self, prefs, local=None, ms=None, player=None):
        self.local = local or FakeEngine("local")
        self.ms = ms or FakeEngine("microsoft", online=True)
        self.player = player or FakePlayer()
        svc = S.SpeechService(tempfile.mkdtemp(), lambda: prefs, self.player, {"local": self.local, "microsoft": self.ms})
        self.events, self.errors = [], []
        svc.on_speaking = self.events.append
        svc.on_error = self.errors.append
        self.addCleanup(svc.shutdown)
        return svc

    def test_speaks_in_order_with_the_chosen_engine_voice_and_speed(self):
        svc = self.make({"enabled": True, "engine": "microsoft", "voice": "en-GB-SoniaNeural", "speed": 1.25})
        self.assertTrue(svc.speak("One. Two."))
        self.assertTrue(wait_for(lambda: self.events == [True, False]))
        self.assertEqual(self.ms.calls, [("One. Two.", "en-GB-SoniaNeural", 1.25)])
        self.assertEqual(self.local.calls, [])
        self.assertFalse(svc.is_busy)

    def test_disabled_speaks_nothing_and_unknown_voice_falls_back_within_the_same_engine(self):
        svc = self.make({"enabled": False, "engine": "microsoft", "voice": "nope", "speed": 1})
        self.assertFalse(svc.speak("Hello."))
        self.assertEqual(svc.settings()["voice"], S.DEFAULT_ONLINE_VOICE)

    def test_local_failure_never_falls_back_to_microsoft(self):
        svc = self.make({"enabled": True, "engine": "local", "voice": "en_GB-alba-medium", "speed": 1}, local=FakeEngine("local", fail="The local voice is not set up."))
        svc.speak("Hello.")
        self.assertTrue(wait_for(lambda: self.errors))
        self.assertIn("not set up", self.errors[0])
        self.assertEqual(self.ms.calls, [], "no online fallback")
        self.assertEqual(self.player.played, [])
        self.assertFalse(svc.availability()[0])

    def test_stop_drops_the_queue_and_cuts_playback(self):
        svc = self.make({"enabled": True, "engine": "local", "voice": "en_GB-alba-medium", "speed": 1}, player=FakePlayer(0.5))
        svc.speak(" ".join(f"Sentence number {i} is here." for i in range(40)))
        self.assertTrue(wait_for(lambda: True in self.events))
        svc.stop()
        self.assertTrue(wait_for(lambda: not svc.is_busy))
        self.assertTrue(self.player.aborted.is_set() or not self.player.played)
        n = len(self.local.calls)
        time.sleep(0.3)
        self.assertLessEqual(len(self.local.calls), n + 1, "nothing more is generated after stop")
        svc.speak("Again.")  # the service keeps working after a stop
        self.assertTrue(wait_for(lambda: self.events[-1] is False and len(self.player.played) >= 1, 3))

    def test_test_reports_success_only_when_audio_played(self):
        svc = self.make({"enabled": False, "engine": "local", "voice": "en_GB-alba-medium", "speed": 1})
        ok, msg = svc.test()
        self.assertTrue(ok, msg)
        self.assertIn("on this computer", msg)
        silent = self.make({"enabled": True, "engine": "local", "voice": "en_GB-alba-medium", "speed": 1}, player=mock.Mock(play=mock.Mock(return_value=0), abort=mock.Mock()))
        self.assertEqual(silent.test()[0], False)
        broken = self.make({"enabled": True, "engine": "microsoft", "voice": "x", "speed": 1}, ms=FakeEngine("microsoft", True, fail="no internet"))
        self.assertEqual(broken.test(), (False, "no internet"))


class FakeSettings(dict):
    def get(self, k):
        return dict.get(self, k)

    def set(self, k, v):
        self[k] = v
        return True


class TestPreferences(unittest.TestCase):
    def test_upgrade_keeps_microsoft_with_the_old_voice_speed_and_switch(self):
        s = FakeSettings(speech_engine="", speech_enabled=True, speech_speed=1.0)
        S.resolve_preferences(s, {"voice": "en-GB-RyanNeural", "speech_rate": 20, "speech_enabled": False}, upgraded=True)
        self.assertEqual((s["speech_engine"], s["speech_voice_online"], s["speech_speed"], s["speech_enabled"]), ("microsoft", "en-GB-RyanNeural", 1.2, False))

    def test_fresh_install_starts_local_and_a_decision_is_never_overwritten(self):
        s = FakeSettings(speech_engine="")
        S.resolve_preferences(s, {}, upgraded=False)
        self.assertEqual(s["speech_engine"], "local")
        S.resolve_preferences(s, {"voice": "x"}, upgraded=True)
        self.assertEqual(s["speech_engine"], "local")

    def test_desktop_settings_have_valid_defaults(self):
        from app.settings import DEFAULTS

        self.assertIn(DEFAULTS["speech_voice_local"], S.LOCAL_VOICES)
        self.assertIn(DEFAULTS["speech_voice_online"], S.ONLINE_VOICES)
        self.assertEqual(DEFAULTS["speech_engine"], "")


try:
    import PyQt6  # noqa: F401

    HAVE_QT = True
except Exception:
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, "PyQt6 not installed")
class TestVoiceSettingsUi(unittest.TestCase):
    def test_controls_reflect_real_state_and_persist(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        from app.ui.speech_bridge import SpeechBridge
        from app.ui.voice_settings import LocalVoiceDialog, SpokenReplies

        d = tempfile.mkdtemp()
        s = FakeSettings(speech_enabled=True, speech_engine="local", speech_voice_local="en_GB-alba-medium", speech_voice_online="en-US-ChristopherNeural", speech_speed=1.0)
        bridge = SpeechBridge(d, s)
        ui = SpokenReplies(bridge, s, d)
        self.assertFalse(ui.voice.isEnabled(), "no local voice installed: nothing selectable")
        self.assertFalse(ui.test_btn.isEnabled())
        self.assertIn("not ready", ui.status.text())
        ui.speed.setValue(150)
        self.assertEqual(s["speech_speed"], 1.5)
        ui.enabled.setChecked(False)
        self.assertFalse(s["speech_enabled"])
        self.assertIn("Off", ui.status.text())
        with mock.patch("app.ui.voice_settings.QMessageBox.exec"), mock.patch("app.ui.voice_settings.QMessageBox.clickedButton", return_value=None):
            ui.ms_rb.setChecked(True)
            ui._engine_clicked(ui.ms_rb)
        self.assertEqual(s["speech_engine"], "local", "declining the Microsoft disclosure keeps the local engine")
        dlg = LocalVoiceDialog(d)
        self.assertEqual(dlg.chosen(), [S.DEFAULT_LOCAL_VOICE])
        bridge.shutdown()
        app.processEvents()


if __name__ == "__main__":
    unittest.main()
