"""Build stand-in voice downloads for the end-to-end tests and print the overrides Atlas reads
(ATLAS_E2E_VOICE_FIXTURES). The files are small archives with placeholder contents: the e2e build
uses labelled stand-in engines, so nothing inside them is ever executed. They exercise Atlas's real
download, checksum and unpacking code against a server on 127.0.0.1. One entry is deliberately
served with the wrong checksum to test the integrity failure path.

Usage: python make_voice_fixtures.py <output dir> <port>
"""
import hashlib
import io
import json
import os
import sys
import tarfile
import zipfile


def tar_bz2(files):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:bz2") as t:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def zip_bytes(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def main():
    out, port = sys.argv[1], int(sys.argv[2])
    os.makedirs(out, exist_ok=True)
    filler = os.urandom(300_000)  # so progress has something to report
    engine = tar_bz2({"pkg/bin/README-fixture.txt": b"stand-in engine (never executed)\n", "pkg/lib/blob": filler})
    voice = tar_bz2({"voice/voice.onnx": filler, "voice/tokens.txt": b"_ 0\n", "voice/espeak-ng-data/phontab": b"x"})
    stt_engine = zip_bytes({"Release/README-fixture.txt": b"stand-in engine (never executed)\n", "Release/blob": filler})
    model = filler + b"stand-in whisper model"
    items = {
        "tts-engine-sherpa-onnx-2.0.1-windows": ("tts-win.tar.bz2", engine),
        "tts-engine-sherpa-onnx-2.0.1-linux": ("tts-linux.tar.bz2", engine),
        "stt-engine-whisper-cpp-1.8.2-windows": ("stt-win.zip", stt_engine),
        "voice-en_GB-alba-medium": ("alba.tar.bz2", voice),
        "stt-whisper-base": ("ggml-base.bin", model),
        "stt-whisper-tiny": ("ggml-tiny.bin", model + b"tiny"),
    }
    overrides = []
    for id_, (name, data) in items.items():
        with open(os.path.join(out, name), "wb") as f:
            f.write(data)
        overrides.append({"id": id_, "url": f"http://127.0.0.1:{port}/{name}", "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
    # Corrupt on purpose: the expected checksum is of different bytes than the server sends.
    with open(os.path.join(out, "ryan.tar.bz2"), "wb") as f:
        f.write(voice)
    overrides.append({"id": "voice-en_US-ryan-medium", "url": f"http://127.0.0.1:{port}/ryan.tar.bz2", "sha256": hashlib.sha256(b"something else").hexdigest(), "bytes": len(voice)})
    print(json.dumps(overrides))


if __name__ == "__main__":
    main()
