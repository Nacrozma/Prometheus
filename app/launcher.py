"""Entry point of the packaged application (PyInstaller builds Prometheus.exe from this file).

The core runs some work in a child Python process: generated code (`run_code`), Forge skill tests
and patch tests use `[sys.executable, "-I", script]` or `[sys.executable, "-m", module, ...]`. In the
packaged app `sys.executable` is Prometheus.exe, not python.exe, so without this those children
would start a second window (and be turned away by the single-instance check). Here the executable
answers exactly those two forms like a Python interpreter, with only the bundled standard library,
and starts the desktop application otherwise. This gives no capability a local user lacks: it runs
a file they name, as they could with any Python.
"""

from __future__ import annotations

import os
import runpy
import sys


def _child_python(argv) -> int | None:
    """Handle `-I script [args]` and `-m module [args]`. Returns an exit code, or None if not a child call."""
    if len(argv) < 3 or argv[1] not in ("-I", "-m"):
        return None
    try:
        if argv[1] == "-I":
            sys.argv = argv[2:]
            runpy.run_path(argv[2], run_name="__main__")
        else:
            sys.argv = [argv[2], *argv[3:]]
            runpy.run_module(argv[2], run_name="__main__", alter_sys=True)
    except SystemExit as e:
        code = e.code
        return code if isinstance(code, int) else (0 if code is None else 1)
    return 0


def run() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:  # started as a script (e.g. from a login entry) rather than with -m
        sys.path.insert(0, root)
    # A windowed executable has no console: give print() somewhere harmless to write.
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    if getattr(sys, "frozen", False):
        code = _child_python(sys.argv)
        if code is not None:
            return code
    from app.application import main

    return main()


if __name__ == "__main__":
    sys.exit(run())
