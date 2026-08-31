from __future__ import annotations

from datetime import UTC, datetime

from app.domain.enums import AssetClass, Direction, ExecutionReadiness
from app.domain.models import FundamentalDecision, TradePlan
from app.risk.policies import (
    FundamentalInvalidationPolicy,
    PriceStopPolicy,
    TimeStopPolicy,
    extract_policies,
)


def _buy_decision(*, invalidation: str, time_stop: str) -> FundamentalDecision:
    plan = TradePlan(
        asset="EURUSD",
        symbol="EURUSD",
        direction=Direction.BUY,
        conviction_1_10=6,
        horizon="1w",
        order_type="market",
        fundamental_trigger="x",
        estimated_entry=1.10,
        stop_loss=1.094,
        distance_to_sl=0.006,
        take_profit=1.112,
        distance_to_tp=0.012,
        risk_reward=2.0,
        time_stop=time_stop,
        cancellation_condition="x",
        fundamental_invalidation=invalidation,
        early_exit_condition="x",
        main_catalysts=[],
        main_risks=[],
    )
    return FundamentalDecision(
        symbol="EURUSD",
        asset_class=AssetClass.FX,
        direction=Direction.BUY,
        trade_action=ExecutionReadiness.ENTER_NOW,
        conviction=70,
        horizon="1w",
        thesis="t",
        top_drivers=[],
        catalysts=[],
        entry_condition="x",
        fundamental_invalidation=invalidation,
        risks=[],
        time_stop=time_stop,
        data_freshness="FRESH",
        sources=[],
        data_cutoff_utc=datetime.now(UTC),
        data_cutoff_local="",
        trade_plan=plan,
    )


def test_price_stop_and_fundamental_invalidation_are_independently_settable():
    """A thesis can be invalidated without price ever touching the stop --
    these must be two separate objects, not one conflated 'stop'."""
    decision = _buy_decision(
        invalidation="Thesis invalidated if EUR fundamentals weaken vs USD.",
        time_stop="Close by Friday regardless of P&L.",
    )
    price_stop, invalidation, time_stop = extract_policies(decision)

    assert isinstance(price_stop, PriceStopPolicy)
    assert isinstance(invalidation, FundamentalInvalidationPolicy)
    assert isinstance(time_stop, TimeStopPolicy)

    # Changing the price stop's numbers has zero effect on the invalidation
    # rule's text, and vice versa -- they are stored on different fields
    # with no shared derivation.
    assert price_stop.stop_loss == 1.094
    assert "EUR fundamentals" in invalidation.rule
    assert "stop_loss" not in invalidation.rule
    assert "Friday" in time_stop.deadline_description


def test_no_trade_decision_has_no_price_stop_but_still_has_the_other_two():
    decision = FundamentalDecision(
        symbol="EURUSD",
        asset_class=AssetClass.FX,
        direction=Direction.NO_TRADE,
        trade_action=ExecutionReadiness.NONE,
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
    price_stop, invalidation, time_stop = extract_policies(decision)
    assert price_stop is None
    assert isinstance(invalidation, FundamentalInvalidationPolicy)
    assert isinstance(time_stop, TimeStopPolicy)
