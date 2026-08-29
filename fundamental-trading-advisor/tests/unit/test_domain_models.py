from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.domain.enums import AssetClass, CatalystSeverity, Direction, DriverCategory
from app.domain.models import (
    CatalystEvent,
    DriverScore,
    FundamentalDecision,
    FundamentalScore,
    TradePlan,
    WeeklyComparison,
)


def _driver(contribution: float) -> DriverScore:
    return DriverScore(
        category=DriverCategory.MONETARY_POLICY,
        label="test",
        contribution=contribution,
        rationale="r",
        supporting_facts=[],
    )


def test_fundamental_score_total_must_match_driver_sum():
    with pytest.raises(ValidationError):
        FundamentalScore(
            subject="USD",
            total=1.0,
            drivers=[_driver(0.5), _driver(0.2)],
            data_cutoff_utc=datetime.now(UTC),
        )


def test_fundamental_score_accepts_matching_total():
    score = FundamentalScore(
        subject="USD",
        total=0.7,
        drivers=[_driver(0.5), _driver(0.2)],
        data_cutoff_utc=datetime.now(UTC),
    )
    assert score.total == 0.7


def test_no_trade_decision_cannot_carry_a_trade_plan():
    plan = TradePlan(
        asset="EURUSD",
        symbol="EURUSD",
        direction=Direction.BUY,
        conviction_1_10=5,
        horizon="1w",
        order_type="market",
        fundamental_trigger="x",
        estimated_entry=1.1,
        stop_loss=1.09,
        distance_to_sl=0.01,
        take_profit=1.12,
        distance_to_tp=0.02,
        risk_reward=2.0,
        time_stop="Friday",
        cancellation_condition="x",
        fundamental_invalidation="x",
        early_exit_condition="x",
        main_catalysts=[],
        main_risks=[],
    )
    with pytest.raises(ValidationError):
        FundamentalDecision(
            symbol="EURUSD",
            asset_class=AssetClass.FX,
            direction=Direction.NO_TRADE,
            conviction=0,
            horizon="N/A",
            thesis="no trade",
            top_drivers=[],
            catalysts=[],
            entry_condition="N/A",
            fundamental_invalidation="N/A",
            risks=[],
            time_stop="N/A",
            data_freshness="FRESH",
            sources=[],
            data_cutoff_utc=datetime.now(UTC),
            data_cutoff_local="",
            trade_plan=plan,
        )


def test_buy_decision_requires_a_trade_plan():
    with pytest.raises(ValidationError):
        FundamentalDecision(
            symbol="EURUSD",
            asset_class=AssetClass.FX,
            direction=Direction.BUY,
            conviction=80,
            horizon="1w",
            thesis="buy thesis",
            top_drivers=[],
            catalysts=[],
            entry_condition="x",
            fundamental_invalidation="x",
            risks=[],
            time_stop="Friday",
            data_freshness="FRESH",
            sources=[],
            data_cutoff_utc=datetime.now(UTC),
            data_cutoff_local="",
            trade_plan=None,
        )


def test_conviction_1_10_rounds_and_floors_at_one_when_positive():
    decision = FundamentalDecision(
        symbol="EURUSD",
        asset_class=AssetClass.FX,
        direction=Direction.NO_TRADE,
        conviction=4,
        horizon="N/A",
        thesis="t",
        top_drivers=[],
        catalysts=[],
        entry_condition="N/A",
        fundamental_invalidation="N/A",
        risks=[],
        time_stop="N/A",
        data_freshness="FRESH",
        sources=[],
        data_cutoff_utc=datetime.now(UTC),
        data_cutoff_local="",
        trade_plan=None,
    )
    assert decision.conviction_1_10 == 1


def test_weekly_comparison_requires_exactly_three_candidates():
    decision = FundamentalDecision(
        symbol="NONE",
        asset_class=AssetClass.FX,
        direction=Direction.NO_TRADE,
        conviction=0,
        horizon="N/A",
        thesis="t",
        top_drivers=[],
        catalysts=[],
        entry_condition="N/A",
        fundamental_invalidation="N/A",
        risks=[],
        time_stop="N/A",
        data_freshness="FRESH",
        sources=[],
        data_cutoff_utc=datetime.now(UTC),
        data_cutoff_local="",
        trade_plan=None,
    )
    with pytest.raises(ValidationError):
        WeeklyComparison(
            generated_at=datetime.now(UTC),
            data_cutoff_utc=datetime.now(UTC),
            data_cutoff_local="",
            candidates=[],
            selected_symbol=None,
            decision=decision,
        )


def test_catalyst_event_roundtrip():
    now = datetime.now(UTC)
    event = CatalystEvent(
        symbol_context="US",
        date_utc=now,
        date_local=now,
        country="US",
        indicator="us_cpi_yoy",
        severity=CatalystSeverity.CRITICAL,
    )
    assert event.severity is CatalystSeverity.CRITICAL
