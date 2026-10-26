"""
gui_config.py — persistent settings for the Prometheus HUD.

Everything the operator can change at runtime (voice, speech rate, model
overrides, provider priority, fallback chain, intro animation, console size,
window geometry) lives in prometheus_config.json next to this file.

Design rules:
  * A corrupt or hand-edited file must never stop the app from launching —
    every value is validated/coerced, and anything invalid falls back to
    its default rather than raising.
  * Writes are atomic (temp file + os.replace) so a crash mid-save can't
    leave a half-written config behind.
  * auto-approve for dangerous tools is deliberately NOT a persisted
    setting — a safety bypass shouldn't silently carry over between launches.
"""

import copy
import json
import os
import re
import tempfile
from typing import Any, Dict

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prometheus_config.json")

DEFAULTS: Dict[str, Any] = {
    "version": 1,
    "voice": "en-US-ChristopherNeural",
    "speech_enabled": True,
    "speech_rate": 0,                 # percent, -50..+100
    "fallback_models": ["openai/gpt-4o", "google/gemini-2.0-flash-001"],
    "model_overrides": {},            # {"groq": "llama-3.3-70b-versatile", ...}
    "provider_priority": [],          # [] = use prometheus.py's PROVIDER_PRIORITY
    "play_intro": True,               # the star-birth startup animation
    "max_console_entries": 400,
    "window_geometry": "",            # base64 QByteArray from saveGeometry()
}

_VOICE_RE = re.compile(r"^[A-Za-z0-9\-]{5,80}$")


def _coerce(key: str, value: Any) -> Any:
    """Return a valid value for `key`, or the default if `value` is unusable."""
    default = DEFAULTS.get(key)
    try:
        if key == "voice":
            v = str(value).strip()
            return v if _VOICE_RE.match(v) else default
        if key in ("speech_enabled", "play_intro"):
            return bool(value) if isinstance(value, bool) else default
        if key == "speech_rate":
            return max(-50, min(100, int(value)))
        if key == "max_console_entries":
            return max(50, min(5000, int(value)))
        if key == "fallback_models":
            if not isinstance(value, list):
                return default
            return [str(x).strip() for x in value if isinstance(x, str) and x.strip()]
        if key == "model_overrides":
            if not isinstance(value, dict):
                return default
            return {str(k).strip(): str(v).strip() for k, v in value.items()
                    if isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip()}
        if key == "provider_priority":
            if not isinstance(value, list):
                return default
            seen, out = set(), []
            for x in value:
                if isinstance(x, str) and x.strip() and x not in seen:
                    seen.add(x)
                    out.append(x.strip())
            return out
        if key == "window_geometry":
            return value if isinstance(value, str) else default
        if key == "version":
            return DEFAULTS["version"]
    except (TypeError, ValueError):
        return copy.deepcopy(default)
    return value  # unknown key: preserved untouched for forward compatibility


class AppConfig:
    def __init__(self, path: str = CONFIG_FILE):
        self.path = path
        self.data: Dict[str, Any] = copy.deepcopy(DEFAULTS)
        self.load_error: str = ""
        self.load()

    def load(self) -> None:
        self.data = copy.deepcopy(DEFAULTS)
        self.load_error = ""
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                raise ValueError("top-level JSON value is not an object")
            for key, value in raw.items():
                self.data[key] = _coerce(key, value)
        except Exception as e:  # corrupt file: keep defaults, remember why
            self.data = copy.deepcopy(DEFAULTS)
            self.load_error = f"{type(e).__name__}: {e}"

    def save(self) -> bool:
        try:
            dir_name = os.path.dirname(self.path) or "."
            fd, tmp = tempfile.mkstemp(dir=dir_name, prefix="cfg_", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)
            return True
        except Exception as e:
            self.load_error = f"save failed: {e}"
            return False

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def get(self, key: str, fallback: Any = None) -> Any:
        return self.data.get(key, fallback)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = _coerce(key, value)

    def update(self, values: Dict[str, Any]) -> None:
        for k, v in values.items():
            self.set(k, v)
