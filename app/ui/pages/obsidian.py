"""Obsidian: a knowledge reader for your vault.

Without a vault: an introduction to what connecting one does, and a single action to choose it.
With a vault: notes (search by name or text) on the left, the note rendered as Markdown in the centre,
and its connections on the right: the notes it links to and the notes that link to it, computed from the
vault's own [[links]]. Prometheus's memory mirror lives in <vault>/Prometheus/; exporting to it is an
approval-gated write done through the Companion. Nothing on this page writes to the vault.
"""

from __future__ import annotations

import datetime
import os

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSplitter, QStackedWidget, QTextBrowser, QVBoxLayout, QWidget

from .. import icons
from .. import theme as T
from ..feedback import notify
from ..widgets import Page, label, run_bg


class ObsidianPage(Page):
    title = "Obsidian"
    header = "none"
    margins = (0, 0, 0, 0)

    def __init__(self, core, companion, parent=None):
        super().__init__(core, parent)
        import gui_markdown as md

        self.md = md
        self.companion = companion
        self.all = []
        self.current = None
        self.stack = QStackedWidget()
        self.stack.addWidget(self._intro())
        self.stack.addWidget(self._reader())
        self.content.addWidget(self.stack, 1)

    # ----- no vault -----
    def _intro(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(60, 60, 60, 40)
        lay.setSpacing(12)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        ic = label()
        ic.setPixmap(icons.pixmap("obsidian", T.ACCENT, 40))
        lay.addWidget(ic)
        lay.addWidget(label("Connect your Obsidian vault", "h1"))
        body = label("Prometheus can read your notes here (search, read, follow links and backlinks) and mirror its memory into a Prometheus folder inside the vault, as linked notes you can browse in Obsidian. It writes only inside that folder, only when you approve an export, and keeps text you add below a note's generated section.", "sub")
        body.setMaximumWidth(640)
        lay.addWidget(body)
        lay.addWidget(label("Nothing is uploaded: the vault stays on this computer.", "faint"))
        pick = QPushButton(icons.icon("workspace", T.ON_ACCENT), " Choose your vault folder…")
        pick.setObjectName("primary")
        pick.clicked.connect(self._pick)
        pick.setMaximumWidth(280)
        lay.addWidget(pick)
        return w

    # ----- reader -----
    def _reader(self) -> QWidget:
        split = QSplitter()
        split.setHandleWidth(1)
        split.setChildrenCollapsible(False)
        left = QFrame()
        left.setObjectName("rail")
        left.setMinimumWidth(240)
        left.setMaximumWidth(340)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(14, 20, 10, 12)
        ll.setSpacing(8)
        ll.addWidget(label("Vault", "h1"))
        self.vault_lbl = label("", "faint", selectable=True)
        ll.addWidget(self.vault_lbl)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search notes by name or text…")
        self.search.setAccessibleName("Search notes")
        self.search.setClearButtonEnabled(True)
        self.search.returnPressed.connect(self._search)
        self.search.textChanged.connect(lambda t: self._search() if not t else None)
        ll.addWidget(self.search)
        self.list = QListWidget()
        self.list.setObjectName("rail")
        self.list.setIconSize(QSize(14, 14))
        self.list.setAccessibleName("Notes")
        self.list.itemClicked.connect(lambda it: self._open(it.data(Qt.ItemDataRole.UserRole)))
        ll.addWidget(self.list, 1)
        row = QHBoxLayout()
        change = QPushButton("Change vault…")
        change.setObjectName("ghost")
        change.clicked.connect(self._pick)
        row.addWidget(change)
        disc = QPushButton("Disconnect")
        disc.setObjectName("ghost")
        disc.clicked.connect(lambda: self._set(""))
        row.addWidget(disc)
        ll.addLayout(row)
        split.addWidget(left)

        mid = QWidget()
        ml = QVBoxLayout(mid)
        ml.setContentsMargins(30, 22, 30, 16)
        self.note_title = label("", "h1")
        ml.addWidget(self.note_title)
        self.note_meta = label("", "faint")
        ml.addWidget(self.note_meta)
        self.reader = QTextBrowser()
        self.reader.setObjectName("conversation")
        self.reader.setOpenLinks(False)
        self.reader.setAccessibleName("Note")
        self.reader.anchorClicked.connect(lambda url: None)
        ml.addWidget(self.reader, 1)
        split.addWidget(mid)

        right = QFrame()
        right.setObjectName("inspector")
        right.setMinimumWidth(240)
        right.setMaximumWidth(330)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(16, 22, 16, 16)
        rl.setSpacing(8)
        rl.addWidget(label("LINKS TO", "eyebrow"))
        self.out_links = QListWidget()
        self.out_links.setObjectName("rail")
        self.out_links.setAccessibleName("Links to")
        self.out_links.itemClicked.connect(self._follow)
        rl.addWidget(self.out_links, 1)
        rl.addWidget(label("LINKED FROM", "eyebrow"))
        self.back_links = QListWidget()
        self.back_links.setObjectName("rail")
        self.back_links.setAccessibleName("Linked from")
        self.back_links.itemClicked.connect(lambda it: self._open(it.data(Qt.ItemDataRole.UserRole)))
        rl.addWidget(self.back_links, 1)
        rl.addWidget(label("PROMETHEUS MIRROR", "eyebrow"))
        self.mirror = label("", "faint")
        rl.addWidget(self.mirror)
        export = QPushButton(icons.icon("export", T.TEXT_SECONDARY), " Export memory (asks first)")
        export.setToolTip("Sends the request to the Companion; the export is a write, so it shows an approval card")
        export.clicked.connect(self._export)
        rl.addWidget(export)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        split.setSizes([270, 720, 280])
        return split

    # ----- data -----
    def _vault(self) -> str:
        return self.companion.config.get("obsidian_vault", "") or os.environ.get("PROMETHEUS_OBSIDIAN_VAULT", "")

    def refresh(self) -> None:
        from ...services import vault_reader as V

        v = self._vault()
        if not v or not os.path.isdir(v):
            self.stack.setCurrentIndex(0)
            return
        self.stack.setCurrentIndex(1)
        marker = os.path.isdir(os.path.join(v, ".obsidian"))
        self.vault_lbl.setText(v + ("" if marker else "\n(no .obsidian folder: is this a vault?)"))
        inbox = os.path.join(v, "Prometheus", "Inbox")
        n = len([f for f in os.listdir(inbox) if f.endswith(".md")]) if os.path.isdir(inbox) else 0
        self.mirror.setText(("The Prometheus folder exists. " if os.path.isdir(os.path.join(v, "Prometheus")) else "Not exported yet. ") + (f"{n} note{'s' if n != 1 else ''} in Prometheus/Inbox wait to be read into memory." if n else ""))
        run_bg(lambda: V.notes(v), self._fill, lambda m: self.vault_lbl.setText("Could not read the vault: " + m.splitlines()[0]), owner=self)

    def _fill(self, all_notes) -> None:
        self.all = all_notes
        self._show_list(all_notes[:300])
        if all_notes and self.current is None:
            self._open(all_notes[0])
        elif not all_notes:
            self.note_title.setText("No notes yet")
            self.note_meta.setText("This vault has no Markdown notes Prometheus can read.")
            self.reader.setHtml("")

    def _show_list(self, items) -> None:
        self.list.clear()
        for n in items:
            it = QListWidgetItem(icons.icon("file", T.TEXT_FAINT), n["name"])
            it.setToolTip(n["rel"])
            it.setData(Qt.ItemDataRole.UserRole, n)
            self.list.addItem(it)
        if not items:
            it = QListWidgetItem("No matching notes.")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(it)

    def _search(self) -> None:
        from ...services import vault_reader as V

        q = self.search.text()
        v = self._vault()
        run_bg(lambda: V.search(v, q, self.all), self._show_list, owner=self)

    def _open(self, n) -> None:
        from ...services import vault_reader as V

        if not n:
            return
        v = self._vault()
        try:
            text = V.read(v, n["path"])
        except (OSError, ValueError) as e:
            notify(self, "Could not open the note", "err", str(e))
            return
        self.current = n
        self.note_title.setText(n["name"])
        self.note_meta.setText(f"{n['rel']} · changed {datetime.datetime.fromtimestamp(n['modified']):%d %b %Y %H:%M} · {len(text.split())} words")
        shown = V.WIKILINK.sub(lambda m: f"**{m.group(1).strip()}**", text)
        from .companion import MD_THEME

        self.reader.setHtml(self.md.render_markdown(shown, MD_THEME, {}, id_prefix="ob"))
        self.out_links.clear()
        names = {x["name"].lower(): x for x in self.all}
        for name in V.links(text):
            target = names.get(name.lower().split("/")[-1])
            it = QListWidgetItem(name + ("" if target else "   (no such note yet)"))
            it.setData(Qt.ItemDataRole.UserRole, target)
            if not target:
                it.setForeground(__import__("PyQt6.QtGui", fromlist=["QColor"]).QColor(T.TEXT_FAINT))
            self.out_links.addItem(it)
        if not self.out_links.count():
            it = QListWidgetItem("This note links to nothing.")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.out_links.addItem(it)
        self.back_links.clear()
        self.back_links.addItem("Looking for backlinks…")
        run_bg(lambda: V.backlinks(v, n["name"], self.all), self._show_back, owner=self)

    def _show_back(self, items) -> None:
        self.back_links.clear()
        for n in items:
            it = QListWidgetItem(n["name"])
            it.setData(Qt.ItemDataRole.UserRole, n)
            self.back_links.addItem(it)
        if not items:
            it = QListWidgetItem("No notes link here.")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.back_links.addItem(it)

    def _follow(self, item) -> None:
        n = item.data(Qt.ItemDataRole.UserRole)
        if n:
            self._open(n)

    def _export(self) -> None:
        self.window().go("Companion") if hasattr(self.window(), "go") else None
        self.companion.send("Export my memory to Obsidian now.")

    def _pick(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose your Obsidian vault")
        if d:
            self._set(d)

    def _set(self, path: str) -> None:
        cfg = self.companion.config
        cfg.set("obsidian_vault", path)
        cfg.save()
        self.core.p.set_obsidian_vault(path or None)
        self.current = None
        notify(self, "Vault connected" if path else "Vault disconnected", "ok", path)
        self.refresh()


def companion_cfg(companion):
    return companion.config
