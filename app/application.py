"""Start Prometheus Desktop: decide paths, load keys, enforce one instance, import the core, show the window."""

from __future__ import annotations

import faulthandler
import os
import sys
import traceback
from datetime import datetime

from . import APP_ID, APP_NAME, __version__


def make_icon():
    """The solar orb as a small painted icon (no image file needed)."""
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap, QRadialGradient

    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(size / 2, size / 2)
        g = QRadialGradient(c, size / 2)
        g.setColorAt(0.0, QColor("#FFF4C2"))
        g.setColorAt(0.45, QColor("#FFB300"))
        g.setColorAt(0.8, QColor("#E65100"))
        g.setColorAt(1.0, QColor(230, 81, 0, 0))
        p.setBrush(g)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(c, size / 2, size / 2)
        p.end()
        icon.addPixmap(pm)
    return icon


def _crash_log(data_dir: str, text: str) -> str:
    path = os.path.join(data_dir or os.path.expanduser("~"), "desktop_crash.log")
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n=== {datetime.now().isoformat(timespec='seconds')} {APP_NAME} {__version__} ===\n{text}\n")
    except OSError:
        pass
    return path


def _run_pending_import(settings, data_dir: str) -> str:
    """Import queued in Settings → Data. Runs before the core is imported, so nothing it holds in
    memory can overwrite the imported files."""
    source = settings.get("pending_import")
    if not source:
        return ""
    settings.set("pending_import", "")  # one attempt only, whatever happens
    from . import migration

    try:
        plan = migration.plan(source, data_dir)
        backup = migration.apply(plan)
    except migration.MigrationError as e:
        return f"Data import from {source} did not run: {e}"
    return f"Imported {len(plan.files)} files from {source}." + (f" Replaced files were backed up to {backup}." if backup else "")


def _self_test(app, win, core, paths, out_path: str) -> int:
    import json

    report = {"version": __version__, "frozen": bool(getattr(sys, "frozen", False)), "pages": {}, "data_dir": paths.data_dir}
    for name in win.pages:
        win.go(name)
        app.processEvents()
        msg = win.statusBar().currentMessage()
        report["pages"][name] = "error: " + msg if msg.startswith("Could not refresh") else "ok"
    report["tools"] = len(core.tool_names())
    report["dangerous_gated"] = all(core.is_dangerous(t) for t in ("write_file", "execute_shell", "run_code_forge", "apply_pending_patch"))
    report["calc"] = core.dispatch("engineering_calc", calc="convert_units", params={"value": 1, "from_unit": "in", "to_unit": "mm"})
    report["router_configured"] = bool(core.router.configured)
    report["ok"] = all(v == "ok" for v in report["pages"].values()) and report["dangerous_gated"]
    win.quit()
    core.shutdown()
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    return 0 if report["ok"] else 2


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    # --self-test=RESULT.json: start everything offscreen, check it, write a report and exit.
    # Used by the installer CI to prove the packaged app starts; touches only the folders given
    # by PROMETHEUS_HOME / PROMETHEUS_WORKSPACE (the CI sets throwaway ones).
    self_test = next((a.split("=", 1)[1] for a in argv if a.startswith("--self-test=")), "")
    if self_test:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QSurfaceFormat
    from PyQt6.QtWidgets import QApplication, QMessageBox, QSplashScreen

    # The orb needs a 3.3 core profile; it must be set before the application exists.
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    QSurfaceFormat.setDefaultFormat(fmt)

    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setDesktopFileName(APP_ID)
    app.setQuitOnLastWindowClosed(False)  # the tray may keep us alive; MainWindow quits explicitly

    from .single_instance import SingleInstance

    instance = SingleInstance(None if not self_test else f"prometheus-self-test-{os.getpid()}")
    if instance.already_running():
        return 0  # the running window was asked to come forward
    instance.listen()

    from . import bootstrap
    from .credentials import CredentialStore
    from .platform import current
    from .settings import DesktopSettings
    from .ui import theme

    app.setStyleSheet(theme.QSS)
    icon = make_icon()
    app.setWindowIcon(icon)
    platform = current()

    # Desktop settings live in the data folder, which depends on the environment and on any
    # existing source-checkout data, so resolve once without a chosen workspace, then again with it.
    first = bootstrap.resolve_paths(platform)
    settings = DesktopSettings(first.data_dir)
    paths = bootstrap.resolve_paths(platform, settings.get("workspace"))
    import_note = _run_pending_import(settings, paths.data_dir)
    bootstrap.apply(paths)
    try:
        faulthandler.enable(open(os.path.join(paths.data_dir, "desktop_faults.log"), "a"))
    except OSError:
        pass

    creds = CredentialStore()
    creds.load_into_environ()

    splash = QSplashScreen(icon.pixmap(256, 256))
    splash.showMessage(f"{APP_NAME} is waking up…", Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter, Qt.GlobalColor.white)
    splash.show()
    app.processEvents()

    try:
        from .services.core import Core

        core = Core()
        from .ui.main_window import MainWindow

        win = MainWindow(core, settings, creds, platform, paths, bootstrap.frozen(), icon)
    except Exception:
        text = traceback.format_exc()
        log = _crash_log(paths.data_dir, text)
        splash.close()
        if self_test:  # no dialogs in a headless check: report and exit
            import json

            with open(self_test, "w", encoding="utf-8") as f:
                json.dump({"ok": False, "error": text.strip().splitlines()[-1], "log": log}, f, indent=2)
            return 1
        QMessageBox.critical(None, f"{APP_NAME} could not start", f"{text.strip().splitlines()[-1]}\n\nDetails were written to {log}.")
        return 1

    if self_test:
        return _self_test(app, win, core, paths, self_test)
    instance.activated.connect(win.show_and_raise)
    if import_note:
        win.statusBar().showMessage(import_note, 0)
    if settings.load_error:
        win.statusBar().showMessage(f"Desktop settings were unreadable and were reset: {settings.load_error}", 0)
    win.show()
    splash.finish(win)
    if not settings.get("first_run_done"):
        settings.set("first_run_done", True)
        if not core.router.configured or core.router.active_providers == ["ollama"]:
            win.go("Settings")
            win.statusBar().showMessage("Welcome. Add a provider key (or start Ollama) to begin.", 0)

    def excepthook(t, v, tb):
        _crash_log(paths.data_dir, "".join(traceback.format_exception(t, v, tb)))
        sys.__excepthook__(t, v, tb)

    sys.excepthook = excepthook
    code = app.exec()
    core.shutdown()
    instance.close()
    return code
