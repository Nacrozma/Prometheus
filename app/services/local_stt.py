"""Voice input without PyTorch: whisper.cpp run on this computer, set up from inside Prometheus.

Settings → Voice → *Set up voice input* downloads two things into the data folder (`<data>/voice/`):

* the whisper.cpp engine (Windows: the official release zip; elsewhere a `whisper-cli` already on PATH);
* one Whisper model in ggml format (Tiny, Base or Small).

Every download is pinned to an HTTPS URL on github.com or huggingface.co and checked against its SHA-256
before it is used; a file that does not match is deleted and the setup fails with the reason. Extraction
accepts only plain files under the archive's `Release/` folder (no paths that leave the folder). Audio is
written to a temporary WAV for the engine and deleted straight after; nothing leaves the computer.

Plain Python (no Qt) so it is unit-tested; the dialog and the recording thread live in app/ui/voice_setup.py.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
import wave
import zipfile
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

FOLDER = "voice"
ALLOWED_HOSTS = ("https://github.com/", "https://huggingface.co/")
CHUNK = 1 << 16
TRANSCRIBE_TIMEOUT_S = 120


@dataclass(frozen=True)
class Asset:
    id: str
    name: str
    url: str
    sha256: str
    size_mb: int
    note: str = ""


ENGINE_WINDOWS = Asset(
    "whisper-cpp-1.8.2-win-x64",
    "whisper.cpp 1.8.2 speech-recognition engine (MIT licence)",
    "https://github.com/ggml-org/whisper.cpp/releases/download/v1.8.2/whisper-bin-x64.zip",
    "b1514ebc099765e39fa37eb780b92a140a94c86bb0b3b3d98226b38825979732",
    4,
    "Official release from github.com/ggml-org/whisper.cpp",
)

MODELS: Dict[str, Asset] = {
    "tiny": Asset("tiny", "Tiny — fastest, least accurate", "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin", "be07e048e1e599ad46341c8d2a135645097a538221678b7acdd1b1919c6e1b21", 75),
    "base": Asset("base", "Base — recommended balance", "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin", "60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe", 142),
    "small": Asset("small", "Small — most accurate, slower", "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin", "1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b", 466),
}
MODEL_LICENCE = "Whisper weights: MIT licence (OpenAI); ggml conversion by whisper.cpp."


class SetupError(RuntimeError):
    pass


class Cancelled(SetupError):
    pass


def folder(data_dir: str) -> str:
    return os.path.join(data_dir, FOLDER)


def engine_dir(data_dir: str) -> str:
    return os.path.join(folder(data_dir), "engine")


def model_path(data_dir: str, model_id: str) -> str:
    return os.path.join(folder(data_dir), "models", f"ggml-{model_id}.bin")


def find_engine(data_dir: str) -> Optional[str]:
    """The whisper-cli executable Prometheus may use: its own copy first, then one on PATH (Linux/macOS builds)."""
    exe = "whisper-cli.exe" if sys.platform == "win32" else "whisper-cli"
    own = os.path.join(engine_dir(data_dir), exe)
    if os.path.isfile(own):
        return own
    return shutil.which("whisper-cli")


def installed_model(data_dir: str) -> Optional[str]:
    """The best installed model id (the most accurate one present), or None."""
    for mid in ("small", "base", "tiny"):
        if os.path.isfile(model_path(data_dir, mid)):
            return mid
    return None


def status(data_dir: str) -> Dict[str, object]:
    eng = find_engine(data_dir)
    mid = installed_model(data_dir)
    can_download_engine = sys.platform == "win32"
    if eng and mid:
        text = f"Ready: whisper.cpp with the {mid.capitalize()} model, on this computer."
    elif not eng and not can_download_engine:
        text = "Needs whisper.cpp: on this system install it so that `whisper-cli` is on PATH, then download a model here."
    else:
        text = "Not set up yet."
    return {"ready": bool(eng and mid), "engine": eng or "", "model": mid or "", "engine_downloadable": can_download_engine, "text": text}


def _check_url(url: str) -> None:
    if not url.startswith(ALLOWED_HOSTS):
        raise SetupError(f"refusing to download from an unknown host: {url}")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def download(asset: Asset, dest: str, progress: Optional[Callable[[int, int], None]] = None, cancel: Optional[threading.Event] = None, opener: Callable = urllib.request.urlopen) -> str:
    """Download `asset` to `dest` via a `.part` file, verify its SHA-256, then move it into place."""
    _check_url(asset.url)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    part = dest + ".part"
    h = hashlib.sha256()
    limit = (asset.size_mb + 64) * 1024 * 1024
    try:
        req = urllib.request.Request(asset.url, headers={"User-Agent": "Prometheus-Desktop"})
        with opener(req, timeout=60) as r, open(part, "wb") as out:
            total = int(r.headers.get("Content-Length") or 0) or asset.size_mb * 1024 * 1024
            got = 0
            while True:
                if cancel is not None and cancel.is_set():
                    raise Cancelled("cancelled")
                block = r.read(CHUNK)
                if not block:
                    break
                got += len(block)
                if got > limit:
                    raise SetupError(f"{asset.name}: larger than expected; stopped")
                h.update(block)
                out.write(block)
                if progress:
                    progress(got, total)
        if h.hexdigest() != asset.sha256:
            raise SetupError(f"{asset.name}: the download does not match its published checksum, so it was deleted")
        os.replace(part, dest)
        return dest
    except Cancelled:
        raise
    except SetupError:
        raise
    except Exception as e:
        raise SetupError(f"{asset.name}: download failed ({type(e).__name__}: {e})") from e
    finally:
        if os.path.exists(part):
            os.remove(part)


def extract_engine(zip_path: str, data_dir: str) -> str:
    """Unpack only the plain files under Release/ into the engine folder; return the whisper-cli path."""
    target = engine_dir(data_dir)
    tmp = target + ".new"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            name = info.filename.replace("\\", "/")
            if info.is_dir() or not name.startswith("Release/"):
                continue
            base = name[len("Release/"):]
            if not base or "/" in base or base.startswith(".") or ".." in base:
                continue  # only top-level files of Release/; nothing can leave the folder
            if not base.lower().endswith((".exe", ".dll")):
                continue
            with z.open(info) as src, open(os.path.join(tmp, base), "wb") as dst:
                shutil.copyfileobj(src, dst)
    exe = os.path.join(tmp, "whisper-cli.exe")
    if not os.path.isfile(exe):
        shutil.rmtree(tmp, ignore_errors=True)
        raise SetupError("the engine archive does not contain whisper-cli.exe")
    copy_runtime(tmp)
    shutil.rmtree(target, ignore_errors=True)
    os.replace(tmp, target)
    return os.path.join(target, "whisper-cli.exe")


RUNTIME_DLLS = ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll")


def copy_runtime(target: str, roots: Optional[List[str]] = None) -> List[str]:
    """whisper-cli.exe needs the Microsoft C++ runtime, which not every PC has installed. Prometheus's own
    install folder already ships these DLLs (with Python and Qt), so copies are placed next to the engine.
    Only these three names are copied, only from Prometheus's own folders."""
    if roots is None:
        roots = [os.path.dirname(sys.executable), getattr(sys, "_MEIPASS", ""), sys.base_prefix]
        try:
            import PyQt6

            roots.append(os.path.dirname(PyQt6.__file__))
        except Exception:
            pass
    want = {n: None for n in RUNTIME_DLLS}
    for root in [r for r in roots if r and os.path.isdir(r)]:
        for dirpath, dirs, files in os.walk(root):
            if dirpath[len(root):].count(os.sep) > 4:
                dirs[:] = []
                continue
            for f in files:
                low = f.lower()
                if low in want and want[low] is None:
                    want[low] = os.path.join(dirpath, f)
            if all(want.values()):
                break
    copied = []
    for name, src in want.items():
        if src and not os.path.exists(os.path.join(target, name)):
            shutil.copy2(src, os.path.join(target, name))
            copied.append(name)
    return copied


def setup(data_dir: str, model_id: str, progress: Optional[Callable[[str, int, int], None]] = None, cancel: Optional[threading.Event] = None, opener: Callable = urllib.request.urlopen) -> Dict[str, object]:
    """Download what is missing (engine on Windows, then the model). Safe to run again."""
    if model_id not in MODELS:
        raise SetupError("unknown model")
    say = (lambda stage: (lambda got, total: progress(stage, got, total))) if progress else (lambda stage: None)
    if not find_engine(data_dir):
        if sys.platform != "win32":
            raise SetupError("whisper.cpp is not installed: on this system install it so that `whisper-cli` is on PATH")
        z = download(ENGINE_WINDOWS, os.path.join(folder(data_dir), "downloads", "whisper-bin-x64.zip"), say("engine"), cancel, opener)
        try:
            extract_engine(z, data_dir)
        finally:
            os.remove(z)
    dest = model_path(data_dir, model_id)
    if not os.path.isfile(dest):
        download(MODELS[model_id], dest, say("model"), cancel, opener)
    return status(data_dir)


def remove(data_dir: str) -> None:
    shutil.rmtree(folder(data_dir), ignore_errors=True)


def write_wav(path: str, pcm, sample_rate: int = 16000) -> None:
    """Float samples in -1..1 (a sequence or numpy array) as 16-bit mono WAV."""
    import array

    data = array.array("h", (int(max(-1.0, min(1.0, float(x))) * 32767) for x in pcm))
    if sys.byteorder == "big":
        data.byteswap()
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(data.tobytes())


def clean_text(text: str) -> str:
    """whisper.cpp marks non-speech as [BLANK_AUDIO], (music) …: those are not words you said."""
    import re

    t = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", text or "")
    return " ".join(t.split())


def transcribe(data_dir: str, pcm, sample_rate: int = 16000, language: str = "auto", runner: Callable = subprocess.run) -> str:
    """Transcribe recorded audio with the installed engine and model. The temporary files are deleted."""
    eng = find_engine(data_dir)
    mid = installed_model(data_dir)
    if not eng or not mid:
        raise SetupError("voice input is not set up: Settings → Voice → Set up voice input")
    work = tempfile.mkdtemp(prefix="prometheus-stt-")
    try:
        wav = os.path.join(work, "speech.wav")
        write_wav(wav, pcm, sample_rate)
        out = os.path.join(work, "speech")
        cmd: List[str] = [eng, "-m", model_path(data_dir, mid), "-f", wav, "-l", language, "-nt", "-np", "-otxt", "-of", out, "-t", str(max(1, min(8, (os.cpu_count() or 4) - 1)))]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        r = runner(cmd, capture_output=True, text=True, timeout=TRANSCRIBE_TIMEOUT_S, creationflags=flags)
        if r.returncode != 0:
            raise SetupError(f"speech recognition failed (exit {r.returncode}): {(r.stderr or '').strip()[-300:]}")
        txt = out + ".txt"
        text = open(txt, encoding="utf-8", errors="replace").read() if os.path.exists(txt) else (r.stdout or "")
        return clean_text(text)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _ci_check(data_dir: str) -> int:
    """Used by the Windows workflow: real download, checksum, extraction and one transcription of a tone."""
    import math

    st = setup(data_dir, "tiny", lambda s, g, t: None)
    tone = [0.2 * math.sin(2 * math.pi * 440 * i / 16000) for i in range(16000 * 2)]
    text = transcribe(data_dir, tone)
    print({"status": st, "text": text})
    return 0 if st["ready"] else 1


if __name__ == "__main__":  # python -m app.services.local_stt --ci-check <folder>
    if len(sys.argv) == 3 and sys.argv[1] == "--ci-check":
        sys.exit(_ci_check(sys.argv[2]))
    print(__doc__)
