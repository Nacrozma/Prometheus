"""Voice input for the desktop app: the guided setup dialog and the recorder that uses the local engine.

`make_voice_input(data_dir)` returns what Companion and ORBIT use for Talk:
1. the whisper.cpp engine set up from Settings → Voice (works in the installed app), else
2. the Python Whisper pipeline (`gui_orb.WhisperVoiceThread`, when running from source with it installed), else
3. None (Talk is disabled and says how to set it up).
Both recorders have the same signals, so the pages do not care which one they got.
"""

from __future__ import annotations

import threading
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QButtonGroup, QDialog, QLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton, QRadioButton, QVBoxLayout

from ..services import local_stt as L
from . import theme as T
from .widgets import label


class LocalVoiceThread(QThread):
    """Push-to-talk recorder (sounddevice) transcribed by the local whisper.cpp engine. Same interface as
    gui_orb.WhisperVoiceThread: start_recording() → bool, stop_recording(), and the three signals."""

    transcription_done = pyqtSignal(str)
    status_signal = pyqtSignal(str)
    audio_level_signal = pyqtSignal(float)
    MIN_SECONDS = 0.35
    MAX_SECONDS = 120

    def __init__(self, data_dir: str, sample_rate: int = 16000):
        super().__init__()
        self.data_dir, self.sample_rate = data_dir, sample_rate
        self.is_recording = False
        self.audio_data: list = []

    def start_recording(self) -> bool:
        if self.isRunning():
            self.status_signal.emit("STILL TRANSCRIBING - TRY AGAIN IN A MOMENT")
            return False
        self.audio_data = []
        self.is_recording = True
        self.start()
        return True

    def stop_recording(self) -> None:
        self.is_recording = False

    def run(self) -> None:
        try:
            import numpy as np
            import sounddevice as sd
        except Exception as e:
            self.is_recording = False
            self.status_signal.emit(f"MICROPHONE ERROR: audio libraries unavailable ({type(e).__name__})")
            return
        self.status_signal.emit("LISTENING...")

        def callback(indata, frames, time_info, status):
            if self.is_recording:
                self.audio_data.append(indata.copy())
                rms = float(np.sqrt(np.mean(indata ** 2))) if len(indata) else 0.0
                self.audio_level_signal.emit(float(np.clip(rms * 5.5, 0.0, 1.0)))

        try:
            with sd.InputStream(samplerate=self.sample_rate, channels=1, dtype="float32", callback=callback):
                waited = 0
                while self.is_recording and waited < self.MAX_SECONDS * 1000:
                    self.msleep(40)
                    waited += 40
        except Exception as e:  # no microphone, device busy, permission denied
            self.is_recording = False
            self.audio_level_signal.emit(0.0)
            self.status_signal.emit(f"MICROPHONE ERROR: {e}")
            return
        self.is_recording = False
        self.audio_level_signal.emit(0.0)
        if not self.audio_data:
            return
        pcm = np.concatenate(self.audio_data, axis=0).flatten()
        self.audio_data = []
        if len(pcm) < self.sample_rate * self.MIN_SECONDS:
            self.status_signal.emit("RECORDING TOO SHORT - IGNORED")
            return
        self.status_signal.emit("TRANSCRIBING AUDIO...")
        try:
            text = L.transcribe(self.data_dir, pcm, self.sample_rate)
        except Exception as e:
            self.status_signal.emit(f"STT ERROR: {e}")
            return
        finally:
            pcm[:] = 0
        self.transcription_done.emit(text)


def make_voice_input(data_dir: str):
    if L.status(data_dir)["ready"]:
        return LocalVoiceThread(data_dir)
    import gui_orb as g

    return g.WhisperVoiceThread() if g.VOICE_INPUT_AVAILABLE else None


def voice_input_text(voice) -> str:
    if isinstance(voice, LocalVoiceThread):
        return "Voice input: on this computer (whisper.cpp)"
    if voice is not None:
        return "Voice input: on this computer (Whisper)"
    return "Voice input: not set up — Settings → Voice → Set up voice input"


class _Job(QThread):
    progress = pyqtSignal(str, int, int)
    finished_ok = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, data_dir: str, model_id: str):
        super().__init__()
        self.data_dir, self.model_id = data_dir, model_id
        self.cancel = threading.Event()

    def run(self) -> None:
        try:
            st = L.setup(self.data_dir, self.model_id, lambda s, g, t: self.progress.emit(s, g, t), self.cancel)
            self.finished_ok.emit(st)
        except L.Cancelled:
            self.failed.emit("Cancelled. Nothing half-downloaded was kept.")
        except Exception as e:
            self.failed.emit(str(e))


class VoiceSetupDialog(QDialog):
    """Set up voice input: choose a model, see exactly what is downloaded from where, download with progress,
    verified by checksum; cancel at any time."""

    ready = pyqtSignal()

    def __init__(self, data_dir: str, parent=None):
        super().__init__(parent)
        self.data_dir = data_dir
        self.job: Optional[_Job] = None
        self.setWindowTitle("Set up voice input")
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)  # wrapped text is never clipped
        lay.addWidget(label("Set up voice input", "h2"))
        lay.addWidget(label("Prometheus will download a speech-recognition engine and one model, then turn speech into text on this computer. Your voice is never sent anywhere; recordings are kept in memory only while they are transcribed.", "sub"))
        st = L.status(data_dir)
        self.state = label(str(st["text"]), "faint")
        lay.addWidget(self.state)
        self.group = QButtonGroup(self)
        current = st["model"] or "base"
        for mid, a in L.MODELS.items():
            rb = QRadioButton(f"{a.name}  ·  {a.size_mb} MB")
            rb.setChecked(mid == current)
            rb.setProperty("model", mid)
            self.group.addButton(rb)
            lay.addWidget(rb)
        src = []
        if not st["engine"]:
            src.append(f"Engine: {L.ENGINE_WINDOWS.name} — {L.ENGINE_WINDOWS.size_mb} MB from github.com/ggml-org/whisper.cpp" if st["engine_downloadable"] else "Engine: install whisper.cpp yourself so that whisper-cli is on PATH (only Windows downloads are offered here).")
        src.append("Model: from huggingface.co/ggerganov/whisper.cpp. " + L.MODEL_LICENCE)
        src.append("Every file is checked against its published SHA-256 before use; files are stored in your Prometheus data folder (voice/).")
        for line in src:  # one label per line: multi-line wrapped labels can be measured too short
            lay.addWidget(label(line, "faint"))
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setVisible(False)
        lay.addWidget(self.bar)
        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        lay.addWidget(self.msg)
        row = QHBoxLayout()
        self.remove_btn = QPushButton("Remove voice files")
        self.remove_btn.setEnabled(bool(st["model"]) or bool(st["engine"] and st["engine_downloadable"]))
        self.remove_btn.clicked.connect(self._remove)
        row.addWidget(self.remove_btn)
        row.addStretch(1)
        self.cancel_btn = QPushButton("Close")
        self.cancel_btn.clicked.connect(self._cancel)
        row.addWidget(self.cancel_btn)
        self.go_btn = QPushButton("Download and set up")
        self.go_btn.setObjectName("primary")
        self.go_btn.setDefault(True)
        self.go_btn.clicked.connect(self._start)
        row.addWidget(self.go_btn)
        lay.addLayout(row)
        self.resize(600, self.heightForWidth(600) if self.hasHeightForWidth() else self.sizeHint().height())

    def model_id(self) -> str:
        b = self.group.checkedButton()
        return b.property("model") if b else "base"

    def _start(self) -> None:
        self.go_btn.setEnabled(False)
        self.remove_btn.setEnabled(False)
        for b in self.group.buttons():
            b.setEnabled(False)
        self.bar.setVisible(True)
        self.bar.setValue(0)
        self.cancel_btn.setText("Cancel")
        self.msg.setStyleSheet("")
        self.msg.setText("Starting…")
        self.job = _Job(self.data_dir, self.model_id())
        self.job.progress.connect(self._progress)
        self.job.finished_ok.connect(self._done)
        self.job.failed.connect(self._failed)
        self.job.start()

    def _progress(self, stage: str, got: int, total: int) -> None:
        self.bar.setValue(int(1000 * got / total) if total else 0)
        what = "engine" if stage == "engine" else "model"
        self.msg.setText(f"Downloading the {what}: {got / 1048576:.1f} of {total / 1048576:.0f} MB")

    def _done(self, st: dict) -> None:
        self.job = None
        self.bar.setValue(1000)
        self.cancel_btn.setText("Done")
        self.state.setText(str(st["text"]))
        self.msg.setStyleSheet(f"color: {T.OK};")
        self.msg.setText("Voice input is ready. Talk now works in the Companion and in ORBIT." if st["ready"] else str(st["text"]))
        self.remove_btn.setEnabled(True)
        if st["ready"]:
            self.ready.emit()

    def _failed(self, why: str) -> None:
        self.job = None
        self.msg.setStyleSheet(f"color: {T.ERR};")
        self.msg.setText(f"Voice input was not set up: {why}")
        self.go_btn.setEnabled(True)
        self.go_btn.setText("Try again")
        self.cancel_btn.setText("Close")
        for b in self.group.buttons():
            b.setEnabled(True)

    def _remove(self) -> None:
        L.remove(self.data_dir)
        st = L.status(self.data_dir)
        self.state.setText(str(st["text"]))
        self.msg.setText("Voice files removed. Talk is off until you set it up again.")
        self.remove_btn.setEnabled(False)
        self.ready.emit()  # pages re-check what they can use

    def _cancel(self) -> None:
        if self.job is not None:
            self.job.cancel.set()
            self.msg.setText("Cancelling…")
            return
        self.accept()

    def closeEvent(self, e) -> None:
        if self.job is not None:
            self.job.cancel.set()
            self.job.wait(5000)
        super().closeEvent(e)


__all__ = ["LocalVoiceThread", "VoiceSetupDialog", "make_voice_input", "voice_input_text"]
