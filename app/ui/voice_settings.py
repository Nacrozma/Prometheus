"""Settings → Voice → Spoken replies: on/off, engine (local or Microsoft online), voice, speed, test, local
voice setup/repair/removal. Every state shown comes from the speech service; nothing is assumed."""

from __future__ import annotations

import threading
from typing import Optional

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..services import speech as S
from . import theme as T
from .widgets import label

MS_DISCLOSURE = ("With Microsoft online speech, the text of every spoken reply is sent over the internet to Microsoft's speech "
                 "service, which returns the audio. It needs an internet connection. Your microphone audio is never sent (voice input "
                 "stays on this computer).")
LOCAL_TEXT = "Speech is generated on this computer by sherpa-onnx with a Piper voice. After setup it needs no internet and no reply text leaves the computer."


class SpokenReplies(QWidget):
    def __init__(self, speech, settings, data_dir: str, parent=None):
        super().__init__(parent)
        self.speech, self.settings, self.data_dir = speech, settings, data_dir
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(label("SPOKEN REPLIES", "eyebrow"))
        self.enabled = QCheckBox("Speak Prometheus's replies (Companion and ORBIT)")
        self.enabled.setChecked(bool(settings.get("speech_enabled")))
        self.enabled.toggled.connect(self._toggle)
        lay.addWidget(self.enabled)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setAccessibleName("Spoken replies status")
        lay.addWidget(self.status)

        self.engines = QButtonGroup(self)
        self.local_rb = QRadioButton("On this computer (local voice)")
        self.ms_rb = QRadioButton("Microsoft online voice")
        for rb, key in ((self.local_rb, "local"), (self.ms_rb, "microsoft")):
            rb.setProperty("engine", key)
            self.engines.addButton(rb)
            lay.addWidget(rb)
            lay.addWidget(label(LOCAL_TEXT if key == "local" else MS_DISCLOSURE, "faint"))
        (self.local_rb if settings.get("speech_engine") != "microsoft" else self.ms_rb).setChecked(True)
        self.engines.buttonClicked.connect(self._engine_clicked)

        row = QHBoxLayout()
        row.addWidget(QLabel("Voice"))
        self.voice = QComboBox()
        self.voice.setAccessibleName("Voice")
        self.voice.setMinimumWidth(280)
        self.voice.activated.connect(self._voice_chosen)
        row.addWidget(self.voice, 1)
        lay.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("Speed"))
        self.speed = QSlider(Qt.Orientation.Horizontal)
        self.speed.setRange(int(S.SPEED_MIN * 100), int(S.SPEED_MAX * 100))
        self.speed.setSingleStep(5)
        self.speed.setPageStep(10)
        self.speed.setAccessibleName("Speaking speed")
        self.speed.setValue(int(S.clamp_speed(settings.get("speech_speed")) * 100))
        self.speed_lbl = QLabel()
        self.speed.valueChanged.connect(self._speed_changed)
        row.addWidget(self.speed, 1)
        row.addWidget(self.speed_lbl)
        reset = QPushButton("Normal")
        reset.setToolTip("Back to normal speed (1.0×)")
        reset.clicked.connect(lambda: self.speed.setValue(100))
        row.addWidget(reset)
        lay.addLayout(row)

        row = QHBoxLayout()
        self.test_btn = QPushButton("Test voice")
        self.test_btn.setObjectName("primary")
        self.test_btn.setToolTip("Generate and play a sentence with the chosen engine, voice and speed")
        self.test_btn.clicked.connect(self._test)
        row.addWidget(self.test_btn)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.speech.stop)
        row.addWidget(self.stop_btn)
        self.setup_btn = QPushButton("Set up local voice…")
        self.setup_btn.clicked.connect(self._setup)
        row.addWidget(self.setup_btn)
        row.addStretch(1)
        lay.addLayout(row)
        self.result = QLabel("")
        self.result.setWordWrap(True)
        self.result.setAccessibleName("Voice test result")
        lay.addWidget(self.result)
        self._speed_changed(self.speed.value(), save=False)
        self.refresh()

    # --- state ---
    def engine(self) -> str:
        b = self.engines.checkedButton()
        return b.property("engine") if b else "local"

    def refresh(self) -> None:
        eng = self.engine()
        st = S.local_status(self.data_dir)
        self.voice.clear()
        if eng == "local":
            for vid, text in self.speech.service.engines["local"].voices():
                self.voice.addItem(text, vid)
            current = self.settings.get("speech_voice_local")
            if self.voice.count() == 0:
                self.voice.addItem("No local voice installed — set up the local voice", "")
                self.voice.setEnabled(False)
            else:
                self.voice.setEnabled(True)
                i = self.voice.findData(current)
                if i < 0:  # the saved voice is gone: use an installed one and say so
                    self.settings.set("speech_voice_local", self.voice.itemData(0))
                    if current:
                        self.result.setText(f"The voice you had chosen is no longer installed; using {self.voice.itemText(0).split(' · ')[0]}.")
                    i = 0
                self.voice.setCurrentIndex(i)
            self.setup_btn.setText("Repair or add voices…" if st["engine"] else "Set up local voice…")
        else:
            for vid, text in self.speech.service.engines["microsoft"].voices():
                self.voice.addItem(text, vid)
            self.voice.setEnabled(True)
            i = self.voice.findData(self.settings.get("speech_voice_online"))
            self.voice.setCurrentIndex(max(0, i))
        self.setup_btn.setVisible(eng == "local" and bool(st["supported"]))
        ok, why = self.speech.availability()
        on = self.settings.get("speech_enabled")
        where = "on this computer" if eng == "local" else "online by Microsoft (reply text is sent to Microsoft)"
        if not on:
            text, colour = "Off: replies are shown as text only. Voice input is not affected.", T.TEXT_SECONDARY
        elif ok:
            text, colour = f"On · speech is generated {where}.", T.OK
        else:
            text, colour = f"On, but not ready: {why}", T.WARN
        if eng == "local" and st["engine"]:
            text += f"  Local voice files: {st['bytes'] / 1048576:.0f} MB."
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {colour};")
        self.test_btn.setEnabled(ok)

    # --- changes ---
    def _toggle(self, on: bool) -> None:
        self.settings.set("speech_enabled", bool(on))
        if not on:
            self.speech.stop()
        self.refresh()

    def _engine_clicked(self, btn) -> None:
        key = btn.property("engine")
        if key == self.settings.get("speech_engine"):
            return
        if key == "microsoft":
            box = QMessageBox(self)
            box.setWindowTitle("Use Microsoft online voice?")
            box.setText(MS_DISCLOSURE)
            box.setInformativeText("Choose this only if you are comfortable with reply text being sent to Microsoft.")
            use = box.addButton("Use Microsoft online", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("Keep the local voice", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is not use:
                self.local_rb.setChecked(True)
                return
        self.speech.stop()
        self.settings.set("speech_engine", key)
        self.result.setText("")
        self.refresh()

    def _voice_chosen(self, i: int) -> None:
        vid = self.voice.itemData(i)
        if not vid:
            return
        self.settings.set("speech_voice_local" if self.engine() == "local" else "speech_voice_online", vid)
        self.refresh()

    def _speed_changed(self, v: int, save: bool = True) -> None:
        sp = S.clamp_speed(v / 100)
        self.speed_lbl.setText(f"{sp:.2f}×")
        if save:
            self.settings.set("speech_speed", float(sp))

    def _test(self) -> None:
        self.test_btn.setEnabled(False)
        self.result.setStyleSheet("")
        self.result.setText("Generating speech…")

        def done(ok: bool, msg: str) -> None:
            self.result.setStyleSheet(f"color: {T.OK if ok else T.ERR};")
            self.result.setText(msg)
            self.test_btn.setEnabled(True)

        self.speech.test(done, owner=self)

    def _setup(self) -> None:
        dlg = LocalVoiceDialog(self.data_dir, self)
        dlg.changed.connect(self.refresh)
        dlg.exec()
        self.refresh()


class _Job(QThread):
    progress = pyqtSignal(str, int, int)
    ok = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, data_dir: str, voices, repair: bool):
        super().__init__()
        self.data_dir, self.voices, self.repair = data_dir, voices, repair
        self.cancel = threading.Event()

    def run(self) -> None:
        try:
            if self.repair:
                S.remove_local(self.data_dir)
            self.ok.emit(S.setup_local(self.data_dir, self.voices, lambda s, g, t: self.progress.emit(s, g, t), self.cancel))
        except S.Cancelled:
            self.failed.emit("Cancelled. Nothing half-downloaded was kept.")
        except Exception as e:
            self.failed.emit(str(e))


class LocalVoiceDialog(QDialog):
    """Set up, repair or remove the local voice: what is downloaded, from where, how big, which licence."""

    changed = pyqtSignal()

    def __init__(self, data_dir: str, parent=None):
        super().__init__(parent)
        self.data_dir = data_dir
        self.job: Optional[_Job] = None
        self.setWindowTitle("Local voice")
        lay = QVBoxLayout(self)
        lay.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        lay.setSpacing(8)
        lay.addWidget(label("Speak on this computer", "h2"))
        lay.addWidget(label("Prometheus downloads a speech engine and the voices you choose, checks each file against its published SHA-256, and from then on speaks without the internet. Reply text never leaves your computer for speech.", "sub"))
        st = S.local_status(data_dir)
        self.state = label(str(st["text"]), "faint")
        lay.addWidget(self.state)
        pk = S.platform_key()
        if pk:
            rt = S.RUNTIMES[pk]
            lay.addWidget(label(f"Engine: {rt.name}, {rt.size_mb} MB download, from github.com/k2-fsa/sherpa-onnx." + (" Already installed." if st["engine"] else ""), "faint"))
        self.checks = {}
        for vid, v in S.LOCAL_VOICES.items():
            installed = vid in st["voices"]
            cb = QCheckBox(f"{v.name} — {v.language}, {v.character} · {v.asset.size_mb} MB · licence: {v.licence}" + ("  (installed)" if installed else ""))
            cb.setChecked(installed or vid == S.DEFAULT_LOCAL_VOICE)
            self.checks[vid] = cb
            lay.addWidget(cb)
        lay.addWidget(label("Voices come from github.com/k2-fsa/sherpa-onnx (Piper voices). Files are stored in your Prometheus data folder (speech/); about 3× the download size of free disk space is needed while installing.", "faint"))
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setVisible(False)
        lay.addWidget(self.bar)
        self.msg = label("", "")
        lay.addWidget(self.msg)
        row = QHBoxLayout()
        self.remove_btn = QPushButton("Remove local voice files")
        self.remove_btn.setEnabled(bool(st["engine"] or st["voices"]))
        self.remove_btn.clicked.connect(self._remove)
        row.addWidget(self.remove_btn)
        self.repair_btn = QPushButton("Repair (download again)")
        self.repair_btn.setEnabled(bool(st["engine"] or st["voices"]))
        self.repair_btn.clicked.connect(lambda: self._start(repair=True))
        row.addWidget(self.repair_btn)
        row.addStretch(1)
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self._close)
        row.addWidget(self.close_btn)
        self.go_btn = QPushButton("Download and set up")
        self.go_btn.setObjectName("primary")
        self.go_btn.setEnabled(pk is not None)
        self.go_btn.clicked.connect(lambda: self._start(repair=False))
        row.addWidget(self.go_btn)
        lay.addLayout(row)
        self.resize(640, self.sizeHint().height())

    def chosen(self):
        return [vid for vid, cb in self.checks.items() if cb.isChecked()]

    def _busy(self, on: bool) -> None:
        for w in (self.go_btn, self.repair_btn, self.remove_btn, *self.checks.values()):
            w.setEnabled(not on)
        self.bar.setVisible(on or self.bar.value() > 0)
        self.close_btn.setText("Cancel" if on else "Close")

    def _start(self, repair: bool) -> None:
        voices = self.chosen()
        if not voices:
            self.msg.setText("Choose at least one voice.")
            return
        if repair and QMessageBox.question(self, "Repair local voice", "Delete the local voice files and download them again?") != QMessageBox.StandardButton.Yes:
            return
        self._busy(True)
        self.bar.setValue(0)
        self.msg.setStyleSheet("")
        self.msg.setText("Starting…")
        self.job = _Job(self.data_dir, voices, repair)
        self.job.progress.connect(self._progress)
        self.job.ok.connect(self._done)
        self.job.failed.connect(self._failed)
        self.job.start()

    def _progress(self, stage: str, got: int, total: int) -> None:
        self.bar.setValue(int(1000 * got / total) if total else 0)
        what = "the engine" if stage == "engine" else f"the voice {S.LOCAL_VOICES[stage].name}" if stage in S.LOCAL_VOICES else stage
        self.msg.setText(f"Downloading {what}: {got / 1048576:.1f} of {total / 1048576:.0f} MB")

    def _done(self, st: dict) -> None:
        self.job = None
        self._busy(False)
        self.bar.setValue(1000)
        self.state.setText(str(st["text"]))
        self.msg.setStyleSheet(f"color: {T.OK};")
        self.msg.setText("The local voice is ready. Choose it in Settings → Voice and press Test voice.")
        self.changed.emit()

    def _failed(self, why: str) -> None:
        self.job = None
        self._busy(False)
        self.msg.setStyleSheet(f"color: {T.ERR};")
        self.msg.setText(f"Not set up: {why}")
        self.changed.emit()

    def _remove(self) -> None:
        if QMessageBox.question(self, "Remove local voice", "Delete the local speech engine and all local voices? Voice input files are not touched.") != QMessageBox.StandardButton.Yes:
            return
        S.remove_local(self.data_dir)
        st = S.local_status(self.data_dir)
        self.state.setText(str(st["text"]))
        self.msg.setText("Local voice files removed. Spoken replies with the local engine are off until you set it up again.")
        self.remove_btn.setEnabled(False)
        self.repair_btn.setEnabled(False)
        self.changed.emit()

    def _close(self) -> None:
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
