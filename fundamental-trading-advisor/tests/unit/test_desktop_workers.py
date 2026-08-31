"""CallableWorker (V1.2): runs a plain callable off the UI thread and
relays either its result or a short error string back via signals -- it
must never crash the process or swallow an exception silently."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from app.desktop.workers import CallableWorker


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_worker_emits_finished_with_result_on_success(qtbot) -> None:
    _app()
    worker = CallableWorker(lambda a, b: a + b, 2, 3)
    with qtbot.waitSignal(worker.finished_with_result, timeout=2000) as blocker:
        worker.start()
    assert blocker.args == [5]


def test_worker_emits_failed_on_exception_never_raises(qtbot) -> None:
    _app()

    def _boom() -> None:
        raise ValueError("data source unavailable")

    worker = CallableWorker(_boom)
    with qtbot.waitSignal(worker.failed, timeout=2000) as blocker:
        worker.start()
    assert blocker.args == ["data source unavailable"]


def test_worker_passes_kwargs_through(qtbot) -> None:
    _app()
    worker = CallableWorker(lambda *, x: x * 2, x=21)
    with qtbot.waitSignal(worker.finished_with_result, timeout=2000) as blocker:
        worker.start()
    assert blocker.args == [42]
