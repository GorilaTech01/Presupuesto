"""Convenience launcher for the desktop control panel.

Equivalent to `python -m app desktop` -- this script exists only so the
app can also be double-clicked/launched without remembering the module
path (see `run_desktop.bat` for the Windows one-click version).
"""

from __future__ import annotations

import sys

from app.desktop.app import run

if __name__ == "__main__":
    sys.exit(run())
