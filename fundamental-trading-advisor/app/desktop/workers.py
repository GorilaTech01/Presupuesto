"""Qt worker thread wrapper (V1.2).

This module is Qt-only glue -- it never decides anything, and it never
re-implements any controller logic. `CallableWorker` just runs a plain
Python callable (always one of the `app.desktop.controllers` methods) on a
background `QThread` and relays either its return value or a short,
user-facing error string back to the UI thread via signals, so the main
window never blocks on a `WeeklyPipeline` run, a `monitor --all` refresh,
or an MT5 probe.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThread, Signal


class CallableWorker(QThread):
    """Runs `func(*args, **kwargs)` on a background thread.

    Connect to `finished_with_result` (receives the callable's return
    value) and `failed` (receives `str(exception)`, never a raw traceback)
    before calling `start()`. Named `finished_with_result` rather than
    `finished` to avoid colliding with `QThread`'s own no-argument
    `finished` signal, which still fires afterward either way.
    """

    finished_with_result = Signal(object)
    failed = Signal(str)

    def __init__(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self._func = func
        self._args = args
        self._kwargs = kwargs

    def run(self) -> None:
        try:
            result = self._func(*self._args, **self._kwargs)
        except Exception as exc:  # noqa: BLE001 -- relayed to the UI thread, never swallowed
            self.failed.emit(str(exc))
            return
        self.finished_with_result.emit(result)
