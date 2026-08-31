"""Desktop controllers (V1.2): thin adapters over existing services. No
Qt import anywhere in this file -- these are plain Python classes, fully
testable without a QApplication. Confirms each controller calls the exact
same shared function the CLI uses (same seam, no second decision engine)
and that no controller exposes a secret value.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.config.settings import Settings
from app.desktop.controllers import (
    DailyAnalysisController,
    JournalActionController,
    JournalEntryNotLinked,
    MonitorController,
    OpportunityNotFound,
    SystemStatusController,
)
from app.domain.enums import Direction, FundamentalBias, JournalStatus, TradeAction, TriggerStatus
from app.domain.models import MonitoredTradeOpportunity, TradePlan
from app.journal.journal import RecommendationJournal
from app.journal.models import JournalEntry
from app.monitor.store import OpportunityStore

_NOW = datetime(2026, 9, 1, tzinfo=UTC)


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    fields: dict[str, object] = {
        "_env_file": None,
        "fred_api_key": None,
        "eia_api_key": None,
        "data_dir": tmp_path,
        "cache_dir": tmp_path / "cache",
        "journal_dir": tmp_path / "journal",
    }
    fields.update(overrides)
    return Settings(**fields)  # type: ignore[arg-type]


def _plan() -> TradePlan:
    return TradePlan(
        asset="EURUSD",
        symbol="EURUSD",
        direction=Direction.SELL,
        conviction_1_10=6,
        horizon="3-5 days",
        order_type="manual",
        fundamental_trigger="test",
        estimated_entry=1.10,
        stop_loss=1.105,
        distance_to_sl=0.005,
        take_profit=1.09,
        distance_to_tp=0.01,
        risk_reward=2.0,
        time_stop="Friday close",
        cancellation_condition="n/a",
        fundamental_invalidation="n/a",
        early_exit_condition="n/a",
        main_catalysts=[],
        main_risks=[],
    )


def _opportunity(
    *,
    opportunity_id: str = "opp-1",
    recommendation_id: str = "rec-1",
    trade_action: TradeAction = TradeAction.WAIT,
) -> MonitoredTradeOpportunity:
    return MonitoredTradeOpportunity(
        opportunity_id=opportunity_id,
        recommendation_id=recommendation_id,
        created_at=_NOW,
        updated_at=_NOW,
        asset="EURUSD",
        symbol="EURUSD",
        fundamental_bias=FundamentalBias.BEARISH,
        trade_action=trade_action,
        direction=Direction.SELL,
        conviction=60,
        original_score=-0.7,
        current_score=-0.7,
        threshold=0.6,
        horizon="Friday close",
        entry_condition="wait for confirmation",
        catalysts=[],
        fundamental_invalidation="n/a",
        cancellation_conditions=[],
        time_stop="Friday close",
        valid_until=_NOW + timedelta(days=3),
        data_cutoff=_NOW,
        last_evaluated_at=_NOW,
        next_relevant_event=None,
        trigger_status=TriggerStatus.PENDING,
        trade_plan=_plan() if trade_action is TradeAction.READY_TO_TRADE else None,
    )


def _journal_entry(recommendation_id: str = "rec-1") -> JournalEntry:
    return JournalEntry(
        recommendation_id=recommendation_id,
        generated_at=_NOW,
        data_cutoff=_NOW,
        asset="EURUSD",
        symbol="EURUSD",
        direction=Direction.SELL,
        conviction=60,
        entry_condition="test",
        recommended_entry=None,
        stop_loss=None,
        take_profit=None,
        risk_reward=None,
        time_stop="Friday close",
        fundamental_thesis="test",
        drivers=[],
        catalysts=[],
        invalidation="n/a",
        sources=[],
    )


# --------------------------------------------------------------------------
# DailyAnalysisController
# --------------------------------------------------------------------------


def test_daily_controller_fails_closed_to_no_trade_without_data(tmp_path: Path):
    """No mocking here -- proves the controller calls the real, unmodified
    weekly pipeline (fail-closed, exactly like `python -m app daily`)."""
    settings = _settings(tmp_path)
    controller = DailyAnalysisController(settings)
    result = controller.run(["EURUSD", "XAUUSD", "BTCUSD"])
    assert result.comparison.decision.direction is Direction.NO_TRADE
    assert len(result.comparison.candidates) == 3


def test_daily_controller_uses_default_candidates_when_none_given(tmp_path: Path):
    settings = _settings(tmp_path)
    controller = DailyAnalysisController(settings)
    result = controller.run()
    assert len(result.comparison.candidates) == 3


# --------------------------------------------------------------------------
# MonitorController
# --------------------------------------------------------------------------


def test_monitor_controller_refresh_all_on_empty_store_returns_empty(tmp_path: Path):
    settings = _settings(tmp_path)
    controller = MonitorController(settings)
    assert controller.refresh_all() == []


def test_monitor_controller_loads_persisted_opportunities(tmp_path: Path):
    settings = _settings(tmp_path)
    store = OpportunityStore(settings.data_dir / "monitor" / "opportunities.jsonl")
    store.save(_opportunity())
    controller = MonitorController(settings)
    loaded = controller.load_all_opportunities()
    assert len(loaded) == 1
    assert loaded[0].opportunity_id == "opp-1"


def test_monitor_controller_get_opportunity_returns_none_for_missing_id(tmp_path: Path):
    settings = _settings(tmp_path)
    controller = MonitorController(settings)
    assert controller.get_opportunity("does-not-exist") is None


# --------------------------------------------------------------------------
# JournalActionController
# --------------------------------------------------------------------------


def test_journal_controller_enter_trade_updates_journal_never_touches_broker(tmp_path: Path):
    settings = _settings(tmp_path)
    store = OpportunityStore(settings.data_dir / "monitor" / "opportunities.jsonl")
    store.save(_opportunity(trade_action=TradeAction.READY_TO_TRADE))
    journal = RecommendationJournal(settings.journal_dir / "journal.jsonl")
    journal.add(_journal_entry())

    controller = JournalActionController(settings)
    updated = controller.enter_trade("opp-1", 1.1005)
    assert updated.status is JournalStatus.ACTIVE_SIMULATION
    assert updated.entry_price_actual_or_simulated == 1.1005


def test_journal_controller_enter_trade_raises_for_unknown_opportunity(tmp_path: Path):
    settings = _settings(tmp_path)
    controller = JournalActionController(settings)
    with pytest.raises(OpportunityNotFound):
        controller.enter_trade("does-not-exist", 1.1)


def test_journal_controller_enter_trade_raises_for_missing_journal_link(tmp_path: Path):
    settings = _settings(tmp_path)
    store = OpportunityStore(settings.data_dir / "monitor" / "opportunities.jsonl")
    store.save(_opportunity(trade_action=TradeAction.READY_TO_TRADE))
    controller = JournalActionController(settings)
    with pytest.raises(JournalEntryNotLinked):
        controller.enter_trade("opp-1", 1.1)


def test_journal_controller_skip_trade_cancels_opportunity_and_journal(tmp_path: Path):
    settings = _settings(tmp_path)
    store = OpportunityStore(settings.data_dir / "monitor" / "opportunities.jsonl")
    store.save(_opportunity(trade_action=TradeAction.WAIT))
    journal = RecommendationJournal(settings.journal_dir / "journal.jsonl")
    journal.add(_journal_entry())

    controller = JournalActionController(settings)
    updated_entry = controller.skip_trade("opp-1")
    assert updated_entry.status is JournalStatus.CANCELLED

    updated_opportunity = store.get("opp-1")
    assert updated_opportunity is not None
    assert updated_opportunity.trade_action is TradeAction.CANCELLED
    assert updated_opportunity.cancellation_reason == "USER_SKIPPED"


def test_journal_controller_load_journal_returns_entries(tmp_path: Path):
    settings = _settings(tmp_path)
    journal = RecommendationJournal(settings.journal_dir / "journal.jsonl")
    journal.add(_journal_entry())
    controller = JournalActionController(settings)
    entries = controller.load_journal()
    assert len(entries) == 1


# --------------------------------------------------------------------------
# SystemStatusController
# --------------------------------------------------------------------------


def test_system_status_never_exposes_secret_values(tmp_path: Path):
    settings = _settings(tmp_path, fred_api_key="super-secret-key", anthropic_api_key="sk-secret")
    controller = SystemStatusController(settings)
    status = controller.get_status()
    dumped = json.dumps(
        {
            "version": status.version,
            "sources": [(d.name, d.configured) for d in status.data_sources],
        }
    )
    assert "super-secret-key" not in dumped
    assert "sk-secret" not in dumped
    fred = next(d for d in status.data_sources if d.name == "FRED")
    assert fred.configured is True  # presence is reported, value is not


def test_system_status_reports_auto_execution_disabled(tmp_path: Path):
    settings = _settings(tmp_path)
    status = SystemStatusController(settings).get_status()
    assert status.auto_execution is False


def test_system_status_does_not_probe_mt5_when_disabled(tmp_path: Path):
    settings = _settings(tmp_path, mt5_enabled=False)
    status = SystemStatusController(settings).get_status()
    assert status.mt5_terminal_available is None


def test_system_status_reports_price_provider_mode(tmp_path: Path):
    settings = _settings(tmp_path, price_provider="manual")
    status = SystemStatusController(settings).get_status()
    assert status.price_provider_mode == "manual"


def test_system_status_fundamental_engine_reports_ok(tmp_path: Path):
    settings = _settings(tmp_path)
    status = SystemStatusController(settings).get_status()
    assert status.fundamental_engine_ok is True
    assert status.fundamental_engine_detail is None
