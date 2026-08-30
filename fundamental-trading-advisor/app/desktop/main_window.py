"""Main window (spec section 5): a sidebar (Dashboard / Daily Analysis /
Opportunities / Journal / Settings & System Status) driving a stacked
content area. This module wires views to controllers via
`app.desktop.workers.CallableWorker` so the UI thread never blocks on a
`WeeklyPipeline` run, a `monitor --all` refresh, or an MT5 probe -- it
never adds any decision, scoring, or execution logic of its own.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QSplitter,
    QStackedWidget,
)

from app.config.settings import Settings, get_settings
from app.desktop.controllers import (
    DailyAnalysisController,
    JournalActionController,
    JournalEntryNotLinked,
    MonitorController,
    OpportunityNotFound,
    SystemStatusController,
)
from app.desktop.dialogs import ask_entry_price, confirm_skip_trade, show_error, show_info
from app.desktop.theme import APP_STYLESHEET
from app.desktop.views.daily_analysis import DailyAnalysisView
from app.desktop.views.dashboard import DashboardView
from app.desktop.views.journal import JournalView
from app.desktop.views.opportunities import OpportunitiesView
from app.desktop.views.settings_status import SettingsStatusView
from app.desktop.workers import CallableWorker
from app.services.daily import DailyRunResult

PAGE_NAMES = ["Dashboard", "Daily Analysis", "Opportunities", "Journal", "Settings & System Status"]


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__()
        self.settings = settings or get_settings()
        self.daily_controller = DailyAnalysisController(self.settings)
        self.monitor_controller = MonitorController(self.settings)
        self.journal_controller = JournalActionController(self.settings)
        self.status_controller = SystemStatusController(self.settings)
        self._worker: CallableWorker | None = None

        self.setWindowTitle("Fundamental Trading Advisor")
        self.resize(1200, 800)
        self.setStyleSheet(APP_STYLESHEET)

        self._build_ui()
        self._refresh_status()

    # -- layout -----------------------------------------------------------

    def _build_ui(self) -> None:
        splitter = QSplitter()
        self.setCentralWidget(splitter)

        self.sidebar = QListWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(220)
        for name in PAGE_NAMES:
            QListWidgetItem(name, self.sidebar)
        self.sidebar.currentRowChanged.connect(self._on_page_changed)
        splitter.addWidget(self.sidebar)

        self.pages = QStackedWidget()
        self.dashboard_view = DashboardView()
        self.dashboard_view.run_daily_requested.connect(self._run_daily_analysis)
        self.dashboard_view.recheck_requested.connect(self._recheck_opportunities)
        self.dashboard_view.enter_trade_requested.connect(self._enter_trade)
        self.dashboard_view.skip_trade_requested.connect(self._skip_trade)
        self.pages.addWidget(self.dashboard_view)

        self.daily_analysis_view = DailyAnalysisView()
        self.pages.addWidget(self.daily_analysis_view)

        self.opportunities_view = OpportunitiesView()
        self.opportunities_view.refresh_requested.connect(self._refresh_opportunities)
        self.pages.addWidget(self.opportunities_view)

        self.journal_view = JournalView()
        self.journal_view.refresh_requested.connect(self._refresh_journal)
        self.pages.addWidget(self.journal_view)

        self.settings_status_view = SettingsStatusView()
        self.settings_status_view.refresh_requested.connect(self._refresh_status)
        self.pages.addWidget(self.settings_status_view)

        splitter.addWidget(self.pages)
        splitter.setSizes([220, 980])
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)

        self.sidebar.setCurrentRow(0)

    def _on_page_changed(self, row: int) -> None:
        self.pages.setCurrentIndex(row)
        if PAGE_NAMES[row] == "Opportunities":
            self._refresh_opportunities()
        elif PAGE_NAMES[row] == "Journal":
            self._refresh_journal()
        elif PAGE_NAMES[row] == "Settings & System Status":
            self._refresh_status()

    # -- background work helper --------------------------------------------

    def _run_in_background(
        self,
        func: Callable[[], Any],
        on_success: Callable[[Any], None],
        on_error: Callable[[str], None],
    ) -> None:
        worker = CallableWorker(func)
        worker.finished_with_result.connect(on_success)
        worker.failed.connect(on_error)
        # Keep a reference so the QThread object isn't garbage-collected mid-run.
        self._worker = worker
        worker.start()

    # -- Run Daily Analysis --------------------------------------------------

    def _run_daily_analysis(self) -> None:
        self.dashboard_view.set_busy(True, "Running analysis…")
        self._run_in_background(
            self.daily_controller.run,
            self._on_daily_analysis_finished,
            self._on_daily_analysis_failed,
        )

    def _on_daily_analysis_finished(self, result: DailyRunResult) -> None:
        self.dashboard_view.set_busy(False)
        self.dashboard_view.render_daily_result(result)
        self.daily_analysis_view.render_comparison(result.comparison)
        self._refresh_provider_status()

    def _on_daily_analysis_failed(self, message: str) -> None:
        self.dashboard_view.set_busy(False)
        show_error(
            self,
            "Daily Analysis Failed",
            f"The daily analysis could not complete:\n\n{message}",
        )

    # -- Re-check Opportunities ----------------------------------------------

    def _recheck_opportunities(self) -> None:
        self.dashboard_view.set_busy(True, "Re-checking opportunities…")
        self._run_in_background(
            self.monitor_controller.refresh_all,
            self._on_recheck_finished,
            self._on_recheck_failed,
        )

    def _on_recheck_finished(self, results: list[tuple[Any, bool]]) -> None:
        self.dashboard_view.set_busy(False)
        current = self.dashboard_view.current_opportunity
        if current is not None:
            match = next(
                (o for o, _ in results if o.opportunity_id == current.opportunity_id), None
            )
            if match is not None:
                self.dashboard_view.render_opportunity(match)
        ready = [o for o, _ in results if o.trade_action.value == "READY_TO_TRADE"]
        already_shown = current is not None and current.opportunity_id in {
            o.opportunity_id for o in ready
        }
        if ready and not already_shown:
            self.dashboard_view.render_opportunity(ready[0])
        show_info(
            self,
            "Re-check Complete",
            f"{len(results)} opportunit{'y' if len(results) == 1 else 'ies'} re-evaluated.",
        )

    def _on_recheck_failed(self, message: str) -> None:
        self.dashboard_view.set_busy(False)
        show_error(self, "Re-check Failed", f"Could not re-check opportunities:\n\n{message}")

    # -- Entered / Skip trade --------------------------------------------------

    def _enter_trade(self, opportunity_id: str) -> None:
        opportunity = self.monitor_controller.get_opportunity(opportunity_id)
        recommended = (
            opportunity.trade_plan.estimated_entry
            if opportunity is not None and opportunity.trade_plan is not None
            else None
        )
        asset = opportunity.asset if opportunity is not None else opportunity_id
        price = ask_entry_price(self, asset, recommended)
        if price is None:
            return
        try:
            entry = self.journal_controller.enter_trade(opportunity_id, price)
        except OpportunityNotFound:
            show_error(self, "No Active Opportunity", "That opportunity could not be found.")
            return
        except JournalEntryNotLinked:
            show_error(
                self,
                "No Linked Journal Entry",
                "This opportunity has no linked journal entry to record an entry against.",
            )
            return
        actual_entry = entry.entry_price_actual_or_simulated
        entry_text = f"{actual_entry:g}" if actual_entry is not None else "(unknown)"
        show_info(self, "Trade Recorded", f"Entry recorded at {entry_text}.")
        updated = self.monitor_controller.get_opportunity(opportunity_id)
        if updated is not None:
            self.dashboard_view.render_opportunity(updated)
        self._refresh_journal()

    def _skip_trade(self, opportunity_id: str) -> None:
        opportunity = self.monitor_controller.get_opportunity(opportunity_id)
        asset = opportunity.asset if opportunity is not None else opportunity_id
        if not confirm_skip_trade(self, asset):
            return
        try:
            self.journal_controller.skip_trade(opportunity_id)
        except OpportunityNotFound:
            show_error(self, "No Active Opportunity", "That opportunity could not be found.")
            return
        show_info(self, "Trade Skipped", f"{asset} has been marked CANCELLED.")
        updated = self.monitor_controller.get_opportunity(opportunity_id)
        if updated is not None:
            self.dashboard_view.render_opportunity(updated)
        self._refresh_journal()

    # -- Refresh UI Data (storage-only, no network) --------------------------

    def _refresh_opportunities(self) -> None:
        try:
            opportunities = self.monitor_controller.load_all_opportunities()
        except Exception as exc:  # noqa: BLE001 -- relayed as a friendly dialog, not a crash
            show_error(self, "Could Not Load Opportunities", str(exc))
            return
        self.opportunities_view.set_opportunities(opportunities)

    def _refresh_journal(self) -> None:
        try:
            entries = self.journal_controller.load_journal()
        except Exception as exc:  # noqa: BLE001
            show_error(self, "Could Not Load Journal", str(exc))
            return
        self.journal_view.set_entries(entries)

    def _refresh_status(self) -> None:
        try:
            status = self.status_controller.get_status()
        except Exception as exc:  # noqa: BLE001
            show_error(self, "Could Not Load System Status", str(exc))
            return
        self.settings_status_view.render_status(status)
        self.dashboard_view.set_provider_status(status.price_provider_mode, status.mt5_enabled)

    def _refresh_provider_status(self) -> None:
        try:
            status = self.status_controller.get_status()
        except Exception:  # noqa: BLE001 -- a status refresh failure must never block the dashboard
            return
        self.dashboard_view.set_provider_status(status.price_provider_mode, status.mt5_enabled)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(2000)
        super().closeEvent(event)
