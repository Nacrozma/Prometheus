"""Workspace: the one folder the workspace tools may use, its files, and a safe preview.
The folder is the backend's boundary (WORKSPACE_DIR); browsing here never widens it."""

from __future__ import annotations

import os

from PyQt6.QtCore import QDir, QUrl
from PyQt6.QtGui import QDesktopServices, QFileSystemModel
from PyQt6.QtWidgets import QHBoxLayout, QPlainTextEdit, QPushButton, QSplitter, QTreeView

from ..widgets import Page, label

MAX_PREVIEW = 200_000
TEXT_EXT = {".txt", ".md", ".py", ".json", ".csv", ".toml", ".yaml", ".yml", ".ini", ".cfg", ".js", ".ts", ".html", ".css", ".rs", ".c", ".h", ".cpp", ".log", ".xml", ".sql", ".sh", ".bat", ".ps1"}


class WorkspacePage(Page):
    title = "Workspace"
    subtitle = "The folder Prometheus may read and change with its file and shell tools. Everything outside it is refused by the core."

    def __init__(self, core, parent=None):
        super().__init__(core, parent)
        self.root = core.paths()["workspace"]
        self.where = label(f"Workspace: {self.root}", "sub", selectable=True)
        self.content.addWidget(self.where)
        self.content.addWidget(label("Change the folder in Settings → Workspace (applies the next time Prometheus starts). Prometheus's own state files and any .env file are off-limits to the tools even inside the workspace.", "faint"))
        row = QHBoxLayout()
        open_btn = QPushButton("Open in file manager")
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.root)))
        row.addStretch(1)
        row.addWidget(open_btn)
        self.content.addLayout(row)
        split = QSplitter()
        self.model = QFileSystemModel()
        self.model.setFilter(QDir.Filter.AllDirs | QDir.Filter.Files | QDir.Filter.NoDotAndDotDot)
        self.model.setReadOnly(True)
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setRootIndex(self.model.setRootPath(self.root))
        self.tree.setAccessibleName("Workspace files")
        self.tree.clicked.connect(self._preview)
        for col in (1, 2, 3):
            self.tree.setColumnHidden(col, col != 3)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setAccessibleName("File preview")
        split.addWidget(self.tree)
        split.addWidget(self.preview)
        split.setSizes([320, 600])
        self.content.addWidget(split, 1)

    def _preview(self, index) -> None:
        path = self.model.filePath(index)
        real = os.path.realpath(path)
        if os.path.commonpath([real, os.path.realpath(self.root)]) != os.path.realpath(self.root):
            self.preview.setPlainText("This entry points outside the workspace; it is not shown.")
            return
        if os.path.isdir(path):
            self.preview.setPlainText("")
            return
        name = os.path.basename(path).lower()
        if name == ".env" or name.startswith(".env."):
            self.preview.setPlainText(".env files hold API keys and are not shown.")
            return
        if os.path.splitext(name)[1] not in TEXT_EXT:
            self.preview.setPlainText(f"No preview for this kind of file ({os.path.getsize(path):,} bytes).")
            return
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read(MAX_PREVIEW + 1)
        self.preview.setPlainText(text[:MAX_PREVIEW] + ("\n… (preview truncated)" if len(text) > MAX_PREVIEW else ""))
