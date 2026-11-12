"""One Prometheus per user. A second launch asks the running one to come forward, then exits.
Uses a Qt local socket (a named pipe on Windows, a Unix socket elsewhere), so it needs no
platform-specific code."""

from __future__ import annotations

import getpass
import hashlib

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket


def server_name() -> str:
    try:
        user = getpass.getuser()
    except Exception:
        user = "user"
    return "prometheus-desktop-" + hashlib.sha256(user.encode()).hexdigest()[:16]


class SingleInstance(QObject):
    #: Emitted in the first instance when another launch asked it to come forward.
    activated = pyqtSignal()

    def __init__(self, name: str | None = None):
        super().__init__()
        self.name = name or server_name()
        self.server: QLocalServer | None = None

    def already_running(self) -> bool:
        """True if another instance answered (it has been asked to come forward)."""
        sock = QLocalSocket()
        sock.connectToServer(self.name)
        if sock.waitForConnected(500):
            sock.write(b"activate\n")
            sock.flush()
            sock.waitForBytesWritten(500)
            sock.disconnectFromServer()
            return True
        return False

    def listen(self) -> bool:
        self.server = QLocalServer(self)
        if not self.server.listen(self.name):
            # A stale socket from a crash: remove it and try once more.
            QLocalServer.removeServer(self.name)
            if not self.server.listen(self.name):
                return False
        self.server.newConnection.connect(self._on_connection)
        return True

    def _on_connection(self) -> None:
        assert self.server is not None
        while self.server.hasPendingConnections():
            conn = self.server.nextPendingConnection()
            if conn is None:
                break
            conn.waitForReadyRead(300)
            if bytes(conn.readAll().data()).startswith(b"activate"):
                self.activated.emit()
            conn.disconnectFromServer()

    def close(self) -> None:
        if self.server is not None:
            self.server.close()
            self.server = None
