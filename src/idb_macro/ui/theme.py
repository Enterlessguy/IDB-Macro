"""Intelligence Database design tokens and the application stylesheet."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon

ASSETS = Path(__file__).resolve().parent.parent / "assets"

BG = "#050A19"
BG_DEEP = "#030612"
SIDEBAR = "#070D1B"
SURFACE = "#0E1425"
SURFACE_STRONG = "#121B31"
INPUT = "#080E1E"
INK = "#F8FAFF"
MUTED = "#AAB3CF"
FAINT = "#707C9D"
BORDER = "#273048"
BORDER_STRONG = "#3A5280"
SELECTION = "#17365E"
PRIMARY = "#4DA6FF"
PRIMARY_STRONG = "#1E67CE"
PRIMARY_HOVER = "#69B5FF"
PRIMARY_SOFT = "#183152"
SUCCESS = "#49D18B"
WARNING = "#F5B942"
DANGER = "#FF6577"

UI_FAMILIES = ["Segoe UI", "Inter", "Noto Sans", "Cantarell", "DejaVu Sans", "sans-serif"]
MONO_FAMILIES = ["Cascadia Mono", "Consolas", "JetBrains Mono", "DejaVu Sans Mono", "monospace"]

_welcome_family: str | None = None


def color(hex_value: str, alpha: int = 255) -> QColor:
    c = QColor(hex_value)
    c.setAlpha(alpha)
    return c


def ui_font(pixel_size: int = 13, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont()
    f.setFamilies(UI_FAMILIES)
    f.setPixelSize(pixel_size)
    f.setWeight(weight)
    return f


def welcome_family() -> str:
    """Family name of the bundled Intelligence Database script face."""
    global _welcome_family
    if _welcome_family is None:
        font_id = QFontDatabase.addApplicationFont(str(ASSETS / "welcome.ttf"))
        families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
        _welcome_family = families[0] if families else UI_FAMILIES[0]
    return _welcome_family


def app_icon() -> QIcon:
    return QIcon(str(ASSETS / "cube.png"))


def stylesheet() -> str:
    ui = ", ".join(f'"{f}"' if " " in f else f for f in UI_FAMILIES)
    mono = ", ".join(f'"{f}"' if " " in f else f for f in MONO_FAMILIES)
    chevron = (ASSETS / "chevron.svg").as_posix()
    return f"""
* {{ font-family: {ui}; font-size: 13px; color: {INK}; }}
QMainWindow, QDialog, #Content {{ background: {BG}; }}
QWidget#Sidebar {{ background: {SIDEBAR}; border-right: 1px solid {BORDER}; }}
QToolTip {{ background: {SURFACE_STRONG}; color: {INK}; border: 1px solid {BORDER_STRONG};
    padding: 6px 8px; border-radius: 6px; }}

QLabel {{ background: transparent; }}
QLabel[role="title"] {{ font-size: 26px; font-weight: 600; }}
QLabel[role="subtitle"] {{ color: {MUTED}; font-size: 13px; }}
QLabel[role="section"] {{ color: {FAINT}; font-size: 11px; font-weight: 600; letter-spacing: 1px; }}
QLabel[role="muted"] {{ color: {MUTED}; }}
QLabel[role="faint"] {{ color: {FAINT}; font-size: 12px; }}
QLabel[role="mono"] {{ font-family: {mono}; color: {MUTED}; }}
QLabel[role="warning"] {{ color: {WARNING}; }}
QLabel[role="error"] {{ color: {DANGER}; }}

QFrame#Card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 14px; }}
QFrame#Card QLabel#CardTitle {{ font-size: 15px; font-weight: 600; }}
QPushButton[chip="true"] {{ background: {PRIMARY_SOFT}; border: 1px solid {BORDER_STRONG}; border-radius: 15px;
    padding: 6px 14px; font-weight: 600; }}
QPushButton[preset="true"] {{ background: {INPUT}; border: 1px solid {BORDER_STRONG}; border-radius: 15px;
    padding: 6px 14px; font-weight: 600; }}
QPushButton[preset="true"]:hover {{ background: {PRIMARY_SOFT}; border-color: {PRIMARY}; }}
QFrame#Card[smart="true"] {{ border: 1px solid {PRIMARY_STRONG};
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #10203C, stop:1 {SURFACE}); }}
QPushButton[chip="true"]:hover {{ background: #3F1D2B; border-color: #8A3446; color: #FFD5DB; }}
QFrame#Inset {{ background: {INPUT}; border: 1px solid {BORDER}; border-radius: 10px; }}

QPushButton {{ background: {SURFACE_STRONG}; border: 1px solid {BORDER_STRONG}; border-radius: 9px;
    padding: 7px 14px; font-weight: 600; }}
QPushButton:hover {{ background: {PRIMARY_SOFT}; }}
QPushButton:pressed {{ background: {SELECTION}; }}
QPushButton:disabled {{ color: {FAINT}; border-color: {BORDER}; background: {SURFACE}; }}
QPushButton[variant="primary"] {{ border: 1px solid {PRIMARY_HOVER};
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #52ABFF, stop:1 #2369D3); }}
QPushButton[variant="primary"]:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #6FBEFF, stop:1 #2F7EE8); }}
QPushButton[variant="primary"]:pressed {{ background: {PRIMARY_STRONG}; }}
QPushButton[variant="primary"]:disabled {{ background: {SURFACE}; border-color: {BORDER}; color: {FAINT}; }}
QPushButton[variant="danger"] {{ border: 1px solid #8A3446; background: #3F1D2B; color: #FFD5DB; }}
QPushButton[variant="danger"]:hover {{ background: #56223A; }}
QPushButton[variant="ghost"] {{ background: transparent; border: 1px solid transparent; color: {MUTED}; }}
QPushButton[variant="ghost"]:hover {{ background: {SURFACE_STRONG}; color: {INK}; }}
QPushButton[variant="run"] {{ font-size: 15px; padding: 10px 22px; border-radius: 11px;
    border: 1px solid {PRIMARY_HOVER};
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #52ABFF, stop:1 #2369D3); }}
QPushButton[variant="run"]:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #6FBEFF, stop:1 #2F7EE8); }}
QPushButton[variant="run"][running="true"] {{ border: 1px solid #FF8A99;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #FF6D80, stop:1 #C8364D); }}

QPushButton[seg="true"] {{ background: transparent; border: none; border-radius: 7px; padding: 6px 12px;
    color: {MUTED}; font-weight: 600; }}
QPushButton[seg="true"]:hover {{ color: {INK}; background: {SURFACE_STRONG}; }}
QPushButton[seg="true"]:checked {{ color: {INK}; background: {SELECTION}; }}
QFrame#Segmented {{ background: {INPUT}; border: 1px solid {BORDER}; border-radius: 10px; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {{ background: {INPUT};
    border: 1px solid {BORDER}; border-radius: 8px; padding: 6px 9px; selection-background-color: {SELECTION}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{
    border: 1px solid {PRIMARY}; }}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{ color: {FAINT}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url("{chevron}"); width: 12px; height: 12px; }}
QPushButton::menu-indicator {{ image: none; width: 0; }}
QComboBox QAbstractItemView {{ background: {SURFACE_STRONG}; border: 1px solid {BORDER_STRONG};
    selection-background-color: {SELECTION}; outline: none; padding: 4px; }}

QListWidget {{ background: {INPUT}; border: 1px solid {BORDER}; border-radius: 10px; padding: 4px; outline: none; }}
QListWidget::item {{ padding: 8px 10px; border-radius: 7px; color: {MUTED}; }}
QListWidget::item:hover {{ background: {SURFACE_STRONG}; color: {INK}; }}
QListWidget::item:selected {{ background: {PRIMARY_SOFT}; color: {INK}; }}

QMenu {{ background: {SURFACE_STRONG}; border: 1px solid {BORDER_STRONG}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 7px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {SELECTION}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 5px 8px; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER_STRONG}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {FAINT}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {BORDER_STRONG}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QMessageBox {{ background: {SURFACE}; }}
QCheckBox {{ spacing: 8px; }}
"""


def apply_dark_title_bar(widget) -> None:
    """Ask Windows 10/11 for a dark, rounded native frame."""
    if sys.platform != "win32":
        return
    import ctypes

    try:
        hwnd = int(widget.winId())
        dwm = ctypes.WinDLL("dwmapi")
        on = ctypes.c_int(1)
        if dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), 4) != 0:
            dwm.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(on), 4)
        rounded = ctypes.c_int(2)
        dwm.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(rounded), 4)
        caption = ctypes.c_int(0x001B0D07)  # SIDEBAR #070D1B as a BGR COLORREF
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(caption), 4)
    except (OSError, AttributeError):
        pass
