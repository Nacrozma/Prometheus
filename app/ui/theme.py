"""Prometheus's design system: Solar × Cosmic.

Deep cosmic darkness and graphite surfaces, with warm gold, solar amber, bronze and restrained
champagne highlights. Pages use the semantic tokens below (never raw hex values) so the whole window
stays consistent. Contrast: primary text on every surface is above 12:1, muted text above 6:1, the
gold accent above 9:1 on the background (WCAG AA for normal text throughout).

The older names (GOLD, AMBER, PANEL, ...) are kept as aliases so the HUD and existing code keep working.
"""

from __future__ import annotations

# ----- palette (raw values; use the semantic tokens in code) -----
DEEP_SPACE = "#08090E"
COSMIC_GRAPHITE = "#10131B"
ELEVATED = "#171A23"
RAISED = "#1E2230"
SOLAR_GOLD = "#F4B52C"
SOLAR_GOLD_HOVER = "#F8C557"
AMBER_ = "#FF8A24"
BRONZE = "#A86B2D"
CHAMPAGNE = "#F7D98B"
PRIMARY_TEXT = "#F4F3EF"
MUTED_TEXT = "#9297A6"
FAINT_TEXT = "#6B7080"

# ----- semantic tokens -----
BG = DEEP_SPACE  # window background
SURFACE = COSMIC_GRAPHITE  # sidebar, panels
SURFACE_ELEVATED = ELEVATED  # cards, inputs
SURFACE_RAISED = RAISED  # hover, selected rows
TEXT = PRIMARY_TEXT
TEXT_SECONDARY = MUTED_TEXT
TEXT_DIM = MUTED_TEXT
TEXT_FAINT = FAINT_TEXT
ACCENT = SOLAR_GOLD
ACCENT_HOVER = SOLAR_GOLD_HOVER
ACCENT_PRESSED = "#D99A1A"
ACCENT_SOFT = "rgba(244, 181, 44, 0.12)"  # selected backgrounds
ACCENT_FAINT = "rgba(244, 181, 44, 0.06)"
ON_ACCENT = "#1A1204"  # text on gold
HIGHLIGHT = CHAMPAGNE
SECONDARY_ACCENT = AMBER_
BORDER = "#242733"
BORDER_STRONG = "#343847"
BORDER_WARM = "#4A3A1E"
FOCUS = CHAMPAGNE
OK = "#5FD39A"
WARN = "#F6B44B"
ERR = "#FF6B5E"
INFO = "#7DB8FF"
SHADOW = "rgba(0, 0, 0, 0.55)"
SOLAR_GLOW = "rgba(255, 138, 36, 0.18)"

# ----- typography -----
FONT_UI = '"Segoe UI Variable Text", "Segoe UI", "Inter", "Noto Sans", sans-serif'
FONT_DISPLAY = '"Segoe UI Variable Display", "Segoe UI", "Inter Display", "Inter", sans-serif'
FONT_MONO = '"Cascadia Code", "JetBrains Mono", "Consolas", "DejaVu Sans Mono", monospace'
SIZE_BASE = 10  # pt
SIZE_SMALL = 9
SIZE_CAPTION = 8
SIZE_H1 = 18
SIZE_H2 = 12

# ----- spacing (px) and radii -----
SPACE_1, SPACE_2, SPACE_3, SPACE_4, SPACE_5, SPACE_6 = 4, 8, 12, 16, 24, 32
RADIUS_S, RADIUS_M, RADIUS_L = 6, 8, 12

# ----- legacy aliases (HUD, older pages and tests) -----
GOLD = ACCENT
AMBER = SECONDARY_ACCENT
GOLD_DIM = BRONZE
PANEL = SURFACE
PANEL_ALT = SURFACE_ELEVATED
LINE = BORDER
LINE_STRONG = BORDER_STRONG

#: Status tones used by pills, timelines and the status bar.
TONES = {"ok": OK, "warn": WARN, "err": ERR, "info": INFO, "accent": ACCENT, "neutral": TEXT_SECONDARY}

QSS = f"""
* {{ font-family: {FONT_UI}; font-size: {SIZE_BASE}pt; color: {TEXT}; }}
QMainWindow, QWidget#root, QDialog {{ background: {BG}; color: {TEXT}; }}
QWidget#workspace {{ background: {BG}; }}

/* ---- navigation ---- */
QWidget#sidebar {{ background: {SURFACE}; border-right: 1px solid {BORDER}; }}
QLabel#brand {{ color: {ACCENT}; font-family: {FONT_DISPLAY}; font-size: 13pt; font-weight: 600; letter-spacing: 4px; }}
QLabel#navGroup {{ color: {TEXT_FAINT}; font-size: {SIZE_CAPTION}pt; font-weight: 600; letter-spacing: 1.5px; padding: 10px 12px 4px 12px; }}
QToolButton#navItem {{ background: transparent; border: none; border-radius: {RADIUS_M}px; color: {TEXT_SECONDARY};
  padding: 7px 10px; text-align: left; font-size: {SIZE_BASE}pt; }}
QToolButton#navItem:hover {{ background: {SURFACE_ELEVATED}; color: {TEXT}; }}
QToolButton#navItem:checked {{ background: {ACCENT_SOFT}; color: {ACCENT}; font-weight: 600; }}
QToolButton#navItem:focus {{ border: 1px solid {FOCUS}; }}
QToolButton#collapse {{ background: transparent; border: none; border-radius: {RADIUS_S}px; color: {TEXT_FAINT}; padding: 6px; }}
QToolButton#collapse:hover {{ background: {SURFACE_ELEVATED}; color: {TEXT}; }}

/* ---- header ---- */
QWidget#topbar {{ background: {BG}; border-bottom: 1px solid {BORDER}; }}
QPushButton#searchField {{ background: {SURFACE_ELEVATED}; border: 1px solid {BORDER}; border-radius: {RADIUS_M}px;
  color: {TEXT_FAINT}; padding: 6px 12px; text-align: left; min-width: 260px; }}
QPushButton#searchField:hover {{ border-color: {BORDER_WARM}; color: {TEXT_SECONDARY}; }}

/* ---- text ---- */
QLabel#eyebrow {{ color: {ACCENT}; font-size: {SIZE_CAPTION}pt; font-weight: 600; letter-spacing: 2px; }}
QLabel#h1 {{ font-family: {FONT_DISPLAY}; font-size: {SIZE_H1}pt; font-weight: 600; color: {TEXT}; }}
QLabel#h2 {{ font-size: {SIZE_H2}pt; font-weight: 600; color: {TEXT}; }}
QLabel#sub {{ color: {TEXT_SECONDARY}; }}
QLabel#faint {{ color: {TEXT_FAINT}; font-size: {SIZE_SMALL}pt; }}
QLabel#mono {{ font-family: {FONT_MONO}; font-size: {SIZE_SMALL}pt; color: {TEXT_SECONDARY}; }}
QLabel#stat {{ font-family: {FONT_DISPLAY}; font-size: 20pt; font-weight: 600; color: {TEXT}; }}
QLabel#warn {{ color: {WARN}; }}
QLabel#err {{ color: {ERR}; }}
QLabel#ok {{ color: {OK}; }}
QLabel#accent {{ color: {ACCENT}; }}
QLabel#tagline {{ color: {TEXT_FAINT}; font-size: {SIZE_CAPTION}pt; }}

/* ---- surfaces ---- */
QFrame#card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: {RADIUS_L}px; }}
QFrame#cardInteractive {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: {RADIUS_L}px; }}
QFrame#cardInteractive:hover {{ border-color: {BORDER_WARM}; }}
QFrame#hero {{ border: 1px solid {BORDER_WARM}; border-radius: {RADIUS_L}px;
  background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1A1508, stop:0.45 {SURFACE}, stop:1 {BG}); }}
QFrame#approval {{ background: {SURFACE_ELEVATED}; border: 1px solid {BORDER_WARM}; border-top: 2px solid {HIGHLIGHT}; border-radius: {RADIUS_L}px; }}
QPushButton#decision {{ background: {SURFACE_RAISED}; border: 1px solid {BORDER_STRONG}; padding: 8px 18px; font-weight: 600; }}
QPushButton#decision:hover {{ border-color: {HIGHLIGHT}; }}
QPushButton#decision:focus {{ border: 2px solid {FOCUS}; }}
QFrame#bubbleUser {{ background: {SURFACE_ELEVATED}; border: 1px solid {BORDER}; border-radius: {RADIUS_L}px; }}
QFrame#divider {{ background: {BORDER}; max-height: 1px; min-height: 1px; border: none; }}
QLabel#pill {{ border-radius: 9px; padding: 2px 9px; font-size: {SIZE_CAPTION}pt; font-weight: 600; }}

/* ---- buttons ---- */
QPushButton {{ background: {SURFACE_ELEVATED}; border: 1px solid {BORDER_STRONG}; border-radius: {RADIUS_S}px; padding: 6px 14px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {SURFACE_RAISED}; }}
QPushButton:focus {{ border-color: {FOCUS}; }}
QPushButton:disabled {{ color: {TEXT_FAINT}; border-color: {BORDER}; }}
QPushButton#primary {{ background: {ACCENT}; color: {ON_ACCENT}; border: none; font-weight: 600; }}
QPushButton#primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#primary:pressed {{ background: {ACCENT_PRESSED}; }}
QPushButton#primary:focus {{ border: 2px solid {FOCUS}; }}
QPushButton#primary:disabled {{ background: {BRONZE}; color: #2A1E08; }}
QPushButton#ghost {{ background: transparent; border: 1px solid transparent; color: {TEXT_SECONDARY}; }}
QPushButton#ghost:hover {{ background: {SURFACE_ELEVATED}; color: {TEXT}; border-color: {BORDER}; }}
QPushButton#ghost:checked {{ background: {ACCENT_SOFT}; color: {ACCENT}; border-color: {BORDER_WARM}; font-weight: 600; }}
QPushButton:checked {{ background: {ACCENT_SOFT}; color: {ACCENT}; border-color: {ACCENT}; }}
QPushButton#chip {{ background: transparent; border: 1px solid {BORDER_STRONG}; border-radius: 13px; padding: 4px 12px; color: {TEXT_SECONDARY}; }}
QPushButton#chip:hover {{ border-color: {BORDER_WARM}; color: {HIGHLIGHT}; background: {ACCENT_FAINT}; }}
QPushButton#chip:checked {{ border-color: {ACCENT}; color: {ACCENT}; background: {ACCENT_SOFT}; }}
QFrame#plainCard {{ background: transparent; border: none; }}
QFrame#homeRow {{ background: {SURFACE}; border: 1px solid transparent; border-radius: {RADIUS_M}px; }}
QFrame#homeRow:hover {{ border-color: {BORDER_WARM}; }}
QFrame#rail {{ background: {SURFACE}; border-right: 1px solid {BORDER}; }}
QFrame#inspector {{ background: {SURFACE}; border-left: 1px solid {BORDER}; }}
QFrame#presence {{ background: transparent; border-bottom: 1px solid {BORDER}; }}
QFrame#viewport {{ background: #05060A; border: 1px solid {BORDER}; border-radius: {RADIUS_L}px; }}
QListWidget#rows {{ background: transparent; border: none; }}
QListWidget#rows::item {{ padding: 10px 12px; border-radius: {RADIUS_M}px; margin: 1px 0; border-bottom: 1px solid {BORDER}; }}
QListWidget#rows::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT}; border-bottom: 1px solid {BORDER_WARM}; }}
QListWidget#rail {{ background: transparent; border: none; }}
QListWidget#rail::item {{ padding: 8px 10px; border-radius: {RADIUS_S}px; color: {TEXT_SECONDARY}; }}
QListWidget#rail::item:selected {{ background: {ACCENT_SOFT}; color: {ACCENT}; }}
QPushButton#danger {{ border-color: {ERR}; color: {ERR}; background: transparent; }}
QPushButton#danger:hover {{ background: rgba(255, 107, 94, 0.10); }}
QPushButton#link {{ background: transparent; border: none; color: {ACCENT}; padding: 0; text-align: left; }}
QPushButton#link:hover {{ color: {ACCENT_HOVER}; text-decoration: underline; }}
QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: {RADIUS_S}px; padding: 4px; color: {TEXT_SECONDARY}; }}
QToolButton:hover {{ background: {SURFACE_ELEVATED}; border-color: {BORDER}; color: {TEXT}; }}
QToolButton:focus {{ border-color: {FOCUS}; }}

/* ---- inputs ---- */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
  background: {SURFACE_ELEVATED}; border: 1px solid {BORDER_STRONG}; border-radius: {RADIUS_S}px; padding: 6px 9px;
  selection-background-color: {BRONZE}; selection-color: {TEXT}; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {ACCENT}; }}
QPlainTextEdit#composer {{ background: transparent; border: none; padding: 4px 2px; }}
QFrame#composerBox {{ background: {SURFACE_ELEVATED}; border: 1px solid {BORDER_STRONG}; border-radius: {RADIUS_L}px; }}
QComboBox QAbstractItemView {{ background: {SURFACE_ELEVATED}; border: 1px solid {BORDER_STRONG}; selection-background-color: {ACCENT_SOFT}; selection-color: {ACCENT}; }}
QTextBrowser {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: {RADIUS_L}px; padding: 10px; }}
QTextBrowser#conversation {{ background: transparent; border: none; padding: 4px 8px; }}

/* ---- lists and tables ---- */
QTableWidget, QTreeView, QListWidget, QTableView {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: {RADIUS_M}px;
  gridline-color: {BORDER}; alternate-background-color: {SURFACE_ELEVATED}; selection-background-color: {ACCENT_SOFT}; selection-color: {TEXT}; }}
QListWidget::item, QTreeView::item {{ padding: 5px 6px; border-radius: {RADIUS_S}px; }}
QListWidget::item:hover, QTreeView::item:hover {{ background: {SURFACE_ELEVATED}; }}
QListWidget::item:selected, QTreeView::item:selected {{ background: {ACCENT_SOFT}; color: {ACCENT}; }}
QListWidget#plain {{ background: transparent; border: none; }}
QHeaderView::section {{ background: {SURFACE_ELEVATED}; color: {TEXT_SECONDARY}; border: none; border-bottom: 1px solid {BORDER}; padding: 6px; font-weight: 600; }}
QTableCornerButton::section {{ background: {SURFACE_ELEVATED}; border: none; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: {RADIUS_M}px; top: -1px; }}
QTabBar::tab {{ background: transparent; color: {TEXT_SECONDARY}; padding: 8px 16px; border-bottom: 2px solid transparent; }}
QTabBar::tab:hover {{ color: {TEXT}; }}
QTabBar::tab:selected {{ color: {ACCENT}; border-bottom: 2px solid {ACCENT}; }}

/* ---- misc ---- */
QStatusBar {{ background: {SURFACE}; border-top: 1px solid {BORDER}; color: {TEXT_SECONDARY}; font-size: {SIZE_SMALL}pt; }}
QStatusBar QLabel {{ padding: 0 10px; color: {TEXT_SECONDARY}; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {BORDER_STRONG}; border-radius: 4px; background: {SURFACE_ELEVATED}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QCheckBox::indicator:disabled {{ background: {SURFACE}; border-color: {BORDER}; }}
QCheckBox:focus {{ color: {HIGHLIGHT}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER_STRONG}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {BRONZE}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {BORDER_STRONG}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QToolTip {{ background: {SURFACE_RAISED}; color: {TEXT}; border: 1px solid {BORDER_STRONG}; padding: 5px 8px; border-radius: 4px; }}
QMenu {{ background: {SURFACE_ELEVATED}; border: 1px solid {BORDER_STRONG}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 4px; }}
QMenu::item:selected {{ background: {ACCENT_SOFT}; color: {ACCENT}; }}
QSplitter::handle {{ background: {BORDER}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QProgressBar {{ background: {SURFACE_ELEVATED}; border: none; border-radius: 3px; max-height: 6px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
"""


def pill_style(tone: str) -> str:
    """Background and text colour for a status pill of the given tone."""
    c = TONES.get(tone, TEXT_SECONDARY)
    r, g, b = int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
    # rgba(), not #RRGGBBAA: Qt reads 8-digit hex as #AARRGGBB
    return f"background: rgba({r}, {g}, {b}, 0.13); color: {c}; border: 1px solid rgba({r}, {g}, {b}, 0.33);"
