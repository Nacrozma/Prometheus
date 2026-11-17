"""Provider health for the desktop: a real connection test per configured provider.

The test asks the provider for its model list (an authenticated, read-only request that generates no
tokens) with a short timeout and no retries, measures the latency and checks that the configured model
is offered. Keys are never included in results or errors.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

TEST_TIMEOUT = 8.0


def _clean(msg: str, secrets: List[str]) -> str:
    for s in secrets:
        if s and len(s) > 6:
            msg = msg.replace(s, "•••")
    return msg[:240]


def test(core, name: str) -> Dict[str, Any]:
    router = core.router
    client = getattr(router, "_clients", {}).get(name)
    if client is None:
        return {"provider": name, "ok": False, "error": "Not configured (no key)."}
    started = time.perf_counter()
    try:
        page = client.client.with_options(timeout=TEST_TIMEOUT, max_retries=0).models.list()
        models = sorted({m.id for m in getattr(page, "data", []) or []})
    except Exception as e:
        key = getattr(client.client, "api_key", "")
        kind = type(e).__name__
        hint = "The server is not running on this computer (start it with “ollama serve”)." if name == "ollama" and "Connect" in kind else ""
        return {"provider": name, "ok": False, "error": hint or f"{kind}: {_clean(str(e), [key])}", "ms": round((time.perf_counter() - started) * 1000)}
    ms = round((time.perf_counter() - started) * 1000)
    return {"provider": name, "ok": True, "ms": ms, "models": models[:500], "model_count": len(models), "default_model": client.default_model, "default_offered": client.default_model in models if models else None}


def test_all(core) -> List[Dict[str, Any]]:
    return [test(core, n) for n in list(getattr(core.router, "_clients", {}))]


def set_model(name: str, model: str) -> List[str]:
    """Save a per-provider model choice (the HUD's own config) and apply it to the running router."""
    import gui_orb as g
    from gui_config import AppConfig

    cfg = AppConfig()
    overrides = dict(cfg.get("model_overrides") or {})
    if model:
        overrides[name] = model
    else:
        overrides.pop(name, None)
    cfg.set("model_overrides", overrides)
    cfg.save()
    return g.apply_router_settings(cfg)
