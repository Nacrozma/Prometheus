"""Prometheus's look: deep charcoal and midnight, warm gold and amber, restrained glow.
Colours match the HUD's palette in gui_orb.py so the orb sits naturally in the window."""

GOLD = "#FFB300"
AMBER = "#FF8C00"
GOLD_DIM = "#8A6200"
BG = "#07070B"
PANEL = "#0E0E15"
PANEL_ALT = "#14141D"
LINE = "#2A2418"
LINE_STRONG = "#4A3A18"
TEXT = "#ECEAF2"
TEXT_DIM = "#9A98AA"
TEXT_FAINT = "#6E6C80"
OK = "#5BD69A"
WARN = "#FFB347"
ERR = "#FF5C5C"
INFO = "#62C7FF"

QSS = f"""
* {{ font-family: "Segoe UI", "Inter", "Noto Sans", sans-serif; font-size: 10pt; color: {TEXT}; }}
QMainWindow, QWidget#root, QDialog {{ background: {BG}; color: {TEXT}; }}
QWidget#sidebar {{ background: {PANEL}; border-right: 1px solid {LINE}; }}
QListWidget#nav {{ background: transparent; border: none; outline: none; }}
QListWidget#nav::item {{ padding: 9px 14px; margin: 1px 8px; border-radius: 6px; color: {TEXT_DIM}; }}
QListWidget#nav::item:hover {{ background: {PANEL_ALT}; color: {TEXT}; }}
QListWidget#nav::item:selected {{ background: rgba(255, 179, 0, 0.12); color: {GOLD}; border-left: 3px solid {GOLD}; }}
QLabel#brand {{ color: {GOLD}; font-size: 13pt; font-weight: 600; letter-spacing: 3px; padding: 18px 16px 4px 16px; }}
QLabel#tagline {{ color: {TEXT_FAINT}; font-size: 8pt; padding: 0 16px 14px 16px; }}
QLabel#h1 {{ font-size: 16pt; font-weight: 600; color: {TEXT}; }}
QLabel#sub {{ color: {TEXT_DIM}; }}
QLabel#faint {{ color: {TEXT_FAINT}; font-size: 9pt; }}
QLabel#warn {{ color: {WARN}; }}
QLabel#err {{ color: {ERR}; }}
QLabel#ok {{ color: {OK}; }}
QFrame#card {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 10px; }}
QFrame#approval {{ background: #1C1408; border: 1px solid {AMBER}; border-radius: 10px; }}
QPushButton {{ background: {PANEL_ALT}; border: 1px solid {LINE_STRONG}; border-radius: 6px; padding: 6px 14px; }}
QPushButton:hover {{ border-color: {GOLD}; }}
QPushButton:disabled {{ color: {TEXT_FAINT}; border-color: {LINE}; }}
QPushButton#primary {{ background: {GOLD}; color: #1A1200; border: none; font-weight: 600; }}
QPushButton#primary:hover {{ background: #FFC533; }}
QPushButton#primary:disabled {{ background: {GOLD_DIM}; color: #2A2000; }}
QPushButton#danger {{ border-color: {ERR}; color: {ERR}; }}
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
  background: {PANEL_ALT}; border: 1px solid {LINE_STRONG}; border-radius: 6px; padding: 5px 8px; selection-background-color: {GOLD_DIM}; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus {{ border-color: {GOLD}; }}
QTextBrowser {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 10px; padding: 8px; }}
QTableWidget, QTreeView, QListWidget {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 8px; gridline-color: {LINE}; alternate-background-color: {PANEL_ALT}; }}
QHeaderView::section {{ background: {PANEL_ALT}; color: {TEXT_DIM}; border: none; border-bottom: 1px solid {LINE}; padding: 5px; }}
QTabWidget::pane {{ border: 1px solid {LINE}; border-radius: 8px; top: -1px; }}
QTabBar::tab {{ background: transparent; color: {TEXT_DIM}; padding: 7px 14px; }}
QTabBar::tab:selected {{ color: {GOLD}; border-bottom: 2px solid {GOLD}; }}
QStatusBar {{ background: {PANEL}; border-top: 1px solid {LINE}; color: {TEXT_DIM}; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {LINE_STRONG}; border-radius: 4px; background: {PANEL_ALT}; }}
QCheckBox::indicator:checked {{ background: {GOLD}; border-color: {GOLD}; }}
QCheckBox::indicator:disabled {{ background: {PANEL}; border-color: {LINE}; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QTableCornerButton::section {{ background: {PANEL_ALT}; border: none; }}
QStatusBar QLabel {{ padding: 0 10px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {LINE_STRONG}; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QToolTip {{ background: {PANEL_ALT}; color: {TEXT}; border: 1px solid {LINE_STRONG}; }}
"""
