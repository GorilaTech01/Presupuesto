"""MonitoredTradeOpportunity's own validators (spec section 1): a
READY_TO_TRADE opportunity must carry a trade_plan, a CANCELLED one must
carry a cancellation_reason, and no other state may carry a trade_plan.
These invariants matter because `fundamental_bias` and `trade_action` are
deliberately independent fields -- the model itself must not allow them to
drift into an inconsistent combination.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.domain.enums import Direction, FundamentalBias, TradeAction, TriggerStatus
from app.domain.models import MonitoredTradeOpportunity, TradePlan

_NOW = datetime(2026, 9, 1, tzinfo=UTC)


def _base_fields(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = dict(
        opportunity_id="abc",
        recommendation_id="rec-abc",
        created_at=_NOW,
        updated_at=_NOW,
        asset="EURUSD",
        symbol="EURUSD",
        fundamental_bias=FundamentalBias.BEARISH,
        trade_action=TradeAction.WAIT,
        direction=Direction.SELL,
        conviction=60,
        original_score=-0.7,
        current_score=-0.7,
        threshold=0.6,
        horizon="3-5 days",
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
    )
    fields.update(overrides)
    return fields


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


def test_wait_state_is_valid_without_trade_plan():
    opp = MonitoredTradeOpportunity(**_base_fields(trade_action=TradeAction.WAIT))
    assert opp.trade_plan is None


def test_ready_to_trade_requires_trade_plan():
    with pytest.raises(ValidationError):
        MonitoredTradeOpportunity(
            **_base_fields(trade_action=TradeAction.READY_TO_TRADE, trade_plan=None)
        )


def test_ready_to_trade_with_trade_plan_is_valid():
    opp = MonitoredTradeOpportunity(
        **_base_fields(trade_action=TradeAction.READY_TO_TRADE, trade_plan=_plan())
    )
    assert opp.trade_plan is not None


def test_cancelled_requires_cancellation_reason():
    with pytest.raises(ValidationError):
        MonitoredTradeOpportunity(
            **_base_fields(trade_action=TradeAction.CANCELLED, cancellation_reason=None)
        )


def test_cancelled_with_reason_is_valid():
    opp = MonitoredTradeOpportunity(
        **_base_fields(
            trade_action=TradeAction.CANCELLED, cancellation_reason="OPPORTUNITY_EXPIRED"
        )
    )
    assert opp.cancellation_reason == "OPPORTUNITY_EXPIRED"


def test_non_ready_state_cannot_carry_a_trade_plan():
    with pytest.raises(ValidationError):
        MonitoredTradeOpportunity(**_base_fields(trade_action=TradeAction.WAIT, trade_plan=_plan()))


def test_bearish_bias_can_sit_at_wait_indefinitely():
    """The core V1.1 architectural distinction: bias and action are
    orthogonal. A BEARISH bias does not force any particular trade_action."""
    opp = MonitoredTradeOpportunity(
        **_base_fields(fundamental_bias=FundamentalBias.BEARISH, trade_action=TradeAction.WAIT)
    )
    assert opp.fundamental_bias is FundamentalBias.BEARISH
    assert opp.trade_action is TradeAction.WAIT
