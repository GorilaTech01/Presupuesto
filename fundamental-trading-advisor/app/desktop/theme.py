"""UI-only presentation constants (V1.2).

Colors/styling here are presentation choices, never domain logic:
`app.domain.enums.TradeAction`/`FundamentalBias` have no notion of color.
This is the ONLY place a state value is mapped to a color, purely so a
human can tell states apart at a glance -- nothing here feeds back into
any decision.
"""

from __future__ import annotations

STATUS_COLORS: dict[str, str] = {
    "WAIT": "#d29922",
    "READY_TO_TRADE": "#3fb950",
    "NO_TRADE": "#8b949e",
    "CANCELLED": "#f85149",
    "NO_CHANGE": "#8b949e",
}

BIAS_COLORS: dict[str, str] = {
    "BULLISH": "#3fb950",
    "BEARISH": "#f85149",
    "NEUTRAL": "#8b949e",
}


def status_color(value: str) -> str:
    return STATUS_COLORS.get(value, "#8b949e")


def bias_color(value: str) -> str:
    return BIAS_COLORS.get(value, "#8b949e")


APP_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #0d1117;
    color: #c9d1d9;
    font-family: "Segoe UI", "Helvetica Neue", sans-serif;
    font-size: 13px;
}
QPushButton {
    background-color: #21262d;
    border: 1px solid #30363d;
    border-radius: 4px;
    padding: 8px 16px;
}
QPushButton:hover { background-color: #30363d; }
QPushButton:disabled { color: #6e7681; border-color: #21262d; }
QPushButton#primaryButton {
    background-color: #238636;
    border: none;
    color: white;
    font-weight: 600;
}
QPushButton#primaryButton:hover { background-color: #2ea043; }
QPushButton#primaryButton:disabled { background-color: #1a4a24; color: #6e7681; }
QPushButton#dangerButton { background-color: #6e2020; border: none; color: #ffd7d5; }
QPushButton#dangerButton:hover { background-color: #8a2727; }
QListWidget#sidebar { background-color: #010409; border: none; outline: none; }
QListWidget#sidebar::item { padding: 12px 18px; border-left: 3px solid transparent; }
QListWidget#sidebar::item:selected {
    background-color: #161b22;
    border-left: 3px solid #1f6feb;
    color: white;
}
QTableView {
    background-color: #161b22;
    alternate-background-color: #1c2129;
    gridline-color: #30363d;
    border: 1px solid #30363d;
    selection-background-color: #1f6feb;
}
QHeaderView::section {
    background-color: #21262d;
    color: #c9d1d9;
    padding: 6px;
    border: none;
    border-bottom: 1px solid #30363d;
}
QTabWidget::pane { border: 1px solid #30363d; }
QTabBar::tab { background-color: #161b22; padding: 8px 16px; }
QTabBar::tab:selected { background-color: #21262d; border-bottom: 2px solid #1f6feb; }
QLabel#sectionTitle { font-size: 20px; font-weight: 700; }
QLabel#fieldLabel { color: #8b949e; font-size: 11px; text-transform: uppercase; }
QLabel#fieldValue { font-size: 15px; font-weight: 600; }
QLabel#disclaimer { color: #6e7681; font-size: 11px; }
QFrame#card { background-color: #161b22; border: 1px solid #30363d; border-radius: 6px; }
QFrame#warningBanner { background-color: #3d2c00; border: 1px solid #d29922; border-radius: 4px; }
"""
