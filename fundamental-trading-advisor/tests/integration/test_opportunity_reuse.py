"""Duplicate-opportunity fix: `create_opportunity` must continue an
existing active opportunity for the same (asset, direction, horizon)
thesis rather than starting a parallel one every time `weekly`/`daily`
runs again. See app/monitor/identity.py for the fingerprint rationale and
docs/daily_workflow.md for the user-facing behavior.

Uses the real `TradeOpportunityMonitorService.create_opportunity`, which
takes an already-built `DecisionDraft` directly -- no monkeypatching, no
live network call, no second decision engine.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.config.settings import Settings
from app.domain.enums import (
    CatalystSeverity,
    Direction,
    ExecutionReadiness,
    Freshness,
    TradeAction,
    TriggerStatus,
)
from app.domain.models import CatalystEvent
from app.fundamental.decision import DecisionDraft
from app.market.price_provider import CurrentMarketQuote
from app.market.universe import get_asset
from app.monitor.alerts import AlertPolicy
from app.monitor.service import TradeOpportunityMonitorService

_NOW = datetime(2026, 9, 1, tzinfo=UTC)
_HORIZON = "Friday close"


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        fred_api_key=None,
        eia_api_key=None,
        data_dir=tmp_path,
        cache_dir=tmp_path / "cache",
        journal_dir=tmp_path / "journal",
    )


def _draft(
    *,
    direction: Direction = Direction.SELL,
    conviction: int = 70,
    catalysts: list[CatalystEvent] | None = None,
    time_stop: str = _HORIZON,
) -> DecisionDraft:
    return DecisionDraft(
        symbol="EURUSD",
        direction=direction,
        trade_action=ExecutionReadiness.ENTER_NOW,
        conviction=conviction,
        thesis="test thesis",
        top_drivers=[],
        catalysts=catalysts or [],
        entry_condition="test entry condition",
        fundamental_invalidation="test invalidation",
        risks=[],
        time_stop=time_stop,
        data_freshness=Freshness.FRESH,
        sources=["TESTSRC"],
        conviction_breakdown=None,
        reasons=[],
    )


def _catalyst(
    *,
    actual: float | None = None,
    consensus: float | None = 150.0,
    indicator: str = "us_nonfarm_payrolls",
) -> CatalystEvent:
    return CatalystEvent(
        symbol_context="US",
        date_utc=_NOW,
        date_local=_NOW,
        country="US",
        indicator=indicator,
        severity=CatalystSeverity.CRITICAL,
        actual=actual,
        consensus=consensus,
    )


def _quote(bid: float = 1.1000, ask: float = 1.1002) -> CurrentMarketQuote:
    return CurrentMarketQuote(
        symbol="EURUSD", broker_symbol="EURUSD", bid=bid, ask=ask, timestamp=_NOW, source="TEST"
    )


class _RecordingSink:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, message: str, *, event: object) -> None:
        self.sent.append(message)


def test_first_call_creates_a_new_opportunity(tmp_path: Path):
    settings = _settings(tmp_path)
    service = TradeOpportunityMonitorService(settings)
    try:
        definition = get_asset("EURUSD")
        opp = service.create_opportunity(
            definition=definition,
            draft=_draft(catalysts=[_catalyst(actual=None)]),
            evaluation_score=-0.9,
            favored_country="US",
            price=None,
            recommendation_id="rec-1",
            data_cutoff=_NOW,
        )
        assert opp is not None
        assert len(service.store.load_all()) == 1
    finally:
        service.close()


def test_second_identical_call_reuses_the_same_opportunity_id(tmp_path: Path):
    settings = _settings(tmp_path)
    service = TradeOpportunityMonitorService(settings)
    try:
        definition = get_asset("EURUSD")
        pending = _catalyst(actual=None)
        first = service.create_opportunity(
            definition=definition,
            draft=_draft(catalysts=[pending]),
            evaluation_score=-0.9,
            favored_country="US",
            price=None,
            recommendation_id="rec-1",
            data_cutoff=_NOW,
        )
        second = service.create_opportunity(
            definition=definition,
            draft=_draft(catalysts=[pending]),
            evaluation_score=-0.9,
            favored_country="US",
            price=None,
            recommendation_id="rec-2",
            data_cutoff=_NOW,
        )
        assert first is not None
        assert second is not None
        assert second.opportunity_id == first.opportunity_id
        # the original creating recommendation_id is preserved -- reuse
        # never rewrites which journal entry the opportunity is linked to
        assert second.recommendation_id == "rec-1"
        assert len(service.store.load_all()) == 1
    finally:
        service.close()


def test_updated_score_and_conviction_are_reflected_on_reuse(tmp_path: Path):
    settings = _settings(tmp_path)
    service = TradeOpportunityMonitorService(settings)
    try:
        definition = get_asset("EURUSD")
        pending = _catalyst(actual=None)
        first = service.create_opportunity(
            definition=definition,
            draft=_draft(catalysts=[pending], conviction=60),
            evaluation_score=-0.7,
            favored_country="US",
            price=None,
            recommendation_id="rec-1",
            data_cutoff=_NOW,
        )
        later_cutoff = _NOW + timedelta(hours=6)
        second = service.create_opportunity(
            definition=definition,
            draft=_draft(catalysts=[pending], conviction=80),
            evaluation_score=-0.95,
            favored_country="US",
            price=None,
            recommendation_id="rec-2",
            data_cutoff=later_cutoff,
        )
        assert first is not None and second is not None
        assert second.opportunity_id == first.opportunity_id
        assert second.current_score == -0.95
        assert second.data_cutoff == later_cutoff
        assert second.original_score == first.original_score  # never rewritten
    finally:
        service.close()


def test_opposite_direction_creates_a_new_opportunity(tmp_path: Path):
    settings = _settings(tmp_path)
    service = TradeOpportunityMonitorService(settings)
    try:
        definition = get_asset("EURUSD")
        bearish = service.create_opportunity(
            definition=definition,
            draft=_draft(direction=Direction.SELL, catalysts=[_catalyst(actual=None)]),
            evaluation_score=-0.9,
            favored_country="US",
            price=None,
            recommendation_id="rec-1",
            data_cutoff=_NOW,
        )
        bullish = service.create_opportunity(
            definition=definition,
            draft=_draft(direction=Direction.BUY, catalysts=[_catalyst(actual=None)]),
            evaluation_score=0.9,
            favored_country="US",
            price=None,
            recommendation_id="rec-2",
            data_cutoff=_NOW,
        )
        assert bearish is not None and bullish is not None
        assert bullish.opportunity_id != bearish.opportunity_id
        assert len(service.store.load_all()) == 2
    finally:
        service.close()


def test_different_horizon_creates_a_new_opportunity(tmp_path: Path):
    settings = _settings(tmp_path)
    service = TradeOpportunityMonitorService(settings)
    try:
        definition = get_asset("EURUSD")
        first = service.create_opportunity(
            definition=definition,
            draft=_draft(catalysts=[_catalyst(actual=None)], time_stop="Friday close"),
            evaluation_score=-0.9,
            favored_country="US",
            price=None,
            recommendation_id="rec-1",
            data_cutoff=_NOW,
        )
        second = service.create_opportunity(
            definition=definition,
            draft=_draft(catalysts=[_catalyst(actual=None)], time_stop="End of next month"),
            evaluation_score=-0.9,
            favored_country="US",
            price=None,
            recommendation_id="rec-2",
            data_cutoff=_NOW,
        )
        assert first is not None and second is not None
        assert second.opportunity_id != first.opportunity_id
        assert len(service.store.load_all()) == 2
    finally:
        service.close()


def test_cancelled_opportunity_is_not_reused(tmp_path: Path):
    settings = _settings(tmp_path)
    service = TradeOpportunityMonitorService(settings)
    try:
        definition = get_asset("EURUSD")
        pending = _catalyst(actual=None)
        first = service.create_opportunity(
            definition=definition,
            draft=_draft(catalysts=[pending]),
            evaluation_score=-0.9,
            favored_country="US",
            price=None,
            recommendation_id="rec-1",
            data_cutoff=_NOW,
        )
        assert first is not None
        service.cancel_opportunity(first, reason="TEST_CANCEL")

        second = service.create_opportunity(
            definition=definition,
            draft=_draft(catalysts=[pending]),
            evaluation_score=-0.9,
            favored_country="US",
            price=None,
            recommendation_id="rec-2",
            data_cutoff=_NOW,
        )
        assert second is not None
        assert second.opportunity_id != first.opportunity_id
        assert len(service.store.load_all()) == 2
    finally:
        service.close()


def test_expired_opportunity_is_not_reused(tmp_path: Path):
    settings = _settings(tmp_path)
    service = TradeOpportunityMonitorService(settings)
    try:
        definition = get_asset("EURUSD")
        pending = _catalyst(actual=None)
        first = service.create_opportunity(
            definition=definition,
            draft=_draft(catalysts=[pending]),
            evaluation_score=-0.9,
            favored_country="US",
            price=None,
            recommendation_id="rec-1",
            data_cutoff=_NOW,
        )
        assert first is not None
        expired = first.model_copy(update={"valid_until": datetime.now(UTC) - timedelta(days=1)})
        service.store.save(expired)
        updated, _ = service.refresh_one(expired)
        assert updated.trade_action is TradeAction.CANCELLED
        assert updated.trigger_status is TriggerStatus.EXPIRED

        second = service.create_opportunity(
            definition=definition,
            draft=_draft(catalysts=[pending]),
            evaluation_score=-0.9,
            favored_country="US",
            price=None,
            recommendation_id="rec-2",
            data_cutoff=_NOW,
        )
        assert second is not None
        assert second.opportunity_id != first.opportunity_id
    finally:
        service.close()


def test_skipped_opportunity_is_not_reused(tmp_path: Path):
    settings = _settings(tmp_path)
    service = TradeOpportunityMonitorService(settings)
    try:
        definition = get_asset("EURUSD")
        pending = _catalyst(actual=None)
        first = service.create_opportunity(
            definition=definition,
            draft=_draft(catalysts=[pending]),
            evaluation_score=-0.9,
            favored_country="US",
            price=None,
            recommendation_id="rec-1",
            data_cutoff=_NOW,
        )
        assert first is not None
        skipped = service.cancel_opportunity(first, reason="USER_SKIPPED")
        assert skipped.trade_action is TradeAction.CANCELLED
        assert skipped.cancellation_reason == "USER_SKIPPED"

        second = service.create_opportunity(
            definition=definition,
            draft=_draft(catalysts=[pending]),
            evaluation_score=-0.9,
            favored_country="US",
            price=None,
            recommendation_id="rec-2",
            data_cutoff=_NOW,
        )
        assert second is not None
        assert second.opportunity_id != first.opportunity_id
    finally:
        service.close()


def test_price_only_change_does_not_create_new_opportunity(tmp_path: Path):
    settings = _settings(tmp_path)
    service = TradeOpportunityMonitorService(settings)
    try:
        definition = get_asset("EURUSD")
        draft = _draft(catalysts=[])
        first = service.create_opportunity(
            definition=definition,
            draft=draft,
            evaluation_score=-0.9,
            favored_country="US",
            price=_quote(bid=1.1000, ask=1.1002),
            recommendation_id="rec-1",
            data_cutoff=_NOW,
        )
        second = service.create_opportunity(
            definition=definition,
            draft=draft,
            evaluation_score=-0.9,
            favored_country="US",
            price=_quote(bid=1.2500, ask=1.2503),  # a completely different price
            recommendation_id="rec-2",
            data_cutoff=_NOW,
        )
        assert first is not None and second is not None
        assert second.opportunity_id == first.opportunity_id
        assert len(service.store.load_all()) == 1
    finally:
        service.close()


def test_catalyst_update_within_same_thesis_reuses_opportunity(tmp_path: Path):
    settings = _settings(tmp_path)
    service = TradeOpportunityMonitorService(settings)
    try:
        definition = get_asset("EURUSD")
        first = service.create_opportunity(
            definition=definition,
            draft=_draft(catalysts=[]),
            evaluation_score=-0.9,
            favored_country="US",
            price=None,
            recommendation_id="rec-1",
            data_cutoff=_NOW,
        )
        new_catalyst = _catalyst(indicator="us_cpi_yoy", actual=None)
        second = service.create_opportunity(
            definition=definition,
            draft=_draft(catalysts=[new_catalyst]),
            evaluation_score=-0.9,
            favored_country="US",
            price=None,
            recommendation_id="rec-2",
            data_cutoff=_NOW,
        )
        assert first is not None and second is not None
        assert second.opportunity_id == first.opportunity_id
        assert len(second.catalysts) == 1
        assert second.catalysts[0].indicator == "us_cpi_yoy"
    finally:
        service.close()


def test_history_and_events_remain_auditable_across_reuse(tmp_path: Path):
    settings = _settings(tmp_path)
    service = TradeOpportunityMonitorService(settings)
    try:
        definition = get_asset("EURUSD")
        pending = _catalyst(actual=None)
        first = service.create_opportunity(
            definition=definition,
            draft=_draft(catalysts=[pending], conviction=60),
            evaluation_score=-0.7,
            favored_country="US",
            price=None,
            recommendation_id="rec-1",
            data_cutoff=_NOW,
        )
        assert first is not None
        assert len(first.decision_history) == 1

        second = service.create_opportunity(
            definition=definition,
            draft=_draft(catalysts=[pending], conviction=80),
            evaluation_score=-0.95,
            favored_country="US",
            price=None,
            recommendation_id="rec-2",
            data_cutoff=_NOW,
        )
        assert second is not None
        # history is appended, never overwritten or truncated
        assert len(second.decision_history) == 2
        assert second.decision_history[0] == first.decision_history[0]

        events = service.event_log.for_opportunity(second.opportunity_id)
        event_types = [e.event_type for e in events]
        assert "TradeOpportunityCreated" in event_types
        assert len(events) >= 1
    finally:
        service.close()


def test_no_duplicate_alert_when_reused_opportunity_state_is_unchanged(tmp_path: Path):
    settings = _settings(tmp_path)
    service = TradeOpportunityMonitorService(settings)
    alert_sink = _RecordingSink()
    alert_policy = AlertPolicy(alert_sink)
    service.event_bus.subscribe(alert_policy.handle)
    try:
        definition = get_asset("EURUSD")
        pending = _catalyst(actual=None)
        draft = _draft(catalysts=[pending])
        first = service.create_opportunity(
            definition=definition,
            draft=draft,
            evaluation_score=-0.9,
            favored_country="US",
            price=None,
            recommendation_id="rec-1",
            data_cutoff=_NOW,
        )
        assert first is not None
        first_alert_count = len(alert_sink.sent)

        second = service.create_opportunity(
            definition=definition,
            draft=draft,
            evaluation_score=-0.9,
            favored_country="US",
            price=None,
            recommendation_id="rec-2",
            data_cutoff=_NOW,
        )
        assert second is not None
        assert second.opportunity_id == first.opportunity_id
        # identical state (same WAIT, same conviction, same bias) -> no new alert
        assert len(alert_sink.sent) == first_alert_count
    finally:
        service.close()
