"""Turn-taking for ORBIT's continuous conversation (plain Python, unit-tested).

The microphone pipeline (`gui_orb.WhisperVoiceThread`) reports a real input level about 25 times a
second while it records. `TurnTaker` turns those levels into conversation events:

* ``speech``  – you started talking (level above the threshold for long enough);
* ``end``     – you stopped: speech lasted at least `min_speech` seconds and was followed by
  `silence` seconds below the threshold, so the recording is stopped and transcribed;
* ``idle``    – nothing but silence for `idle_timeout` seconds: listening stops (the microphone is
  never left open indefinitely without speech).

It never sees audio, only levels, and keeps nothing. Thresholds adapt to the room: the noise floor
is tracked while nobody speaks and the speech threshold sits above it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class TurnTaker:
    silence: float = 1.2  # seconds of quiet that end your turn
    min_speech: float = 0.35  # shorter sounds are clicks or coughs, not a turn
    idle_timeout: float = 30.0  # stop listening after this long with no speech at all
    sensitivity: float = 0.5  # 0 (needs loud speech) … 1 (picks up quiet speech)
    floor: float = 0.02
    _t0: Optional[float] = None
    _speech_start: Optional[float] = None
    _last_loud: Optional[float] = None
    _loud_run: float = 0.0
    _last_t: Optional[float] = None
    speaking: bool = False
    events: List[str] = field(default_factory=list)

    def threshold(self) -> float:
        margin = 0.10 - 0.07 * max(0.0, min(1.0, self.sensitivity))  # 0.10 … 0.03 above the floor
        return min(0.6, self.floor + margin)

    def reset(self, t: float) -> None:
        self._t0, self._speech_start, self._last_loud, self._last_t = t, None, None, t
        self._loud_run, self.speaking = 0.0, False
        self.events = []

    def feed(self, level: float, t: float) -> Optional[str]:
        """One level sample (0…1) at time t (seconds). Returns an event name or None."""
        if self._t0 is None:
            self.reset(t)
        dt = max(0.0, t - (self._last_t if self._last_t is not None else t))
        self._last_t = t
        # the room's noise floor: drops quickly to quiet moments (pauses between words), rises slowly to a
        # steady sound (a fan, traffic), so constant background noise stops counting as speech
        lv = min(level, 0.5)
        self.floor = (0.7 * self.floor + 0.3 * lv) if lv < self.floor else (self.floor + (lv - self.floor) * 0.03)
        loud = level >= self.threshold()
        if loud:
            self._loud_run += dt
            self._last_loud = t
            if not self.speaking and self._loud_run >= 0.12:
                self.speaking = True
                self._speech_start = t - self._loud_run
                return self._emit("speech")
        else:
            self._loud_run = 0.0
        if self.speaking and self._last_loud is not None and t - self._last_loud >= self.silence:
            spoken = self._last_loud - (self._speech_start if self._speech_start is not None else self._last_loud)
            self.speaking = False
            if spoken >= self.min_speech:
                return self._emit("end")
            self._speech_start = None  # too short: keep listening
            return None
        if not self.speaking and self._speech_start is None and self._t0 is not None and t - self._t0 >= self.idle_timeout and "idle" not in self.events:
            return self._emit("idle")
        return None

    def _emit(self, e: str) -> str:
        self.events.append(e)
        return e


#: What ORBIT's voice can and cannot do on this build, stated plainly in the interface.
LIMITS = (
    "Speech recognition runs on this computer (Whisper). The microphone is on only while ORBIT is "
    "listening, shown by the listening state and the level meter; nothing is recorded or kept.",
    "While Prometheus speaks, the microphone is paused so it does not hear itself (this build has no "
    "echo cancellation). Interrupt with Stop speaking, the Space key, or by pressing Talk: speech stops "
    "at once and ORBIT listens.",
    "Spoken replies use edge-tts, which sends the reply text to Microsoft's speech service. Mute speech "
    "in Settings → Voice to keep everything local.",
)
