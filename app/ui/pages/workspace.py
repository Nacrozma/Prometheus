"""Workspace: the one folder the workspace tools may use. Projects, files (with search), a safe
highlighted preview, each project's Git state (read-only) and what changed recently.
The folder is the backend's boundary (WORKSPACE_DIR); browsing here never widens it."""

from __future__ import annotations

import datetime
import os

from PyQt6.QtCore import QDir, QSortFilterProxyModel, Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QFileSystemModel
from PyQt6.QtWidgets import QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSplitter, QTabWidget, QTextBrowser, QTreeView, QVBoxLayout, QWidget

from .. import icons
from .. import theme as T
from ..widgets import Page, label, run_bg

MAX_PREVIEW = 200_000
TEXT_EXT = {".txt", ".md", ".py", ".json", ".csv", ".toml", ".yaml", ".yml", ".ini", ".cfg", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".rs", ".c", ".h", ".cpp", ".hpp", ".java", ".go", ".log", ".xml", ".sql", ".sh", ".bat", ".ps1", ".ino", ".lua", ".rb", ".kt", ".swift"}
LANG = {".py": "python", ".js": "javascript", ".ts": "typescript", ".tsx": "typescript", ".jsx": "javascript", ".json": "json", ".rs": "rust", ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp", ".java": "java", ".go": "go", ".sh": "bash", ".sql": "sql", ".html": "html", ".css": "css", ".ino": "cpp"}
GIT_CODE = {"M": "modified", "A": "added", "D": "deleted", "R": "renamed", "C": "copied", "?": "new", "U": "conflict"}


def safe_preview(root: str, path: str) -> str:
    """Plain text of a workspace file for preview, or the reason it is not shown."""
    real = os.path.realpath(path)
    rroot = os.path.realpath(root)
    if os.path.commonpath([real, rroot]) != rroot:
        return "\x00This entry points outside the workspace; it is not shown."
    if os.path.isdir(path):
        return "\x00"
    name = os.path.basename(path).lower()
    if name == ".env" or name.startswith(".env."):
        return "\x00.env files hold API keys and are not shown."
    if os.path.splitext(name)[1] not in TEXT_EXT:
        return f"\x00No preview for this kind of file ({os.path.getsize(path):,} bytes)."
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read(MAX_PREVIEW + 1)
    return text[:MAX_PREVIEW] + ("\n… (preview truncated)" if len(text) > MAX_PREVIEW else "")


class WorkspacePage(Page):
    title = "Workspace"
    subtitle = "The folder Prometheus may read and change with its file and shell tools. Everything outside it is refused by the core."

    def __init__(self, core, parent=None):
        super().__init__(core, parent)
        import gui_markdown as md

        self.md = md
        self.root = core.paths()["workspace"]
        open_btn = QPushButton(icons.icon("workspace", T.TEXT_SECONDARY), " Open folder")
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.root)))
        self.actions.addWidget(open_btn)
        self.where = label(f"{self.root}  ·  change it in Settings → Workspace (applies after a restart). Prometheus's own state files and .env files stay off-limits to the tools even inside it.", "faint", selectable=True)
        self.content.addWidget(self.where)

        split = QSplitter()
        split.setHandleWidth(1)
        # left: projects and files
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 8, 0)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter files by name…")
        self.filter.setAccessibleName("Filter files")
        self.filter.setClearButtonEnabled(True)
        ll.addWidget(self.filter)
        self.model = QFileSystemModel()
        self.model.setFilter(QDir.Filter.AllDirs | QDir.Filter.Files | QDir.Filter.NoDotAndDotDot)
        self.model.setReadOnly(True)
        self.model.setNameFilterDisables(False)
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setRootIndex(self.model.setRootPath(self.root))
        self.tree.setAccessibleName("Workspace files")
        self.tree.clicked.connect(lambda ix: self.open_path(self.model.filePath(ix)))
        for col in (1, 2, 3):
            self.tree.setColumnHidden(col, True)
        self.tree.setHeaderHidden(True)
        self.filter.textChanged.connect(self._filter)
        ll.addWidget(self.tree, 1)
        split.addWidget(left)

        # middle: preview
        mid = QWidget()
        ml = QVBoxLayout(mid)
        ml.setContentsMargins(8, 0, 8, 0)
        self.preview_title = label("Select a file", "h2", wrap=False)
        ml.addWidget(self.preview_title)
        self.preview = QTextBrowser()
        self.preview.setAccessibleName("File preview")
        self.preview.setOpenLinks(False)
        ml.addWidget(self.preview, 1)
        split.addWidget(mid)

        # right: projects, git, recent
        right = QTabWidget()
        self.projects = QListWidget()
        self.projects.setObjectName("plain")
        self.projects.setAccessibleName("Projects")
        self.projects.itemClicked.connect(lambda it: self._project(it.data(Qt.ItemDataRole.UserRole)))
        pw = QWidget()
        pl = QVBoxLayout(pw)
        pl.addWidget(self.projects, 1)
        self.git = QTextBrowser()
        self.git.setAccessibleName("Git status")
        pl.addWidget(self.git, 2)
        right.addTab(pw, "Projects")
        self.recent = QListWidget()
        self.recent.setObjectName("plain")
        self.recent.setAccessibleName("Recently changed files")
        self.recent.itemClicked.connect(lambda it: self.reveal(it.data(Qt.ItemDataRole.UserRole)))
        right.addTab(self.recent, "Recent changes")
        split.addWidget(right)
        split.setSizes([300, 560, 340])
        self.content.addWidget(split, 1)
        self._project_path = ""

    # ----- files -----
    def _filter(self, text: str) -> None:
        t = text.strip()
        self.model.setNameFilters([f"*{t}*"] if t else [])

    def reveal(self, path: str) -> None:
        if not path:
            return
        ix = self.model.index(path)
        if ix.isValid():
            self.tree.setCurrentIndex(ix)
            self.tree.scrollTo(ix)
        self.open_path(path)

    def open_path(self, path: str) -> None:
        text = safe_preview(self.root, path)
        self.preview_title.setText(os.path.relpath(path, self.root) if path else "")
        if text.startswith("\x00"):
            self.preview.setHtml(f'<p style="color:{T.TEXT_FAINT};">{self.md.esc(text[1:])}</p>')
            return
        ext = os.path.splitext(path)[1].lower()
        if ext == ".md":
            self.preview.setHtml(self.md.render_markdown(text, None, {}, id_prefix="ws"))
            return
        body = self.md.highlight_code(text, LANG.get(ext, ""), {**self.md.DEFAULT_THEME, "text": T.TEXT, "kw": "#F2A65A", "str": "#C9D98B", "com": "#6B7080", "num": "#F7D98B", "fn": "#8CC4FF", "deco": "#F4B52C", "builtin": "#E8C9A0"})
        self.preview.setHtml(f'<pre style="font-family:Consolas,\'DejaVu Sans Mono\',monospace; font-size:9pt; white-space:pre-wrap; color:{T.TEXT};">{body}</pre>')

    # ----- projects -----
    def refresh(self) -> None:
        from ...services import workspace_info as W

        run_bg(lambda: (W.projects(self.root), W.recent_files(self.root)), self._fill, lambda m: self.git.setPlainText("Could not read the workspace: " + m.splitlines()[0]), owner=self)

    def _fill(self, data) -> None:
        projs, recent = data
        self.projects.clear()
        for p in projs:
            it = QListWidgetItem(icons.icon("git" if p["git"] else "workspace", T.ACCENT if p["git"] else T.TEXT_SECONDARY), f"{p['name']}   ·   {datetime.datetime.fromtimestamp(p['modified']):%d %b %H:%M}" if p["modified"] else p["name"])
            it.setData(Qt.ItemDataRole.UserRole, p["path"])
            self.projects.addItem(it)
        if not projs:
            self.git.setHtml(f'<p style="color:{T.TEXT_FAINT};">No project folders yet. Put a project in the workspace, or ask Prometheus to create one.</p>')
        elif not self._project_path:
            self._project(projs[0]["path"])
        self.recent.clear()
        for f in recent:
            it = QListWidgetItem(icons.icon("file", T.TEXT_SECONDARY), f"{f['rel']}   ·   {datetime.datetime.fromtimestamp(f['modified']):%d %b %H:%M}")
            it.setData(Qt.ItemDataRole.UserRole, f["path"])
            self.recent.addItem(it)
        if not recent:
            self.recent.addItem("Nothing changed in the last 7 days.")

    def _project(self, path: str) -> None:
        from ...services import workspace_info as W

        self._project_path = path
        run_bg(lambda: W.git_status(self.root, path), lambda st: self._show_git(path, st), owner=self)

    def _show_git(self, path: str, st) -> None:
        esc = self.md.esc
        name = os.path.basename(path)
        if st.get("error"):
            self.git.setHtml(f"<b>{esc(name)}</b><p style='color:{T.WARN};'>{esc(st['error'])}</p>")
            return
        if not st.get("git"):
            self.git.setHtml(f"<b>{esc(name)}</b><p style='color:{T.TEXT_FAINT};'>Not a Git repository.</p>")
            return
        ch = st.get("changes", [])
        rows = "".join(f"<tr><td style='color:{T.WARN if c['code'].strip() != '??' else T.INFO}; padding-right:8px;'>{GIT_CODE.get(c['code'].strip()[:1] or '?', c['code'])}</td><td>{esc(c['path'])}</td></tr>" for c in ch[:40])
        commits = "".join(f"<tr><td style='color:{T.ACCENT}; font-family:monospace; padding-right:8px;'>{esc(c['hash'])}</td><td>{esc(c['subject'])}</td><td style='color:{T.TEXT_FAINT}; padding-left:8px;'>{esc(c['when'])}</td></tr>" for c in st.get("commits", []))
        self.git.setHtml(
            f"<b>{esc(name)}</b> &nbsp;<span style='color:{T.TEXT_FAINT};'>branch</span> <span style='color:{T.ACCENT};'>{esc(st.get('branch', ''))}</span>"
            f"<p style='color:{T.TEXT_SECONDARY};'>{len(ch)} changed files" + (" (clean)" if not ch else "") + "</p>"
            f"<table>{rows}</table>" + (f"<p style='color:{T.TEXT_SECONDARY}; margin-top:10px;'>Recent commits</p><table>{commits}</table>" if commits else "")
        )
