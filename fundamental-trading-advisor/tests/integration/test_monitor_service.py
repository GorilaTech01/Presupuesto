"""TradeOpportunityMonitorService end-to-end (V1.1 monitoring spec).

Exercises the full WEEKLY -> WAITING FOR CATALYST -> REEVALUATE ->
READY_TO_TRADE/CANCELLED flow through the real service, its real
persistence, its real event bus, and the real AlertPolicy -- with no live
network call. Two isolation techniques are used, matched to what's being
tested:

  - `create_opportunity` takes an already-built `DecisionDraft` directly, so
    creation-flow tests just construct one by hand -- no monkeypatching
    needed, no second decision engine invoked.
  - `refresh_one` recomputes the draft itself by calling
    `app.fundamental.candidate.build_decision_draft` on freshly fetched
    facts. To drive specific re-evaluation scenarios (data confirms,
    contradicts, or is mixed) without a live network call, tests monkeypatch
    that one function at the `app.monitor.service` import site -- the same
    seam `WeeklyPipeline` and this service already share, so this never
    duplicates or bypasses the real decision engine, it just controls its
    input for the test. Lookahead-rejection tests instead monkeypatch
    `repository.fetch_many` directly, since that's what lookahead is
    actually checked against.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.config.settings import Settings
from app.domain.enums import (
    CatalystSeverity,
    Direction,
    ExecutionReadiness,
    Freshness,
    FundamentalBias,
    JournalStatus,
    ObservationKind,
    TradeAction,
    TriggerStatus,
)
from app.domain.models import CatalystEvent, FactObservation, FundamentalScore
from app.fundamental.candidate import CandidateEvaluation
from app.fundamental.decision import DecisionDraft
from app.journal.journal import RecommendationJournal
from app.journal.models import JournalEntry
from app.market.universe import get_asset
from app.monitor import service as service_module
from app.monitor.alerts import AlertPolicy
from app.monitor.service import TradeOpportunityMonitorService

_NOW = datetime(2026, 9, 1, tzinfo=UTC)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        fred_api_key=None,
        eia_api_key=None,
        data_dir=tmp_path,
        cache_dir=tmp_path / "cache",
        journal_dir=tmp_path / "journal",
    )


def _write_manual_price(tmp_path: Path, symbol: str = "EURUSD") -> None:
    (tmp_path / "manual_prices.json").write_text(
        json.dumps({symbol: {"bid": 1.1000, "ask": 1.1002, "as_of": "2026-09-01T12:00:00Z"}})
    )


def _draft(
    *,
    direction: Direction = Direction.SELL,
    trade_action: ExecutionReadiness = ExecutionReadiness.ENTER_NOW,
    catalysts: list[CatalystEvent] | None = None,
    conviction: int = 70,
) -> DecisionDraft:
    return DecisionDraft(
        symbol="EURUSD",
        direction=direction,
        trade_action=trade_action,
        conviction=conviction,
        thesis="test thesis",
        top_drivers=[],
        catalysts=catalysts or [],
        entry_condition="test entry condition",
        fundamental_invalidation="test invalidation",
        risks=[],
        time_stop="Friday close",
        data_freshness=Freshness.FRESH,
        sources=["TESTSRC"],
        conviction_breakdown=None,
        reasons=[],
    )


def _catalyst(
    *,
    severity: CatalystSeverity = CatalystSeverity.CRITICAL,
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
        severity=severity,
        actual=actual,
        consensus=consensus,
    )


def _fake_score() -> FundamentalScore:
    return FundamentalScore(
        subject="EURUSD", total=0.0, drivers=[], data_cutoff_utc=_NOW, warnings=[]
    )


def _seed_journal_entry(settings: Settings, recommendation_id: str) -> None:
    journal = RecommendationJournal(settings.journal_dir / "journal.jsonl")
    journal.add(
        JournalEntry(
            recommendation_id=recommendation_id,
            generated_at=_NOW,
            data_cutoff=_NOW,
            asset="EURUSD",
            symbol="EURUSD",
            direction=Direction.SELL,
            conviction=70,
            entry_condition="wait for confirmation",
            recommended_entry=None,
            stop_loss=None,
            take_profit=None,
            risk_reward=None,
            time_stop="Friday close",
            fundamental_thesis="test",
            drivers=[],
            catalysts=[],
            invalidation="n/a",
            sources=["TESTSRC"],
        )
    )


class _RecordingSink:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, message: str, *, event: object) -> None:
        self.sent.append(message)


# --------------------------------------------------------------------------
# create_opportunity
# --------------------------------------------------------------------------


def test_create_opportunity_returns_none_when_not_worth_monitoring(tmp_path: Path):
    settings = _settings(tmp_path)
    service = TradeOpportunityMonitorService(settings)
    try:
        definition = get_asset("EURUSD")
        draft = _draft(direction=Direction.NO_TRADE, trade_action=ExecutionReadiness.NONE)
        result = service.create_opportunity(
            definition=definition,
            draft=draft,
            evaluation_score=0.05,  # far below monitoring-interest threshold
            favored_country="US",
            price=None,
            recommendation_id="rec-1",
            data_cutoff=_NOW,
        )
        assert result is None
        assert service.store.load_all() == []
    finally:
        service.close()


def test_create_opportunity_persists_wait_state_and_emits_created_event(tmp_path: Path):
    settings = _settings(tmp_path)
    service = TradeOpportunityMonitorService(settings)
    received: list[str] = []
    service.event_bus.subscribe(lambda e: received.append(e.event_type))
    try:
        definition = get_asset("EURUSD")
        pending = _catalyst(actual=None)
        draft = _draft(
            direction=Direction.SELL, trade_action=ExecutionReadiness.ENTER_NOW, catalysts=[pending]
        )
        opportunity = service.create_opportunity(
            definition=definition,
            draft=draft,
            evaluation_score=-0.9,
            favored_country="US",
            price=None,
            recommendation_id="rec-2",
            data_cutoff=_NOW,
        )
        assert opportunity is not None
        assert opportunity.trade_action is TradeAction.WAIT
        assert opportunity.fundamental_bias is FundamentalBias.BEARISH
        assert service.store.get(opportunity.opportunity_id) is not None
        assert "TradeOpportunityCreated" in received
    finally:
        service.close()


def test_create_opportunity_can_reach_ready_to_trade_immediately(tmp_path: Path):
    settings = _settings(tmp_path)
    _write_manual_price(tmp_path)
    service = TradeOpportunityMonitorService(settings)
    try:
        definition = get_asset("EURUSD")
        draft = _draft(
            direction=Direction.SELL, trade_action=ExecutionReadiness.ENTER_NOW, catalysts=[]
        )
        opportunity = service.create_opportunity(
            definition=definition,
            draft=draft,
            evaluation_score=-0.9,
            favored_country="US",
            price=service.price_provider.get_quote("EURUSD"),
            recommendation_id="rec-3",
            data_cutoff=_NOW,
        )
        assert opportunity is not None
        assert opportunity.trade_action is TradeAction.READY_TO_TRADE
        assert opportunity.trade_plan is not None
    finally:
        service.close()


# --------------------------------------------------------------------------
# refresh_one -- scenario A: data confirms -> READY_TO_TRADE
# --------------------------------------------------------------------------


def test_refresh_one_transitions_wait_to_ready_to_trade_when_data_confirms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    settings = _settings(tmp_path)
    _write_manual_price(tmp_path)
    service = TradeOpportunityMonitorService(settings)
    _seed_journal_entry(settings, "rec-a")
    received: list[str] = []
    alert_sink = _RecordingSink()
    alert_policy = AlertPolicy(alert_sink)
    service.event_bus.subscribe(lambda e: received.append(e.event_type))
    service.event_bus.subscribe(alert_policy.handle)
    try:
        definition = get_asset("EURUSD")
        pending = _catalyst(actual=None)
        wait_draft = _draft(
            direction=Direction.SELL, trade_action=ExecutionReadiness.ENTER_NOW, catalysts=[pending]
        )
        opportunity = service.create_opportunity(
            definition=definition,
            draft=wait_draft,
            evaluation_score=-0.9,
            favored_country="US",
            price=None,
            recommendation_id="rec-a",
            data_cutoff=_NOW,
        )
        assert opportunity is not None
        assert opportunity.trade_action is TradeAction.WAIT

        confirmed_catalyst = _catalyst(actual=200.0, consensus=150.0)  # hawkish, confirms
        confirmed_draft = _draft(
            direction=Direction.SELL,
            trade_action=ExecutionReadiness.ENTER_NOW,
            catalysts=[confirmed_catalyst],
        )

        def fake_build_decision_draft(
            defn, fetch_result, *, catalyst_service, decision_engine, timezone_name
        ):
            evaluation = CandidateEvaluation(definition=defn, score=_fake_score(), bias=-0.9)
            return confirmed_draft, evaluation, "US"

        monkeypatch.setattr(service_module, "build_decision_draft", fake_build_decision_draft)

        updated, state_changed = service.refresh_one(opportunity)

        assert state_changed is True
        assert updated.trade_action is TradeAction.READY_TO_TRADE
        assert updated.trade_plan is not None
        assert "TradeOpportunityReady" in received

        journal = RecommendationJournal(settings.journal_dir / "journal.jsonl")
        entry = journal.find("rec-a")
        assert entry is not None
        assert entry.ready_to_trade_at is not None

        assert len(alert_sink.sent) >= 1
    finally:
        service.close()


# --------------------------------------------------------------------------
# refresh_one -- scenario B: data contradicts -> CANCELLED
# --------------------------------------------------------------------------


def test_refresh_one_cancels_when_catalyst_contradicts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    settings = _settings(tmp_path)
    service = TradeOpportunityMonitorService(settings)
    _seed_journal_entry(settings, "rec-b")
    try:
        definition = get_asset("EURUSD")
        pending = _catalyst(actual=None)
        wait_draft = _draft(
            direction=Direction.SELL, trade_action=ExecutionReadiness.ENTER_NOW, catalysts=[pending]
        )
        opportunity = service.create_opportunity(
            definition=definition,
            draft=wait_draft,
            evaluation_score=-0.9,
            favored_country="US",
            price=None,
            recommendation_id="rec-b",
            data_cutoff=_NOW,
        )
        assert opportunity is not None

        contradicting_catalyst = _catalyst(actual=80.0, consensus=150.0)  # dovish, contradicts
        contradicting_draft = _draft(
            direction=Direction.SELL,
            trade_action=ExecutionReadiness.ENTER_NOW,
            catalysts=[contradicting_catalyst],
        )

        def fake_build_decision_draft(
            defn, fetch_result, *, catalyst_service, decision_engine, timezone_name
        ):
            evaluation = CandidateEvaluation(definition=defn, score=_fake_score(), bias=-0.9)
            return contradicting_draft, evaluation, "US"

        monkeypatch.setattr(service_module, "build_decision_draft", fake_build_decision_draft)

        updated, state_changed = service.refresh_one(opportunity)

        assert state_changed is True
        assert updated.trade_action is TradeAction.CANCELLED
        assert updated.trigger_status is TriggerStatus.FAILED
        assert updated.cancellation_reason is not None

        journal = RecommendationJournal(settings.journal_dir / "journal.jsonl")
        entry = journal.find("rec-b")
        assert entry is not None
        assert entry.status is JournalStatus.CANCELLED
    finally:
        service.close()


# --------------------------------------------------------------------------
# refresh_one -- scenario C: mixed data -> stays at WAIT
# --------------------------------------------------------------------------


def test_refresh_one_stays_at_wait_on_mixed_signal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    settings = _settings(tmp_path)
    service = TradeOpportunityMonitorService(settings)
    try:
        definition = get_asset("EURUSD")
        pending = _catalyst(actual=None)
        wait_draft = _draft(
            direction=Direction.SELL, trade_action=ExecutionReadiness.ENTER_NOW, catalysts=[pending]
        )
        opportunity = service.create_opportunity(
            definition=definition,
            draft=wait_draft,
            evaluation_score=-0.9,
            favored_country="US",
            price=None,
            recommendation_id="rec-c",
            data_cutoff=_NOW,
        )
        assert opportunity is not None

        confirming = _catalyst(indicator="us_nonfarm_payrolls", actual=200.0, consensus=150.0)
        still_pending = _catalyst(
            indicator="us_cpi_yoy", severity=CatalystSeverity.HIGH, actual=None
        )
        mixed_draft = _draft(
            direction=Direction.SELL,
            trade_action=ExecutionReadiness.ENTER_NOW,
            catalysts=[confirming, still_pending],
        )

        def fake_build_decision_draft(
            defn, fetch_result, *, catalyst_service, decision_engine, timezone_name
        ):
            evaluation = CandidateEvaluation(definition=defn, score=_fake_score(), bias=-0.9)
            return mixed_draft, evaluation, "US"

        monkeypatch.setattr(service_module, "build_decision_draft", fake_build_decision_draft)

        updated, _ = service.refresh_one(opportunity)
        assert updated.trade_action is TradeAction.WAIT
        assert updated.trigger_status is TriggerStatus.PARTIALLY_CONFIRMED
    finally:
        service.close()


# --------------------------------------------------------------------------
# refresh_one -- scenario D: lookahead rejection
# --------------------------------------------------------------------------


def test_refresh_one_rejects_future_dated_facts_without_changing_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    settings = _settings(tmp_path)
    service = TradeOpportunityMonitorService(settings)
    try:
        definition = get_asset("EURUSD")
        wait_draft = _draft(direction=Direction.SELL, trade_action=ExecutionReadiness.ENTER_NOW)
        opportunity = service.create_opportunity(
            definition=definition,
            draft=wait_draft,
            evaluation_score=-0.9,
            favored_country="US",
            price=None,
            recommendation_id="rec-d",
            data_cutoff=_NOW,
        )
        assert opportunity is not None
        original_bias = opportunity.fundamental_bias
        original_action = opportunity.trade_action

        from app.sources.repository import FetchResult

        future_fact = FactObservation(
            indicator="us_nonfarm_payrolls",
            country="US",
            source="TESTSRC",
            source_url="https://example.invalid",
            publication_timestamp=datetime.now(UTC) + timedelta(days=30),
            observation_period="2026-09",
            kind=ObservationKind.ACTUAL,
            value=200.0,
            unit="thousands",
            retrieval_timestamp=datetime.now(UTC),
        )

        def fake_fetch_many(indicators):
            return FetchResult(facts={"us_nonfarm_payrolls": future_fact}, errors={})

        monkeypatch.setattr(service.repository, "fetch_many", fake_fetch_many)

        updated, state_changed = service.refresh_one(opportunity)

        # state itself is left exactly as it was -- only the audit trail
        # records the rejected attempt (fail-closed, not silently re-decided)
        assert updated.fundamental_bias == original_bias
        assert updated.trade_action == original_action
        assert "LOOKAHEAD_VIOLATION_DETECTED" in updated.decision_history[-1].reason
    finally:
        service.close()


# --------------------------------------------------------------------------
# refresh_one -- expiration
# --------------------------------------------------------------------------


def test_refresh_one_expires_past_valid_until(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    settings = _settings(tmp_path)
    service = TradeOpportunityMonitorService(settings)
    _seed_journal_entry(settings, "rec-e")
    try:
        definition = get_asset("EURUSD")
        wait_draft = _draft(direction=Direction.SELL, trade_action=ExecutionReadiness.ENTER_NOW)
        opportunity = service.create_opportunity(
            definition=definition,
            draft=wait_draft,
            evaluation_score=-0.9,
            favored_country="US",
            price=None,
            recommendation_id="rec-e",
            data_cutoff=_NOW,
        )
        assert opportunity is not None
        expired = opportunity.model_copy(
            update={"valid_until": datetime.now(UTC) - timedelta(days=1)}
        )
        service.store.save(expired)

        def fake_build_decision_draft(
            defn, fetch_result, *, catalyst_service, decision_engine, timezone_name
        ):
            evaluation = CandidateEvaluation(definition=defn, score=_fake_score(), bias=-0.9)
            return wait_draft, evaluation, "US"

        monkeypatch.setattr(service_module, "build_decision_draft", fake_build_decision_draft)

        updated, state_changed = service.refresh_one(expired)
        assert updated.trade_action is TradeAction.CANCELLED
        assert updated.trigger_status is TriggerStatus.EXPIRED
        assert updated.cancellation_reason == "OPPORTUNITY_EXPIRED"

        journal = RecommendationJournal(settings.journal_dir / "journal.jsonl")
        entry = journal.find("rec-e")
        assert entry is not None
        assert entry.status is JournalStatus.NOT_TRIGGERED
    finally:
        service.close()


# --------------------------------------------------------------------------
# refresh_all -- terminal state is never re-evaluated (scenario E, part 1)
# --------------------------------------------------------------------------


def test_refresh_all_never_touches_cancelled_opportunities(tmp_path: Path):
    settings = _settings(tmp_path)
    service = TradeOpportunityMonitorService(settings)
    try:
        definition = get_asset("EURUSD")
        wait_draft = _draft(direction=Direction.SELL, trade_action=ExecutionReadiness.ENTER_NOW)
        opportunity = service.create_opportunity(
            definition=definition,
            draft=wait_draft,
            evaluation_score=-0.9,
            favored_country="US",
            price=None,
            recommendation_id="rec-f",
            data_cutoff=_NOW,
        )
        assert opportunity is not None
        cancelled = opportunity.model_copy(
            update={
                "trade_action": TradeAction.CANCELLED,
                "cancellation_reason": "TEST",
                "trade_plan": None,
            }
        )
        service.store.save(cancelled)

        results = service.refresh_all()

        assert results == []
        untouched = service.store.get(opportunity.opportunity_id)
        assert untouched is not None
        assert untouched.last_evaluated_at == cancelled.last_evaluated_at
    finally:
        service.close()


# --------------------------------------------------------------------------
# scenario E, part 2: same catalyst processed twice -> no duplicate alert
# --------------------------------------------------------------------------


def test_no_duplicate_alert_when_state_has_not_materially_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    settings = _settings(tmp_path)
    _write_manual_price(tmp_path)
    service = TradeOpportunityMonitorService(settings)
    alert_sink = _RecordingSink()
    alert_policy = AlertPolicy(alert_sink)
    service.event_bus.subscribe(alert_policy.handle)
    try:
        definition = get_asset("EURUSD")
        wait_draft = _draft(
            direction=Direction.SELL,
            trade_action=ExecutionReadiness.ENTER_NOW,
            catalysts=[_catalyst(actual=None)],
        )
        opportunity = service.create_opportunity(
            definition=definition,
            draft=wait_draft,
            evaluation_score=-0.9,
            favored_country="US",
            price=None,
            recommendation_id="rec-g",
            data_cutoff=_NOW,
        )
        assert opportunity is not None

        confirmed_draft = _draft(
            direction=Direction.SELL,
            trade_action=ExecutionReadiness.ENTER_NOW,
            catalysts=[_catalyst(actual=200.0, consensus=150.0)],
        )

        def fake_build_decision_draft(
            defn, fetch_result, *, catalyst_service, decision_engine, timezone_name
        ):
            evaluation = CandidateEvaluation(definition=defn, score=_fake_score(), bias=-0.9)
            return confirmed_draft, evaluation, "US"

        monkeypatch.setattr(service_module, "build_decision_draft", fake_build_decision_draft)

        first, first_changed = service.refresh_one(opportunity)
        assert first_changed is True
        assert first.trade_action is TradeAction.READY_TO_TRADE
        first_alert_count = len(alert_sink.sent)
        assert first_alert_count >= 1

        # re-run the exact same (already-processed) catalyst data again
        second, second_changed = service.refresh_one(first)
        assert second_changed is False
        assert len(alert_sink.sent) == first_alert_count  # no duplicate alert
    finally:
        service.close()


# --------------------------------------------------------------------------
# incremental vs. full-refresh equivalence (no new data available either way)
# --------------------------------------------------------------------------


def test_incremental_and_full_refresh_agree_when_no_new_data_exists(tmp_path: Path):
    settings = _settings(tmp_path)
    service_incremental = TradeOpportunityMonitorService(settings)
    try:
        definition = get_asset("EURUSD")
        draft = _draft(direction=Direction.SELL, trade_action=ExecutionReadiness.ENTER_NOW)
        opportunity = service_incremental.create_opportunity(
            definition=definition,
            draft=draft,
            evaluation_score=-0.9,
            favored_country="US",
            price=None,
            recommendation_id="rec-h",
            data_cutoff=_NOW,
        )
        assert opportunity is not None
        incremental_result, _ = service_incremental.refresh_one(opportunity, full_refresh=False)
        full_result, _ = service_incremental.refresh_one(opportunity, full_refresh=True)

        assert incremental_result.trade_action == full_result.trade_action
        assert incremental_result.fundamental_bias == full_result.fundamental_bias
    finally:
        service_incremental.close()
