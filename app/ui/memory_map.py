"""The memory map: people, projects, tools and topics Prometheus remembers, and how they connect.

Nodes are the graph's entities (size = how many memories mention them, colour = kind); lines are stored
relations or "mentioned together in a memory". Positions come from a deterministic force layout. Hover
shows a node's name and links; clicking a node shows its memories in the library. Keyboard: Tab focuses
the map, arrow keys move between nodes, Enter opens the selected one. Nothing is drawn that is not in
the stored graph.
"""

from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from . import theme as T

TYPE_COLOUR = {"person": "#F7D98B", "project": "#F4B52C", "tool": "#FF8A24", "topic": "#C9A46B", "concept": "#D8B880", "org": "#E8A15A", "place": "#9FC3A8", "event": "#B9A0E0", "skill": "#FFB35C", "other": "#9297A6"}


class MemoryMap(QWidget):
    picked = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.data = {"nodes": [], "edges": [], "pos": {}}
        self.hover: Optional[str] = None
        self.selected: Optional[str] = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(360)
        self.setAccessibleName("Memory map")

    def set_data(self, data: Dict) -> None:
        self.data = data
        self.selected = data["nodes"][0]["id"] if data.get("nodes") else None
        names = ", ".join(n["name"] for n in data.get("nodes", [])[:20])
        self.setAccessibleDescription(f"{len(data.get('nodes', []))} people, projects and topics, {len(data.get('edges', []))} links. {names}")
        self.update()

    # ----- geometry -----
    def _xy(self, nid: str) -> QPointF:
        x, y = self.data["pos"].get(nid, (0.0, 0.0))
        m = 60
        return QPointF(m + (x + 1) / 2 * (self.width() - 2 * m), m + (y + 1) / 2 * (self.height() - 2 * m))

    def _radius(self, n: Dict) -> float:
        return 6 + 4 * math.sqrt(max(0, n.get("facts", 0)))

    def _node_at(self, pt: QPointF) -> Optional[str]:
        for n in reversed(self.data["nodes"]):
            c = self._xy(n["id"])
            if math.hypot(pt.x() - c.x(), pt.y() - c.y()) <= self._radius(n) + 4:
                return n["id"]
        return None

    def _neighbours(self, nid: str) -> List[Dict]:
        return [e for e in self.data["edges"] if nid in (e["a"], e["b"])]

    # ----- painting -----
    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        nodes = {n["id"]: n for n in self.data["nodes"]}
        if not nodes:
            p.setPen(QColor(T.TEXT_SECONDARY))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "The map appears once memories mention people, projects, tools or topics.")
            p.end()
            return
        focus = self.hover or self.selected
        near = {focus} | {x for e in self._neighbours(focus) for x in (e["a"], e["b"])} if focus else set()
        for e in self.data["edges"]:
            a, b = self._xy(e["a"]), self._xy(e["b"])
            on = focus in (e["a"], e["b"])
            col = QColor(T.ACCENT if on else T.BORDER_STRONG)
            col.setAlphaF(0.85 if on else 0.6)
            p.setPen(QPen(col, 1.6 if on else 1.0, Qt.PenStyle.SolidLine if e["label"] != "mentioned together" else Qt.PenStyle.DashLine))
            p.drawLine(a, b)
            if on and e["label"] != "mentioned together":
                mid = (a + b) / 2
                p.setPen(QColor(T.HIGHLIGHT))
                p.drawText(QRectF(mid.x() - 80, mid.y() - 18, 160, 16), Qt.AlignmentFlag.AlignCenter, e["label"])
        f = QFont(self.font())
        f.setPointSizeF(9)
        p.setFont(f)
        for nid, n in nodes.items():
            c = self._xy(nid)
            r = self._radius(n)
            col = QColor(TYPE_COLOUR.get(n["type"], TYPE_COLOUR["other"]))
            dim = focus is not None and nid not in near
            col.setAlphaF(0.35 if dim else 0.95)
            p.setPen(QPen(QColor(T.FOCUS if nid == self.selected else T.BG), 2.0 if nid == self.selected else 1.0))
            p.setBrush(col)
            p.drawEllipse(c, r, r)
            tc = QColor(T.TEXT if not dim else T.TEXT_FAINT)
            p.setPen(tc)
            p.drawText(QRectF(c.x() - 90, c.y() + r + 2, 180, 16), Qt.AlignmentFlag.AlignHCenter, n["name"])
        # legend
        y = 10
        p.setPen(QColor(T.TEXT_FAINT))
        p.drawText(QRectF(12, y, 400, 16), Qt.AlignmentFlag.AlignLeft, "Size: memories that mention it · solid line: stored relation · dashed: mentioned together")
        p.end()

    # ----- interaction -----
    def mouseMoveEvent(self, e) -> None:
        h = self._node_at(e.position())
        if h != self.hover:
            self.hover = h
            self.setCursor(Qt.CursorShape.PointingHandCursor if h else Qt.CursorShape.ArrowCursor)
            if h:
                n = next(x for x in self.data["nodes"] if x["id"] == h)
                self.setToolTip(f"{n['name']} ({n['type']}) · {n['facts']} memories · {len(self._neighbours(h))} links")
            self.update()

    def leaveEvent(self, e) -> None:
        self.hover = None
        self.update()

    def mousePressEvent(self, e) -> None:
        h = self._node_at(e.position())
        if h:
            self.selected = h
            self.update()
            self.picked.emit(next(x["name"] for x in self.data["nodes"] if x["id"] == h))

    def keyPressEvent(self, e) -> None:
        nodes = self.data["nodes"]
        if not nodes:
            return super().keyPressEvent(e)
        ids = [n["id"] for n in nodes]
        i = ids.index(self.selected) if self.selected in ids else 0
        if e.key() in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            self.selected = ids[(i + 1) % len(ids)]
        elif e.key() in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self.selected = ids[(i - 1) % len(ids)]
        elif e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.picked.emit(nodes[i]["name"])
            return
        else:
            return super().keyPressEvent(e)
        n = next(x for x in nodes if x["id"] == self.selected)
        self.setAccessibleName(f"Memory map: {n['name']}, {n['facts']} memories")
        self.update()
