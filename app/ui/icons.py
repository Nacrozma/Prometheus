"""Line icons drawn for Prometheus (24×24, 1.75 stroke, round caps), rendered from SVG at any size and
tinted per state. Original drawings; no icon font or third-party set is bundled."""

from __future__ import annotations

from functools import lru_cache

from PyQt6.QtCore import QByteArray, QRectF, QSize, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

_PATHS = {
    # sun: Prometheus's mark
    "sun": '<circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M5.3 18.7l1.6-1.6M17.1 6.9l1.6-1.6"/>',
    "home": '<path d="M3.5 10.5 12 3.8l8.5 6.7"/><path d="M5.5 9v10.5h13V9"/><path d="M10 19.5v-5.2h4v5.2"/>',
    "chat": '<path d="M4 5.5h16v10.5H9.5L5.2 19.6V16H4z"/><path d="M8 9.5h8M8 12.5h5"/>',
    "memory": '<circle cx="6.5" cy="7" r="2.3"/><circle cx="17.5" cy="6.5" r="2.3"/><circle cx="12" cy="17" r="2.6"/><path d="M8.5 8.3 10.8 14.8M15.6 8.1 13.3 14.6M8.8 7 15.2 6.6"/>',
    "engineering": '<path d="M4 20 10.5 13.5"/><path d="M14.5 3.5a5 5 0 0 0-4.6 6.9L4 16.3V20h3.7l5.9-5.9a5 5 0 0 0 6.9-4.6l-3 1.7-2.5-1-1-2.5z"/>',
    "forge": '<path d="M4 9h11a4 4 0 0 1 4 4H8a4 4 0 0 1-4-4z"/><path d="M8 13v3.5M15 13v3.5M6 20h12M19 9.5V7"/>',
    "workspace": '<path d="M3.5 6.5h6l2 2h9v10h-17z"/><path d="M3.5 10.5h17"/>',
    "tasks": '<path d="M9.5 6.5h10M9.5 12h10M9.5 17.5h10"/><path d="M4 6.3l1.3 1.3L7.6 5.2M4 11.8l1.3 1.3 2.3-2.4M4.5 17.5h2.5"/>',
    "obsidian": '<path d="M12 2.8 19.5 8 17 19.5H7L4.5 8z"/><path d="M12 2.8 9.5 12.5 7 19.5M9.5 12.5l7.5 7"/>',
    "robot": '<path d="M5 20h8M9 20v-4"/><circle cx="9" cy="14.5" r="1.6"/><path d="M10.2 13.4 15 8.6"/><circle cx="15.8" cy="7.8" r="1.4"/><path d="M17 6.8l2.2-2.2M17.3 9.6l2.5.8"/>',
    "reflection": '<path d="M4 19.5h16"/><path d="M7 16v-4M11 16V8M15 16v-6M19 16V5"/>',
    "shield": '<path d="M12 3 19 6v5.5c0 4.3-3 7.6-7 9.5-4-1.9-7-5.2-7-9.5V6z"/><path d="m9 12 2.2 2.2L15.3 10"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M5.5 18.5l1.7-1.7M16.8 7.2l1.7-1.7"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6"/><path d="m15 15 5 5"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "send": '<path d="M4.5 12 19.5 4.5 15.5 19.5l-3.5-6z"/><path d="m12 13.5 7.5-9"/>',
    "stop": '<rect x="6.5" y="6.5" width="11" height="11" rx="2"/>',
    "mic": '<rect x="9" y="3.5" width="6" height="11" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v2.5"/>',
    "copy": '<rect x="8.5" y="8.5" width="11" height="11" rx="2"/><path d="M15.5 8.5V5.5a1 1 0 0 0-1-1h-9a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h3"/>',
    "retry": '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3"/><path d="M19.5 4.5v4.2h-4.2"/>',
    "trash": '<path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13"/>',
    "edit": '<path d="M4.5 19.5h4l10-10-4-4-10 10z"/><path d="m13 7.5 3.5 3.5"/>',
    "chevron-left": '<path d="m14.5 6-6 6 6 6"/>',
    "chevron-right": '<path d="m9.5 6 6 6-6 6"/>',
    "bell": '<path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 2h-15z"/><path d="M10 20.5h4"/>',
    "bolt": '<path d="M13 3 5.5 13.5H12L11 21l7.5-10.5H12z"/>',
    "check": '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    "alert": '<path d="M12 4 21 19.5H3z"/><path d="M12 10v4.5M12 17.2v.3"/>',
    "plug": '<path d="M9 3.5v4M15 3.5v4M6.5 7.5h11V11a5.5 5.5 0 0 1-11 0z"/><path d="M12 16.5v4"/>',
    "file": '<path d="M6 3.5h8l4 4v13H6z"/><path d="M14 3.5v4h4"/>',
    "clock": '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    "export": '<path d="M12 15V4M7.5 8.5 12 4l4.5 4.5"/><path d="M5 14v5.5h14V14"/>',
    "git": '<circle cx="6.5" cy="5.5" r="2"/><circle cx="6.5" cy="18.5" r="2"/><circle cx="17.5" cy="9" r="2"/><path d="M6.5 7.5v9M17.5 11c0 3-3 4-9 5.5"/>',
}


def svg(name: str, color: str) -> bytes:
    body = _PATHS.get(name, _PATHS["sun"])
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
        f'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    ).encode()


@lru_cache(maxsize=512)
def pixmap(name: str, color: str, size: int = 18, ratio: float = 2.0) -> QPixmap:
    px = QPixmap(int(size * ratio), int(size * ratio))
    px.fill(Qt.GlobalColor.transparent)
    r = QSvgRenderer(QByteArray(svg(name, color)))
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r.render(p, QRectF(0, 0, px.width(), px.height()))
    p.end()
    px.setDevicePixelRatio(ratio)
    return px


def icon(name: str, color: str, active: str = "", disabled: str = "") -> QIcon:
    """An icon with a normal colour and optional colours for the checked/active and disabled states."""
    ic = QIcon()
    ic.addPixmap(pixmap(name, color), QIcon.Mode.Normal, QIcon.State.Off)
    if active:
        ic.addPixmap(pixmap(name, active), QIcon.Mode.Normal, QIcon.State.On)
        ic.addPixmap(pixmap(name, active), QIcon.Mode.Active, QIcon.State.On)
    if disabled:
        ic.addPixmap(pixmap(name, disabled), QIcon.Mode.Disabled, QIcon.State.Off)
    return ic


def names() -> list:
    return sorted(_PATHS)


ICON_SIZE = QSize(18, 18)
