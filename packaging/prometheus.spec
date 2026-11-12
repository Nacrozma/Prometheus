# PyInstaller spec for Prometheus Desktop (one-folder build). Run from the repository root:
#   pyinstaller packaging/prometheus.spec --noconfirm
# Only source files and two read-only reference files are bundled. No personal state (memory,
# sessions, audit log, settings) and no .env or keys: those live in the user's data folder and the
# OS credential store, never in the install folder.
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))  # noqa: F821 (SPECPATH is defined by PyInstaller)

CORE_MODULES = [
    "prometheus", "gui_orb", "gui_markdown", "gui_config", "gui_session", "gui_birth", "state_io",
    "safety", "memory_graph", "skill_forge", "patch_gate", "reflection", "engineering", "arm_sim",
    "obsidian_memory", "sibling_adapter",
]

a = Analysis(  # noqa: F821
    [os.path.join(ROOT, "app", "launcher.py")],
    pathex=[ROOT],
    hiddenimports=CORE_MODULES + ["app.application", "keyring.backends.Windows", "win32ctypes.core", "unittest"],
    datas=[
        (os.path.join(ROOT, "permissions.example.json"), "."),
        (os.path.join(ROOT, "evals", "results.json"), "evals"),
    ],
    # Voice input (Whisper/PyTorch) is optional and multi-gigabyte: not bundled. Settings → Voice says so.
    excludes=["torch", "whisper", "openai_whisper", "tkinter", "matplotlib", "IPython", "pytest", "PyQt6.QtWebEngineCore", "PyQt6.QtQuick", "PyQt6.QtQml", "PyQt6.QtMultimedia"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Prometheus",
    console=False,
    icon=os.path.join(SPECPATH, "prometheus.ico"),  # noqa: F821
    version=os.path.join(SPECPATH, "version_info.txt") if os.path.exists(os.path.join(SPECPATH, "version_info.txt")) else None,  # noqa: F821
)
coll = COLLECT(exe, a.binaries, a.datas, name="Prometheus")  # noqa: F821
