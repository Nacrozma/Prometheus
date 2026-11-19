"""Spoken replies for Prometheus: one shared speech service with two engines the owner chooses between.

* **Local (on this computer)** — sherpa-onnx's `sherpa-onnx-offline-tts` program with Piper voices, set up
  from Settings → Voice. After setup it needs no internet and no reply text leaves the computer.
* **Microsoft online** — edge-tts: the reply text is sent to Microsoft's speech service and audio comes back.
  Needs internet. Optional, disclosed before it is chosen.

There is **no automatic fallback** between engines: if the chosen engine cannot speak, the reply stays text
and the error says why and what to do.

Downloads follow the same rules as voice input (`local_stt.download`): pinned HTTPS URLs on github.com,
SHA-256 checked before use, `.part` files, cancel, size limit, safe extraction (only regular files inside the
archive's own folder; no links, no absolute or `..` paths). Plain Python except the optional audio player, so
the rules are unit-tested.
"""

from __future__ import annotations

import io
import os
import queue
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import wave
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from .local_stt import Asset, Cancelled, SetupError, download

FOLDER = "speech"
SYNTH_TIMEOUT_S = 60
MAX_CHUNK = 360  # characters per synthesis call: keeps latency low and command lines short
SPEED_MIN, SPEED_MAX = 0.5, 2.0

RUNTIMES: Dict[str, Asset] = {
    "win32": Asset("sherpa-onnx-1.12.40-win-x64", "sherpa-onnx 1.12.40 speech engine (Apache-2.0)",
                   "https://github.com/k2-fsa/sherpa-onnx/releases/download/v1.12.40/sherpa-onnx-v1.12.40-win-x64-shared-MT-Release.tar.bz2",
                   "7555e9fa5e30e5b47feea1700090086c0fa2a91dd09754922ac7d79a72f46f91", 23),
    "linux": Asset("sherpa-onnx-1.12.40-linux-x64", "sherpa-onnx 1.12.40 speech engine (Apache-2.0)",
                   "https://github.com/k2-fsa/sherpa-onnx/releases/download/v1.12.40/sherpa-onnx-v1.12.40-linux-x64-shared.tar.bz2",
                   "f7bb558400a298c94aaebeba6f68cd2bcdd0a9484b63daaed3f45a2c246eb929", 27),
}


@dataclass(frozen=True)
class LocalVoice:
    id: str
    name: str
    language: str
    character: str
    asset: Asset
    licence: str


def _voice_asset(vid: str, sha: str, size: int) -> Asset:
    return Asset(vid, f"Piper voice {vid}", f"https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-{vid}.tar.bz2", sha, size)


#: Checksums computed from the downloaded archives (2026-11-19); sizes in MB.
LOCAL_VOICES: Dict[str, LocalVoice] = {
    "en_GB-alba-medium": LocalVoice("en_GB-alba-medium", "Alba", "English (UK)", "female, calm", _voice_asset("en_GB-alba-medium", "fcd45962906933eec4431d3688f7d74aaac8713c87c6717f91fd3b23463aa1a1", 65), "CC BY 4.0"),
    "en_US-lessac-medium": LocalVoice("en_US-lessac-medium", "Lessac", "English (US)", "female, clear", _voice_asset("en_US-lessac-medium", "9e3febfacf0abf4270172d2958bcec246032b7e88efc2720840cc80c93de334e", 65), "Blizzard 2013 Lessac licence (non-commercial use)"),
    "en_US-ryan-medium": LocalVoice("en_US-ryan-medium", "Ryan", "English (US)", "male, warm", _voice_asset("en_US-ryan-medium", "c546af78b6395b4e7c4ce1ed899438b64426a362f5d4ec5fecd090ded9ad7505", 65), "CC BY-NC-SA 4.0 (non-commercial use)"),
}
DEFAULT_LOCAL_VOICE = "en_GB-alba-medium"

#: Microsoft neural voices offered for the online engine (real edge-tts voice names).
ONLINE_VOICES: Dict[str, Tuple[str, str, str]] = {
    "en-US-ChristopherNeural": ("Christopher", "English (US)", "male"),
    "en-US-JennyNeural": ("Jenny", "English (US)", "female"),
    "en-US-GuyNeural": ("Guy", "English (US)", "male"),
    "en-US-AriaNeural": ("Aria", "English (US)", "female"),
    "en-GB-RyanNeural": ("Ryan", "English (UK)", "male"),
    "en-GB-SoniaNeural": ("Sonia", "English (UK)", "female"),
    "en-AU-NatashaNeural": ("Natasha", "English (Australia)", "female"),
}
DEFAULT_ONLINE_VOICE = "en-US-ChristopherNeural"
ENGINES = ("local", "microsoft")


class SpeechError(RuntimeError):
    """Something the owner can act on; the message says what happened and what to do."""


# ------------------------------------------------------------------ local assets

def folder(data_dir: str) -> str:
    return os.path.join(data_dir, FOLDER)


def runtime_dir(data_dir: str) -> str:
    return os.path.join(folder(data_dir), "engine")


def voice_dir(data_dir: str, vid: str) -> str:
    return os.path.join(folder(data_dir), "voices", vid)


def platform_key() -> Optional[str]:
    if sys.platform == "win32":
        return "win32"
    if sys.platform.startswith("linux"):
        return "linux"
    return None


def find_runtime(data_dir: str) -> Optional[str]:
    exe = "sherpa-onnx-offline-tts.exe" if sys.platform == "win32" else "sherpa-onnx-offline-tts"
    p = os.path.join(runtime_dir(data_dir), "bin", exe)
    return p if os.path.isfile(p) else None


def voice_files(data_dir: str, vid: str) -> Optional[Dict[str, str]]:
    """The model, tokens and phoneme data of an installed voice, or None if anything is missing."""
    d = voice_dir(data_dir, vid)
    files = {"model": os.path.join(d, f"{vid}.onnx"), "tokens": os.path.join(d, "tokens.txt"), "data": os.path.join(d, "espeak-ng-data")}
    if os.path.isfile(files["model"]) and os.path.isfile(files["tokens"]) and os.path.isdir(files["data"]):
        return files
    return None


def installed_voices(data_dir: str) -> List[str]:
    return [vid for vid in LOCAL_VOICES if voice_files(data_dir, vid)]


def storage_bytes(data_dir: str) -> int:
    total = 0
    for root, _, files in os.walk(folder(data_dir)):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def local_status(data_dir: str) -> Dict[str, object]:
    pk = platform_key()
    rt = find_runtime(data_dir)
    voices = installed_voices(data_dir)
    if pk is None:
        text = "Local speech is not available on this operating system yet."
    elif rt and voices:
        text = f"Ready on this computer: {len(voices)} voice{'s' if len(voices) != 1 else ''} installed."
    elif rt:
        text = "The engine is installed but no voice is. Install a voice."
    else:
        text = "Not set up yet."
    return {"supported": pk is not None, "engine": rt or "", "voices": voices, "ready": bool(rt and voices), "text": text, "bytes": storage_bytes(data_dir)}


def safe_extract_tar(archive: str, dest: str, top: str, keep: Callable[[str], bool]) -> int:
    """Extract regular files under `top/` whose relative path passes `keep`. Links, devices, absolute paths
    and any path that would leave `dest` are skipped. Returns the number of files written."""
    n = 0
    real_dest = os.path.realpath(dest)
    with tarfile.open(archive, "r:bz2") as t:
        for m in t:
            name = m.name.replace("\\", "/")
            if not m.isfile() or not name.startswith(top + "/"):
                continue
            rel = name[len(top) + 1:]
            parts = rel.split("/")
            if not rel or rel.startswith("/") or any(p in ("", "..") for p in parts) or not keep(rel):
                continue
            target = os.path.realpath(os.path.join(dest, *parts))
            if not target.startswith(real_dest + os.sep):
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            src = t.extractfile(m)
            if src is None:
                continue
            with src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            if sys.platform != "win32" and m.mode & 0o111:
                os.chmod(target, 0o755)
            n += 1
    return n


def _check_space(data_dir: str, mb: int) -> None:
    os.makedirs(folder(data_dir), exist_ok=True)
    free = shutil.disk_usage(folder(data_dir)).free
    need = int(mb * 3.2 * 1024 * 1024)  # archive + extracted files + margin
    if free < need:
        raise SetupError(f"not enough disk space: about {need // 1048576} MB are needed, {free // 1048576} MB are free")


def install_runtime(data_dir: str, progress=None, cancel=None, opener=None) -> str:
    pk = platform_key()
    if pk is None:
        raise SetupError("local speech is not available on this operating system yet")
    asset = RUNTIMES[pk]
    _check_space(data_dir, asset.size_mb)
    arc = os.path.join(folder(data_dir), "downloads", os.path.basename(asset.url))
    kw = {"opener": opener} if opener else {}
    download(asset, arc, progress, cancel, **kw)
    tmp = runtime_dir(data_dir) + ".new"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    try:
        top = os.path.basename(asset.url)[: -len(".tar.bz2")]
        exe = "sherpa-onnx-offline-tts" + (".exe" if pk == "win32" else "")
        lib_ok = (lambda rel: rel.startswith("lib/") and (rel.endswith((".dll", ".so")) or ".so." in rel))
        n = safe_extract_tar(arc, tmp, top, lambda rel: rel == f"bin/{exe}" or (pk == "win32" and rel.startswith("bin/") and rel.endswith(".dll")) or lib_ok(rel))
        if not os.path.isfile(os.path.join(tmp, "bin", exe)) or n < 2:
            raise SetupError("the engine archive does not contain the speech program")
        if pk == "win32":  # the program looks for its DLLs next to itself
            for f in os.listdir(os.path.join(tmp, "lib")) if os.path.isdir(os.path.join(tmp, "lib")) else []:
                if f.endswith(".dll") and not os.path.exists(os.path.join(tmp, "bin", f)):
                    shutil.copy2(os.path.join(tmp, "lib", f), os.path.join(tmp, "bin", f))
        shutil.rmtree(runtime_dir(data_dir), ignore_errors=True)
        os.replace(tmp, runtime_dir(data_dir))
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    finally:
        if os.path.exists(arc):
            os.remove(arc)
    return find_runtime(data_dir) or ""


def install_voice(data_dir: str, vid: str, progress=None, cancel=None, opener=None) -> None:
    v = LOCAL_VOICES.get(vid)
    if v is None:
        raise SetupError("unknown voice")
    _check_space(data_dir, v.asset.size_mb)
    arc = os.path.join(folder(data_dir), "downloads", os.path.basename(v.asset.url))
    kw = {"opener": opener} if opener else {}
    download(v.asset, arc, progress, cancel, **kw)
    target = voice_dir(data_dir, vid)
    tmp = target + ".new"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    try:
        allowed = (f"{vid}.onnx", "tokens.txt", f"{vid}.onnx.json", "MODEL_CARD")
        safe_extract_tar(arc, tmp, f"vits-piper-{vid}", lambda rel: rel in allowed or rel.startswith("espeak-ng-data/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.rmtree(target, ignore_errors=True)
        os.replace(tmp, target)
        if not voice_files(data_dir, vid):
            shutil.rmtree(target, ignore_errors=True)
            raise SetupError("the voice archive is incomplete")
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    finally:
        if os.path.exists(arc):
            os.remove(arc)


def setup_local(data_dir: str, voices: List[str], progress: Optional[Callable[[str, int, int], None]] = None, cancel: Optional[threading.Event] = None, opener=None) -> Dict[str, object]:
    """Install what is missing: the engine, then each chosen voice. Safe to run again (repair = remove + setup)."""
    say = (lambda stage: (lambda g, t: progress(stage, g, t))) if progress else (lambda stage: None)
    if not find_runtime(data_dir):
        install_runtime(data_dir, say("engine"), cancel, opener)
    for vid in voices:
        if not voice_files(data_dir, vid):
            install_voice(data_dir, vid, say(vid), cancel, opener)
    return local_status(data_dir)


def remove_local(data_dir: str, vid: Optional[str] = None) -> None:
    """Remove one voice, or everything local speech downloaded. Voice input files are elsewhere and untouched."""
    shutil.rmtree(voice_dir(data_dir, vid) if vid else folder(data_dir), ignore_errors=True)


# ------------------------------------------------------------------ text

def speakable(text: str) -> str:
    """Only words meant for a person: no code, plan blocks, links, markup or tool payloads."""
    t = re.sub(r"```.*?```", " ", text or "", flags=re.S)
    t = re.sub(r"```.*$", " ", t, flags=re.S)  # an unfinished block
    t = re.sub(r"`([^`]{1,40})`", r"\1", t)
    t = re.sub(r"`[^`]*`", " ", t)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"https?://\S*[^\s.,;:!?)\]]", "a link", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"^\s{0,3}(#{1,6}|>|[-*+]|\d+[.)])\s+", "", t, flags=re.M)
    t = re.sub(r"[*_~|]{1,3}", "", t)
    t = re.sub(r"\{[^{}]{40,}\}", " ", t)  # raw structured payloads
    return " ".join(t.split())


def chunks(text: str, limit: int = MAX_CHUNK) -> List[str]:
    """Sentences, merged up to `limit` characters; very long sentences are split at commas, then words."""
    sentences = re.split(r"(?<=[.!?…])\s+", text.strip())
    out: List[str] = []
    cur = ""
    for s in sentences:
        if len(s) > limit and cur:
            out.append(cur)
            cur = ""
        while len(s) > limit:
            cut = s.rfind(", ", 0, limit)
            cut = cut + 1 if cut > limit // 3 else s.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            out.append(s[:cut].strip())
            s = s[cut:].strip()
        if cur and len(cur) + 1 + len(s) > limit:
            out.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        out.append(cur)
    return [c for c in out if c]


def clamp_speed(x) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 1.0
    return max(SPEED_MIN, min(SPEED_MAX, v))


# ------------------------------------------------------------------ engines

def read_wav(path_or_bytes) -> Tuple["object", int]:
    import numpy as np

    src = io.BytesIO(path_or_bytes) if isinstance(path_or_bytes, (bytes, bytearray)) else path_or_bytes
    with wave.open(src, "rb") as w:
        sr, ch, width, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    if width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype("float32") / 32768.0
    elif width == 4:
        data = np.frombuffer(raw, dtype="<i4").astype("float32") / 2147483648.0
    else:
        raise SpeechError("the speech engine produced audio in an unexpected format")
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    return data.astype("float32"), sr


class LocalEngine:
    name = "local"
    online = False

    def __init__(self, data_dir: str, runner: Callable = subprocess.run):
        self.data_dir, self.runner = data_dir, runner

    def voices(self) -> List[Tuple[str, str]]:
        return [(vid, f"{LOCAL_VOICES[vid].name} · {LOCAL_VOICES[vid].language} · {LOCAL_VOICES[vid].character}") for vid in installed_voices(self.data_dir)]

    def check(self, voice: str) -> None:
        if platform_key() is None:
            raise SpeechError("Local speech is not available on this operating system yet. Choose Microsoft online in Settings → Voice, or keep replies as text.")
        if not find_runtime(self.data_dir):
            raise SpeechError("The local voice is not set up. Settings → Voice → Set up local voice. Replies stay as text until then.")
        if not voice_files(self.data_dir, voice):
            raise SpeechError(f"The voice “{LOCAL_VOICES[voice].name if voice in LOCAL_VOICES else voice}” is not installed. Choose an installed voice or install it in Settings → Voice.")

    def synth(self, text: str, voice: str, speed: float):
        self.check(voice)
        files = voice_files(self.data_dir, voice)
        work = tempfile.mkdtemp(prefix="prometheus-tts-")
        try:
            out = os.path.join(work, "speech.wav")
            cmd = [find_runtime(self.data_dir), f"--vits-model={files['model']}", f"--vits-tokens={files['tokens']}", f"--vits-data-dir={files['data']}",
                   f"--vits-length-scale={1.0 / clamp_speed(speed):.3f}", f"--num-threads={max(1, min(4, (os.cpu_count() or 2) - 1))}", f"--output-filename={out}", text]
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
            try:
                r = self.runner(cmd, capture_output=True, text=True, timeout=SYNTH_TIMEOUT_S, creationflags=flags)
            except subprocess.TimeoutExpired:
                raise SpeechError("The local voice took too long to answer and was stopped.")
            except OSError as e:
                raise SpeechError(f"The local speech engine could not be started ({e}). Repair it in Settings → Voice.")
            if r.returncode != 0 or not os.path.isfile(out) or os.path.getsize(out) <= 44:
                raise SpeechError(f"The local voice could not generate speech (exit {r.returncode}). Repair it in Settings → Voice.")
            return read_wav(out)
        finally:
            shutil.rmtree(work, ignore_errors=True)


class MicrosoftEngine:
    name = "microsoft"
    online = True

    def voices(self) -> List[Tuple[str, str]]:
        return [(vid, f"{n} · {lang} · {kind}") for vid, (n, lang, kind) in ONLINE_VOICES.items()]

    def check(self, voice: str) -> None:
        try:
            import edge_tts  # noqa: F401
            import soundfile  # noqa: F401
        except Exception:
            raise SpeechError("Microsoft online speech is not available in this installation.")

    def synth(self, text: str, voice: str, speed: float):
        import asyncio

        self.check(voice)
        import edge_tts
        import soundfile as sf

        pct = int(round((clamp_speed(speed) - 1.0) * 100))
        pct = max(-50, min(100, pct))  # edge-tts accepts -50%..+100%

        async def go():
            buf = bytearray()
            async for c in edge_tts.Communicate(text, voice, rate=f"{'+' if pct >= 0 else ''}{pct}%").stream():
                if c["type"] == "audio":
                    buf.extend(c["data"])
            return bytes(buf)

        try:
            data = asyncio.run(go())
        except Exception as e:
            raise SpeechError(f"Microsoft's speech service could not be reached ({type(e).__name__}). Check the internet connection, or choose the local voice in Settings → Voice.")
        if not data:
            raise SpeechError("Microsoft's speech service returned no audio.")
        audio, sr = sf.read(io.BytesIO(data), dtype="float32")
        if getattr(audio, "ndim", 1) > 1:
            audio = audio.mean(axis=1).astype("float32")
        return audio, sr


# ------------------------------------------------------------------ playback

class SoundDevicePlayer:
    """Plays one utterance on the default output device; `abort()` stops it within one audio block."""

    def __init__(self):
        self._abort = threading.Event()

    def abort(self) -> None:
        self._abort.set()

    def play(self, data, sr: int, level: Callable[[float], None]) -> int:
        import numpy as np
        import sounddevice as sd

        self._abort.clear()
        done = threading.Event()
        pos = 0

        def cb(outdata, frames, t, status):
            nonlocal pos
            if self._abort.is_set():
                outdata[:] = 0
                raise sd.CallbackStop()
            chunk = data[pos:pos + frames]
            n = len(chunk)
            outdata[:n, 0] = chunk
            outdata[n:, 0] = 0
            pos += n
            level(float(np.clip(np.sqrt(np.mean(chunk.astype("float64") ** 2)) * 4.8, 0, 1)) if n else 0.0)
            if n < frames:
                raise sd.CallbackStop()

        try:
            with sd.OutputStream(samplerate=sr, channels=1, dtype="float32", callback=cb, finished_callback=done.set):
                done.wait(timeout=len(data) / max(sr, 1) + 5.0)
        except Exception as e:
            raise SpeechError(f"The speaker could not be used ({e}).")
        finally:
            level(0.0)
        return pos


# ------------------------------------------------------------------ the shared service

class SpeechService:
    """One queue, one player, used by the Companion and ORBIT. Synthesis runs ahead of playback in its own
    thread; `stop()` drops everything queued and cuts the current audio. Callbacks (from worker threads):
    on_level(float), on_speaking(bool), on_error(str)."""

    def __init__(self, data_dir: str, prefs: Callable[[], Dict[str, object]], player=None, engines: Optional[Dict[str, object]] = None):
        self.data_dir = data_dir
        self.prefs = prefs
        self.player = player or SoundDevicePlayer()
        self.engines = engines or {"local": LocalEngine(data_dir), "microsoft": MicrosoftEngine()}
        self.on_level: Callable[[float], None] = lambda x: None
        self.on_speaking: Callable[[bool], None] = lambda b: None
        self.on_error: Callable[[str], None] = lambda m: None
        self._gen = 0
        self._lock = threading.Lock()
        self._text: "queue.Queue" = queue.Queue()
        self._audio: "queue.Queue" = queue.Queue(maxsize=3)
        self._speaking = False
        self._pending = 0
        self._closed = False
        self._last_error = ""
        self._threads = [threading.Thread(target=self._synth_loop, daemon=True, name="speech-synth"), threading.Thread(target=self._play_loop, daemon=True, name="speech-play")]
        for t in self._threads:
            t.start()

    # --- preferences ---
    def settings(self) -> Dict[str, object]:
        p = dict(self.prefs())
        engine = p.get("engine") if p.get("engine") in ENGINES else "local"
        voice = p.get("voice") or ""
        if engine == "local" and voice not in LOCAL_VOICES:
            voice = (installed_voices(self.data_dir) or [DEFAULT_LOCAL_VOICE])[0]
        if engine == "microsoft" and voice not in ONLINE_VOICES:
            voice = DEFAULT_ONLINE_VOICE
        return {"enabled": bool(p.get("enabled", True)), "engine": engine, "voice": voice, "speed": clamp_speed(p.get("speed", 1.0))}

    @property
    def enabled(self) -> bool:
        return self.settings()["enabled"]

    def engine(self, name: Optional[str] = None):
        return self.engines[name or self.settings()["engine"]]

    def availability(self) -> Tuple[bool, str]:
        s = self.settings()
        try:
            self.engine(s["engine"]).check(s["voice"])
            return True, "Ready"
        except SpeechError as e:
            return False, str(e)

    # --- speaking ---
    @property
    def is_busy(self) -> bool:
        return self._speaking or self._pending > 0

    def speak(self, text: str, force: bool = False) -> bool:
        """Queue words for speaking (respects the on/off switch unless `force`, used by Test voice)."""
        if self._closed or (not force and not self.enabled):
            return False
        clean = speakable(text)
        if not clean:
            return False
        with self._lock:
            gen = self._gen
            for c in chunks(clean):
                self._pending += 1
                self._text.put((gen, c))
        return True

    def stop(self) -> None:
        """Stop speaking now: drop queued text and audio, cut the current utterance."""
        with self._lock:
            self._gen += 1
            for q in (self._text, self._audio):
                while True:
                    try:
                        q.get_nowait()
                        self._pending = max(0, self._pending - 1)
                    except queue.Empty:
                        break
        self.player.abort()

    # compatibility with the pages' former TTSManager use
    def set_muted(self, muted: bool) -> None:
        if muted:
            self.stop()

    def _fail(self, msg: str) -> None:
        self._last_error = msg
        self.stop()
        try:
            self.on_error(msg)
        except Exception:
            pass

    def _synth_loop(self) -> None:
        while not self._closed:
            try:
                gen, text = self._text.get(timeout=0.5)
            except queue.Empty:
                continue
            if gen != self._gen:
                self._pending = max(0, self._pending - 1)
                continue
            s = self.settings()
            try:
                audio, sr = self.engine(s["engine"]).synth(text, s["voice"], s["speed"])
            except SpeechError as e:
                self._pending = max(0, self._pending - 1)
                self._fail(str(e))
                continue
            except Exception as e:
                self._pending = max(0, self._pending - 1)
                self._fail(f"Speech failed unexpectedly ({type(e).__name__}).")
                continue
            if gen != self._gen:
                self._pending = max(0, self._pending - 1)
                continue
            while not self._closed:
                try:
                    self._audio.put((gen, audio, sr), timeout=0.5)
                    break
                except queue.Full:
                    if gen != self._gen:
                        self._pending = max(0, self._pending - 1)
                        break

    def _play_loop(self) -> None:
        while not self._closed:
            try:
                gen, audio, sr = self._audio.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                if gen == self._gen and len(audio):
                    if not self._speaking:
                        self._speaking = True
                        self.on_speaking(True)
                    self.player.play(audio, sr, self.on_level)
            except SpeechError as e:
                self._fail(str(e))
            except Exception as e:
                self._fail(f"Playback failed ({type(e).__name__}).")
            finally:
                self._pending = max(0, self._pending - 1)
                if self._pending == 0 and self._speaking:
                    self._speaking = False
                    self.on_speaking(False)

    def test(self, text: str = "Hello. This is how I will sound when I answer you.", timeout: float = 60.0) -> Tuple[bool, str]:
        """Generate and play real speech with the current engine, voice and speed; True only if audio played."""
        s = self.settings()
        try:
            eng = self.engine(s["engine"])
            eng.check(s["voice"])
            audio, sr = eng.synth(text, s["voice"], s["speed"])
        except SpeechError as e:
            return False, str(e)
        if not len(audio):
            return False, "No audio was generated."
        self.stop()
        try:
            played = self.player.play(audio, sr, self.on_level)
        except SpeechError as e:
            return False, str(e)
        if played <= 0:
            return False, "The audio was generated but could not be played."
        where = "on this computer" if not eng.online else "by Microsoft's online service"
        return True, f"Spoken {where}: {played / sr:.1f} s of audio."

    def shutdown(self) -> None:
        self.stop()
        self._closed = True


# ------------------------------------------------------------------ preferences and migration

def resolve_preferences(settings, legacy: Optional[Dict[str, object]] = None, upgraded: bool = False) -> None:
    """Fill the speech_* desktop settings once. An upgrade keeps 2.2.0's behaviour (Microsoft online, with
    its voice, speed and on/off from the old config); a fresh install starts with the local engine."""
    if settings.get("speech_engine") in ENGINES:
        return
    legacy = legacy or {}
    if upgraded:
        settings.set("speech_engine", "microsoft")
        v = str(legacy.get("voice") or "")
        settings.set("speech_voice_online", v if v in ONLINE_VOICES else DEFAULT_ONLINE_VOICE)
        try:
            settings.set("speech_speed", clamp_speed(1.0 + int(legacy.get("speech_rate", 0) or 0) / 100.0))
        except (TypeError, ValueError):
            pass
        settings.set("speech_enabled", bool(legacy.get("speech_enabled", True)))
    else:
        settings.set("speech_engine", "local")


def prefs_from(settings) -> Callable[[], Dict[str, object]]:
    def read() -> Dict[str, object]:
        engine = settings.get("speech_engine")
        return {"enabled": settings.get("speech_enabled"), "engine": engine, "voice": settings.get("speech_voice_local" if engine == "local" else "speech_voice_online"), "speed": settings.get("speech_speed")}

    return read


def _ci_check(data_dir: str) -> int:
    """Windows workflow: real download, checksums, extraction, local speech generation and (if the runner
    has an audio device) playback."""
    import numpy as np

    st = setup_local(data_dir, [DEFAULT_LOCAL_VOICE])
    print("setup:", {k: v for k, v in st.items() if k != "bytes"}, "MB:", st["bytes"] // 1048576)
    eng = LocalEngine(data_dir)
    t0 = time.time()
    audio, sr = eng.synth("Hello. I am Prometheus, and I am speaking on this computer.", DEFAULT_LOCAL_VOICE, 1.0)
    dur, rms = len(audio) / sr, float(np.sqrt(np.mean(audio.astype("float64") ** 2)))
    print(f"generated {dur:.2f} s at {sr} Hz in {time.time() - t0:.2f} s, rms {rms:.4f}")
    fast, _ = eng.synth("Hello. I am Prometheus, and I am speaking on this computer.", DEFAULT_LOCAL_VOICE, 1.5)
    print(f"speed 1.5x: {len(fast) / sr:.2f} s")
    try:
        played = SoundDevicePlayer().play(audio, sr, lambda x: None)
        print(f"playback: {played} frames")
    except SpeechError as e:
        print(f"playback not possible on this runner: {e}")
    ok = st["ready"] and dur > 1.0 and rms > 0.005 and len(fast) < len(audio)
    return 0 if ok else 1


if __name__ == "__main__":  # python -m app.services.speech --ci-check <folder>
    if len(sys.argv) == 3 and sys.argv[1] == "--ci-check":
        sys.exit(_ci_check(sys.argv[2]))
    print(__doc__)


__all__ = ["SpeechService", "SpeechError", "LocalEngine", "MicrosoftEngine", "Cancelled"]
