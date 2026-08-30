"""Desktop app entry point (V1.2). `python -m app desktop` and
`scripts/run_desktop.py` both call `run()`."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app.desktop.main_window import MainWindow


def run() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()
