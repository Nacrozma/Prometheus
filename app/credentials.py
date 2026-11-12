"""Provider keys in the operating system's credential store (Windows Credential Manager first).

Keys are never written to the desktop settings file or to logs. At start-up the stored keys are put
into this process's environment, which is where the core already reads them; a key that is already in
the environment (or in a .env file) wins, so terminal users and existing .env setups keep working.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

SERVICE = "Prometheus Desktop"

# Every key the core reads, and what it is for. Ollama needs none.
KNOWN_KEYS: Dict[str, str] = {
    "OPENROUTER_API_KEY": "OpenRouter",
    "GROQ_API_KEY": "Groq",
    "CEREBRAS_API_KEY": "Cerebras",
    "TAVILY_API_KEY": "Tavily (web search)",
}


class CredentialError(Exception):
    pass


def mask(value: str) -> str:
    """Show only enough of a key to recognise it."""
    v = value.strip()
    return "••••" if len(v) < 12 else f"{v[:4]}…{v[-4:]}"


class CredentialStore:
    def __init__(self, backend=None):
        self._kr = backend
        self.error = ""
        if self._kr is None:
            try:
                import keyring  # type: ignore[import-not-found]
                from keyring.backends import fail  # type: ignore[import-not-found]

                if isinstance(keyring.get_keyring(), fail.Keyring):
                    raise CredentialError("no secure credential store is available on this system")
                self._kr = keyring
            except CredentialError as e:
                self.error = str(e)
            except Exception as e:  # keyring missing or broken
                self.error = f"the secure credential store could not be opened ({type(e).__name__})"

    @property
    def available(self) -> bool:
        return self._kr is not None

    def _check(self, name: str) -> None:
        if name not in KNOWN_KEYS:
            raise CredentialError(f"unknown key name '{name}'")
        if not self.available:
            raise CredentialError(self.error or "no secure credential store")

    def get(self, name: str) -> Optional[str]:
        self._check(name)
        try:
            return self._kr.get_password(SERVICE, name)
        except Exception as e:
            raise CredentialError(f"could not read {KNOWN_KEYS[name]} key: {type(e).__name__}") from None

    def set(self, name: str, value: str) -> None:
        self._check(name)
        value = value.strip()
        if not value or len(value) > 512 or any(c.isspace() for c in value):
            raise CredentialError("that does not look like an API key")
        try:
            self._kr.set_password(SERVICE, name, value)
        except Exception as e:
            raise CredentialError(f"could not save the {KNOWN_KEYS[name]} key: {type(e).__name__}") from None
        os.environ[name] = value

    def delete(self, name: str) -> None:
        self._check(name)
        try:
            self._kr.delete_password(SERVICE, name)
        except Exception:
            pass  # not stored: nothing to remove
        os.environ.pop(name, None)

    def load_into_environ(self) -> List[str]:
        """Copy stored keys into the environment where none is set. Returns the names loaded."""
        loaded = []
        if not self.available:
            return loaded
        for name in KNOWN_KEYS:
            if os.environ.get(name, "").strip():
                continue
            try:
                value = self._kr.get_password(SERVICE, name)
            except Exception:
                continue
            if value:
                os.environ[name] = value
                loaded.append(name)
        return loaded

    def status(self) -> Dict[str, Dict[str, str]]:
        """Per key: where it comes from (credential store, environment/.env, or none) and a masked hint."""
        out = {}
        for name, label in KNOWN_KEYS.items():
            stored = None
            if self.available:
                try:
                    stored = self._kr.get_password(SERVICE, name)
                except Exception:
                    stored = None
            env = os.environ.get(name, "").strip()
            if stored and env == stored:
                source = "credential store"
            elif env:
                source = "environment or .env file"
            else:
                source = "not set"
            out[name] = {"label": label, "source": source, "hint": mask(env) if env else ""}
        return out
