"""Obsidian: mirror the memory graph into a vault. Writes only inside <vault>/Prometheus/ and keeps
your own text in those notes; exporting is a confirmed tool call like any other write."""

from __future__ import annotations

import json
import os

from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QPlainTextEdit, QPushButton

from ..widgets import Card, Page, label


class ObsidianPage(Page):
    title = "Obsidian"
    subtitle = "Your memory graph as linked notes in an Obsidian vault."

    def __init__(self, core, companion, parent=None):
        super().__init__(core, parent)
        self.companion = companion
        cfg = Card("Vault")
        self.path = label("", "sub", selectable=True)
        cfg.body.addWidget(self.path)
        row = QHBoxLayout()
        pick = QPushButton("Choose vault folder…")
        pick.clicked.connect(self._pick)
        clear = QPushButton("Disconnect")
        clear.clicked.connect(lambda: self._set(""))
        row.addWidget(pick)
        row.addWidget(clear)
        row.addStretch(1)
        cfg.body.addLayout(row)
        cfg.body.addWidget(label("Prometheus writes only inside the vault's Prometheus folder. Text you add below a note's generated section is kept on every export.", "faint"))
        self.content.addWidget(cfg)
        ex = Card("Export")
        ex.body.addWidget(label("Exporting is a write, so the Companion asks you to approve it (export_obsidian).", "faint"))
        go = QPushButton("Export now (asks first)")
        go.setObjectName("primary")
        go.clicked.connect(lambda: companion.send("Export my memory to Obsidian now."))
        ex.body.addWidget(go)
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        ex.body.addWidget(self.report)
        self.content.addWidget(ex, 1)

    def _vault(self) -> str:
        return companion_cfg(self.companion).get("obsidian_vault", "") or os.environ.get("PROMETHEUS_OBSIDIAN_VAULT", "")

    def refresh(self) -> None:
        v = self._vault()
        if not v:
            self.path.setText("No vault connected.")
            return
        ok = os.path.isdir(os.path.join(v, ".obsidian"))
        self.path.setText(f"{v}" + ("" if ok else "   (no .obsidian folder found: is this a vault?)"))
        inbox = os.path.join(v, "Prometheus", "Inbox")
        n = len([f for f in os.listdir(inbox) if f.endswith(".md")]) if os.path.isdir(inbox) else 0
        self.report.setPlainText(json.dumps({"vault": v, "inbox_notes_waiting": n, "prometheus_folder_exists": os.path.isdir(os.path.join(v, "Prometheus"))}, indent=2))

    def _pick(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose your Obsidian vault")
        if d:
            self._set(d)

    def _set(self, path: str) -> None:
        cfg = companion_cfg(self.companion)
        cfg.set("obsidian_vault", path)
        cfg.save()
        self.core.p.set_obsidian_vault(path or None)
        self.refresh()


def companion_cfg(companion):
    return companion.config
