"""Workspace: a file explorer for the one folder Prometheus may touch.

Left: the project you are in (or the whole workspace) and its files, with a name filter. Centre: the
selected file, highlighted (Markdown rendered) — or, with nothing selected, an overview of the workspace:
projects and what changed recently, so the screen is never a blank panel. Right: an inspector for the
selection: size, dates, Git state of its project, and what you can do with it (open, copy path, ask
Prometheus about it). The workspace is the backend's boundary; browsing never widens it.
"""

from __future__ import annotations

import datetime
import os

from PyQt6.QtCore import QDir, Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QFileSystemModel
from PyQt6.QtWidgets import QApplication, QComboBox, QFrame, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSplitter, QStackedWidget, QTextBrowser, QTreeView, QVBoxLayout, QWidget

from .. import icons
from .. import theme as T
from ..feedback import notify
from ..widgets import Page, label, run_bg

MAX_PREVIEW = 200_000
TEXT_EXT = {".txt", ".md", ".py", ".json", ".csv", ".toml", ".yaml", ".yml", ".ini", ".cfg", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".rs", ".c", ".h", ".cpp", ".hpp", ".java", ".go", ".log", ".xml", ".sql", ".sh", ".bat", ".ps1", ".ino", ".lua", ".rb", ".kt", ".swift"}
LANG = {".py": "python", ".js": "javascript", ".ts": "typescript", ".tsx": "typescript", ".jsx": "javascript", ".json": "json", ".rs": "rust", ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp", ".java": "java", ".go": "go", ".sh": "bash", ".sql": "sql", ".html": "html", ".css": "css", ".ino": "cpp"}
GIT_CODE = {"M": "modified", "A": "added", "D": "deleted", "R": "renamed", "C": "copied", "?": "new", "U": "conflict"}


def safe_preview(root: str, path: str) -> str:
    """Plain text of a workspace file for preview, or (prefixed with NUL) the reason it is not shown."""
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
    header = "none"
    margins = (0, 0, 0, 0)

    def __init__(self, core, parent=None):
        super().__init__(core, parent)
        import gui_markdown as md

        self.md = md
        self.root = core.paths()["workspace"]
        self.selected = ""
        split = QSplitter()
        split.setHandleWidth(1)
        split.setChildrenCollapsible(False)

        # left: project + tree
        left = QFrame()
        left.setObjectName("rail")
        left.setMinimumWidth(240)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(14, 20, 10, 12)
        ll.setSpacing(8)
        ll.addWidget(label("Workspace", "h1"))
        self.project = QComboBox()
        self.project.setAccessibleName("Project")
        self.project.currentIndexChanged.connect(self._project_changed)
        ll.addWidget(self.project)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter files by name…")
        self.filter.setAccessibleName("Filter files")
        self.filter.setClearButtonEnabled(True)
        ll.addWidget(self.filter)
        self.model = QFileSystemModel()
        self.model.setFilter(QDir.Filter.AllDirs | QDir.Filter.Files | QDir.Filter.NoDotAndDotDot)
        self.model.setReadOnly(True)
        self.model.setNameFilterDisables(False)
        self.model.setRootPath(self.root)
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setRootIndex(self.model.index(self.root))
        self.tree.setAccessibleName("Workspace files")
        self.tree.setHeaderHidden(True)
        for col in (1, 2, 3):
            self.tree.setColumnHidden(col, True)
        self.tree.clicked.connect(lambda ix: self.open_path(self.model.filePath(ix)))
        self.filter.textChanged.connect(lambda t: self.model.setNameFilters([f"*{t.strip()}*"] if t.strip() else []))
        ll.addWidget(self.tree, 1)
        boundary = label("Only this folder is reachable by Prometheus's file and shell tools. Change it in Settings → Workspace.", "faint")
        ll.addWidget(boundary)
        split.addWidget(left)

        # centre: overview or preview
        self.centre = QStackedWidget()
        ov = QWidget()
        ol = QVBoxLayout(ov)
        ol.setContentsMargins(30, 24, 30, 20)
        ol.setSpacing(10)
        ol.addWidget(label("OVERVIEW", "eyebrow"))
        self.ov_title = label("Your workspace", "h1")
        ol.addWidget(self.ov_title)
        self.ov_path = label(self.root, "mono", selectable=True)
        ol.addWidget(self.ov_path)
        ol.addWidget(label("PROJECTS", "eyebrow"))
        self.projects = QListWidget()
        self.projects.setObjectName("rows")
        self.projects.setAccessibleName("Projects")
        self.projects.setMaximumHeight(220)
        self.projects.itemClicked.connect(lambda it: self._select_project(it.data(Qt.ItemDataRole.UserRole)))
        ol.addWidget(self.projects)
        ol.addWidget(label("CHANGED IN THE LAST 7 DAYS", "eyebrow"))
        self.recent = QListWidget()
        self.recent.setObjectName("rows")
        self.recent.setAccessibleName("Recently changed files")
        self.recent.itemClicked.connect(lambda it: self.reveal(it.data(Qt.ItemDataRole.UserRole)))
        ol.addWidget(self.recent, 1)
        self.centre.addWidget(ov)
        pv = QWidget()
        pl = QVBoxLayout(pv)
        pl.setContentsMargins(24, 20, 24, 16)
        ph = QHBoxLayout()
        back = QPushButton(icons.icon("chevron-left", T.TEXT_SECONDARY), " Overview")
        back.setObjectName("ghost")
        back.clicked.connect(self._overview)
        ph.addWidget(back)
        self.preview_title = label("", "h2", wrap=False)
        ph.addWidget(self.preview_title, 1)
        pl.addLayout(ph)
        self.preview = QTextBrowser()
        self.preview.setAccessibleName("File preview")
        self.preview.setOpenLinks(False)
        pl.addWidget(self.preview, 1)
        self.centre.addWidget(pv)
        split.addWidget(self.centre)

        # right: inspector
        ins = QFrame()
        ins.setObjectName("inspector")
        ins.setMinimumWidth(260)
        ins.setMaximumWidth(360)
        il = QVBoxLayout(ins)
        il.setContentsMargins(18, 22, 18, 16)
        il.setSpacing(8)
        il.addWidget(label("INSPECTOR", "eyebrow"))
        self.i_name = label("Nothing selected", "h2")
        il.addWidget(self.i_name)
        self.i_meta = label("Choose a file on the left, or a project in the overview.", "faint", selectable=True)
        il.addWidget(self.i_meta)
        self.b_open = QPushButton(icons.icon("file", T.TEXT_SECONDARY), " Open with the system")
        self.b_copy = QPushButton(icons.icon("copy", T.TEXT_SECONDARY), " Copy path")
        self.b_ask = QPushButton(icons.icon("chat", T.TEXT_SECONDARY), " Ask Prometheus about it")
        self.b_folder = QPushButton(icons.icon("workspace", T.TEXT_SECONDARY), " Show in folder")
        for b, fn in ((self.b_open, self._open_system), (self.b_copy, self._copy_path), (self.b_ask, self._ask), (self.b_folder, self._show_folder)):
            b.clicked.connect(fn)
            il.addWidget(b)
        il.addWidget(label("PROJECT", "eyebrow"))
        self.git = QTextBrowser()
        self.git.setAccessibleName("Git state")
        il.addWidget(self.git, 1)
        split.addWidget(ins)
        split.setStretchFactor(1, 1)
        split.setSizes([280, 760, 300])
        self.content.addWidget(split, 1)
        self._actions_enabled(False)

    # ----- selection -----
    def _actions_enabled(self, on: bool) -> None:
        for b in (self.b_open, self.b_copy, self.b_ask, self.b_folder):
            b.setEnabled(on)

    def _overview(self) -> None:
        self.selected = ""
        self.tree.clearSelection()
        self.centre.setCurrentIndex(0)
        self.i_name.setText("Nothing selected")
        self.i_meta.setText("Choose a file on the left, or a project in the overview.")
        self._actions_enabled(False)

    def reveal(self, path: str) -> None:
        if not path:
            return
        ix = self.model.index(path)
        if ix.isValid():
            self.tree.setCurrentIndex(ix)
            self.tree.scrollTo(ix)
        self.open_path(path)

    def open_path(self, path: str) -> None:
        if os.path.isdir(path):
            self.tree.setExpanded(self.model.index(path), True)
            return
        self.selected = path
        text = safe_preview(self.root, path)
        rel = os.path.relpath(path, self.root)
        self.preview_title.setText(rel)
        self.centre.setCurrentIndex(1)
        try:
            st = os.stat(path)
            self.i_meta.setText(f"{rel}\n{st.st_size:,} bytes · changed {datetime.datetime.fromtimestamp(st.st_mtime):%d %b %Y %H:%M}\nType: {os.path.splitext(path)[1] or 'no extension'}")
        except OSError:
            self.i_meta.setText(rel)
        self.i_name.setText(os.path.basename(path))
        self._actions_enabled(not text.startswith("\x00This entry"))
        if text.startswith("\x00"):
            self.preview.setHtml(f'<p style="color:{T.TEXT_FAINT}; margin-top:40px; text-align:center;">{self.md.esc(text[1:])}</p>')
            return
        ext = os.path.splitext(path)[1].lower()
        if ext == ".md":
            self.preview.setHtml(self.md.render_markdown(text, None, {}, id_prefix="ws"))
            return
        body = self.md.highlight_code(text, LANG.get(ext, ""), {**self.md.DEFAULT_THEME, "text": T.TEXT, "kw": "#F2A65A", "str": "#C9D98B", "com": "#6B7080", "num": "#F7D98B", "fn": "#8CC4FF", "deco": "#F4B52C", "builtin": "#E8C9A0"})
        self.preview.setHtml(f'<pre style="font-family:Consolas,\'DejaVu Sans Mono\',monospace; font-size:9pt; white-space:pre-wrap; color:{T.TEXT};">{body}</pre>')

    def _open_system(self) -> None:
        if self.selected:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.selected))
            notify(self, "Opened with the system's default app", "info", os.path.basename(self.selected))

    def _copy_path(self) -> None:
        if self.selected:
            QApplication.clipboard().setText(self.selected)
            notify(self, "Path copied", "ok")

    def _show_folder(self) -> None:
        if self.selected:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(self.selected)))

    def _ask(self) -> None:
        win = self.window()
        if self.selected and hasattr(win, "companion"):
            rel = os.path.relpath(self.selected, self.root)
            win.go("Companion")
            win.companion.input.setText(f"Read {rel} and explain what it does. ")
            win.companion.input.setFocus()

    # ----- projects -----
    def _project_changed(self, _i: int) -> None:
        path = self.project.currentData() or self.root
        self.tree.setRootIndex(self.model.index(path))
        self._git(path)

    def _select_project(self, path: str) -> None:
        i = self.project.findData(path)
        if i >= 0:
            self.project.setCurrentIndex(i)

    def refresh(self) -> None:
        from ...services import workspace_info as W

        run_bg(lambda: (W.projects(self.root), W.recent_files(self.root)), self._fill, lambda m: self.ov_title.setText("Could not read the workspace"), owner=self)

    def _fill(self, data) -> None:
        projs, recent = data
        cur = self.project.currentData()
        self.project.blockSignals(True)
        self.project.clear()
        self.project.addItem(icons.icon("workspace", T.TEXT_SECONDARY), "Whole workspace", self.root)
        for p in projs:
            if p["path"] != self.root:
                self.project.addItem(icons.icon("git" if p["git"] else "workspace", T.ACCENT if p["git"] else T.TEXT_SECONDARY), p["name"], p["path"])
        self.project.setCurrentIndex(max(0, self.project.findData(cur)) if cur else 0)
        self.project.blockSignals(False)
        self._project_changed(0)
        self.projects.clear()
        for p in projs:
            it = QListWidgetItem(icons.icon("git" if p["git"] else "workspace", T.ACCENT if p["git"] else T.TEXT_SECONDARY), f"{p['name']}\n{'Git repository · ' if p['git'] else ''}changed {datetime.datetime.fromtimestamp(p['modified']):%d %b %H:%M}" if p["modified"] else p["name"])
            it.setData(Qt.ItemDataRole.UserRole, p["path"])
            self.projects.addItem(it)
        if not projs:
            it = QListWidgetItem("No project folders yet. Create one in this folder, or ask Prometheus to start a project for you.")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.projects.addItem(it)
        self.recent.clear()
        for f in recent:
            it = QListWidgetItem(icons.icon("file", T.TEXT_SECONDARY), f"{f['rel']}   ·   {datetime.datetime.fromtimestamp(f['modified']):%d %b %H:%M}")
            it.setData(Qt.ItemDataRole.UserRole, f["path"])
            self.recent.addItem(it)
        if not recent:
            it = QListWidgetItem("Nothing changed in the last 7 days.")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.recent.addItem(it)
        self.ov_title.setText(f"Your workspace · {len(projs)} project{'s' if len(projs) != 1 else ''}")

    def _git(self, path: str) -> None:
        from ...services import workspace_info as W

        run_bg(lambda: W.git_status(self.root, path), lambda st: self._show_git(path, st), owner=self)

    def _show_git(self, path: str, st) -> None:
        esc = self.md.esc
        name = os.path.basename(path) if path != self.root else "Whole workspace"
        if st.get("error"):
            self.git.setHtml(f"<b>{esc(name)}</b><p style='color:{T.WARN};'>{esc(st['error'])}</p>")
            return
        if not st.get("git"):
            self.git.setHtml(f"<b>{esc(name)}</b><p style='color:{T.TEXT_FAINT};'>Not a Git repository, so there is no change history to show.</p>")
            return
        ch = st.get("changes", [])
        rows = "".join(f"<tr><td style='color:{T.WARN if c['code'].strip() != '??' else T.INFO}; padding-right:8px;'>{GIT_CODE.get(c['code'].strip()[:1] or '?', c['code'])}</td><td>{esc(c['path'])}</td></tr>" for c in ch[:30])
        commits = "".join(f"<tr><td style='color:{T.ACCENT}; font-family:monospace; padding-right:8px;'>{esc(c['hash'])}</td><td>{esc(c['subject'])}</td></tr>" for c in st.get("commits", [])[:6])
        self.git.setHtml(f"<b>{esc(name)}</b> &nbsp;<span style='color:{T.ACCENT};'>⎇ {esc(st.get('branch', ''))}</span><p style='color:{T.TEXT_SECONDARY};'>{len(ch)} changed file{'s' if len(ch) != 1 else ''}{' — clean' if not ch else ''}</p><table>{rows}</table>" + (f"<p style='color:{T.TEXT_SECONDARY}; margin-top:8px;'>Recent commits</p><table>{commits}</table>" if commits else ""))
