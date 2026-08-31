"""Desktop UI controllers/adapters (V1.2).

Every method here is a thin wrapper around an existing service --
`app.services.daily.run_daily_analysis`, `app.monitor.service.
TradeOpportunityMonitorService`, `app.journal.actions`, `app.journal.
journal.RecommendationJournal`, `app.market.price_router.build_price_
provider`. NONE of these controllers re-implements scoring, decision, or
state-machine logic; each one calls the exact same function the CLI calls
and returns the exact same typed domain objects (`WeeklyComparison`,
`MonitoredTradeOpportunity`, `JournalEntry`, ...) untouched. The desktop UI
is provably a presentation layer over these, not a second decision engine
-- see `tests/unit/test_desktop_controllers.py` and
`tests/unit/test_no_order_execution_path.py` (extended to also cover
`app/desktop/`).

These classes have no Qt dependency at all, so they're fully unit-testable
without a QApplication; `app.desktop.workers` is the only place a Qt
signal/thread wraps a call into one of these.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config.settings import Settings, get_settings
from app.domain.models import MonitoredTradeOpportunity
from app.journal.actions import (
    JournalEntryNotLinked,
    OpportunityNotFound,
    record_manual_entry,
    record_skip,
)
from app.journal.journal import RecommendationJournal
from app.journal.models import JournalEntry
from app.market.mt5_provider import MT5ReadOnlyPriceProvider
from app.market.price_router import build_price_provider
from app.monitor.service import TradeOpportunityMonitorService
from app.monitor.store import OpportunityStore
from app.services.daily import DailyRunResult, run_daily_analysis

__all__ = [
    "DailyAnalysisController",
    "MonitorController",
    "JournalActionController",
    "SystemStatusController",
    "DataSourceStatus",
    "SystemStatus",
    "OpportunityNotFound",
    "JournalEntryNotLinked",
]

DEFAULT_CANDIDATES = ["EURUSD", "XAUUSD", "BTCUSD"]


class DailyAnalysisController:
    """Runs exactly the same flow as `python -m app daily`."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def run(self, candidates: list[str] | None = None) -> DailyRunResult:
        return run_daily_analysis(self.settings, candidates or DEFAULT_CANDIDATES)


class MonitorController:
    """Runs exactly the same flow as `python -m app monitor --all`, and
    provides read-only access to the persisted opportunity store for the
    Opportunities screen (never mutates anything the analysis engine
    itself didn't already decide)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def refresh_all(self) -> list[tuple[MonitoredTradeOpportunity, bool]]:
        service = TradeOpportunityMonitorService(self.settings)
        try:
            return service.refresh_all()
        finally:
            service.close()

    def load_all_opportunities(self) -> list[MonitoredTradeOpportunity]:
        store = OpportunityStore(self.settings.data_dir / "monitor" / "opportunities.jsonl")
        return store.load_all()

    def get_opportunity(self, opportunity_id: str) -> MonitoredTradeOpportunity | None:
        store = OpportunityStore(self.settings.data_dir / "monitor" / "opportunities.jsonl")
        return store.get(opportunity_id)


class JournalActionController:
    """Wraps the exact same `journal enter` / `journal skip` / journal
    listing service calls the CLI uses -- see `app.journal.actions`."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def enter_trade(self, opportunity_id: str, price: float) -> JournalEntry:
        return record_manual_entry(self.settings, opportunity_id=opportunity_id, price=price)

    def skip_trade(self, opportunity_id: str) -> JournalEntry:
        return record_skip(self.settings, opportunity_id=opportunity_id)

    def load_journal(self) -> list[JournalEntry]:
        journal = RecommendationJournal(self.settings.journal_dir / "journal.jsonl")
        return journal.load_all()


@dataclass
class DataSourceStatus:
    name: str
    configured: bool


@dataclass
class SystemStatus:
    version: str
    fundamental_engine_ok: bool
    fundamental_engine_detail: str | None
    price_provider_mode: str
    mt5_enabled: bool
    mt5_terminal_available: bool | None  # None = not probed (MT5_ENABLED is false)
    auto_execution: bool
    paper_trading: bool
    timezone: str
    risk_percent: float
    account_equity: float | None
    max_quote_age_seconds: int
    data_sources: list[DataSourceStatus]


class SystemStatusController:
    """Read-only status summary. Never exposes API key/secret *values* --
    only whether one is configured -- and never offers a way to flip
    `AUTO_EXECUTION` on."""

    APP_VERSION = "V1.2 Desktop"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def get_status(self) -> SystemStatus:
        settings = self.settings
        engine_ok, engine_detail = self._check_fundamental_engine()
        mt5_available = None
        if settings.mt5_enabled:
            mt5_available = MT5ReadOnlyPriceProvider().is_terminal_available()
        return SystemStatus(
            version=self.APP_VERSION,
            fundamental_engine_ok=engine_ok,
            fundamental_engine_detail=engine_detail,
            price_provider_mode=settings.price_provider,
            mt5_enabled=settings.mt5_enabled,
            mt5_terminal_available=mt5_available,
            auto_execution=settings.auto_execution,
            paper_trading=settings.paper_trading,
            timezone=settings.timezone,
            risk_percent=settings.risk_percent,
            account_equity=settings.account_equity,
            max_quote_age_seconds=settings.max_quote_age_seconds,
            data_sources=[
                DataSourceStatus(name="FRED", configured=bool(settings.fred_api_key)),
                DataSourceStatus(name="EIA", configured=bool(settings.eia_api_key)),
                DataSourceStatus(name="ECB", configured=True),  # keyless, always available
                DataSourceStatus(name="Eurostat", configured=True),
                DataSourceStatus(name="BLS", configured=True),
                DataSourceStatus(name="CFTC", configured=True),
                DataSourceStatus(
                    name="Claude synthesis (optional)", configured=bool(settings.anthropic_api_key)
                ),
            ],
        )

    def check_price_provider(self) -> str:
        """Returns a short human string describing the resolved price
        provider without fetching a live quote (which requires a symbol
        and would be misleading as a generic "system status" check)."""
        provider = build_price_provider(self.settings)
        return provider.mode

    @staticmethod
    def _check_fundamental_engine() -> tuple[bool, str | None]:
        try:
            from app.fundamental.decision import FundamentalDecisionEngine

            FundamentalDecisionEngine()
        except Exception as exc:  # noqa: BLE001 -- this is itself the health check
            return False, str(exc)
        return True, None
