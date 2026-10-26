"""
Stand-ins for the heavy / hardware-bound imports of gui_orb.py (audio devices,
Whisper, edge-tts, OpenGL) so its logic can be tested headless and fast, with
no microphone, speaker, GPU, model download or network.

Call install() BEFORE importing gui_orb. PyQt6 itself is real; the tests run it
on Qt's 'offscreen' platform.
"""
import os
import sys
import types


def _module(name, **attrs):
    mod = types.ModuleType(name)
    mod.__dict__.update(attrs)
    return mod


class _Stream:
    """Context-manager stand-in for sounddevice.InputStream / OutputStream."""
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeWhisperModel:
    def transcribe(self, audio):
        return {"text": "hello from a fake model"}


class _Communicate:
    def __init__(self, *args, **kwargs):
        pass

    async def stream(self):
        if False:
            yield {}


def install():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    gl = _module("OpenGL.GL")
    stubs = {
        "sounddevice": _module("sounddevice", InputStream=_Stream, OutputStream=_Stream,
                               CallbackStop=type("CallbackStop", (Exception,), {})),
        "soundfile": _module("soundfile", read=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stub"))),
        "edge_tts": _module("edge_tts", Communicate=_Communicate),
        "whisper": _module("whisper", load_model=lambda name: _FakeWhisperModel()),
        "OpenGL": _module("OpenGL", GL=gl),
        "OpenGL.GL": gl,
    }
    for name, mod in stubs.items():
        sys.modules.setdefault(name, mod)
