"""OpportunityFingerprint + find_reusable_opportunity (duplicate-opportunity
fix). Pure, deterministic identity matching -- asset/direction/horizon
only, never price. See app/monitor/identity.py for the full rationale.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.domain.enums import Direction, FundamentalBias, TradeAction, TriggerStatus
from app.domain.models import MonitoredTradeOpportunity, TradePlan
from app.monitor.identity import OpportunityFingerprint, find_reusable_opportunity

_NOW = datetime(2026, 9, 1, tzinfo=UTC)
_HORIZON = "Close/reassess by Friday market close of the analysis week regardless of P&L."


def _plan(direction: Direction) -> TradePlan:
    return TradePlan(
        asset="EURUSD",
        symbol="EURUSD",
        direction=direction,
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
    opportunity_id: str = "abc",
    asset: str = "EURUSD",
    direction: Direction = Direction.SELL,
    horizon: str = _HORIZON,
    trade_action: TradeAction = TradeAction.WAIT,
) -> MonitoredTradeOpportunity:
    return MonitoredTradeOpportunity(
        opportunity_id=opportunity_id,
        recommendation_id=f"rec-{opportunity_id}",
        created_at=_NOW,
        updated_at=_NOW,
        asset=asset,
        symbol=asset,
        fundamental_bias=FundamentalBias.BEARISH,
        trade_action=trade_action,
        direction=direction,
        conviction=60,
        original_score=-0.7,
        current_score=-0.7,
        threshold=0.6,
        horizon=horizon,
        entry_condition="wait for confirmation",
        catalysts=[],
        fundamental_invalidation="n/a",
        cancellation_conditions=[],
        time_stop=horizon,
        valid_until=_NOW + timedelta(days=3),
        data_cutoff=_NOW,
        last_evaluated_at=_NOW,
        next_relevant_event=None,
        trigger_status=TriggerStatus.PENDING,
        cancellation_reason="USER_SKIPPED" if trade_action is TradeAction.CANCELLED else None,
        trade_plan=_plan(direction) if trade_action is TradeAction.READY_TO_TRADE else None,
    )


def test_fingerprint_equality_ignores_nothing_but_asset_direction_horizon():
    a = OpportunityFingerprint(asset="EURUSD", direction=Direction.SELL, horizon=_HORIZON)
    b = OpportunityFingerprint(asset="EURUSD", direction=Direction.SELL, horizon=_HORIZON)
    assert a == b


def test_find_reusable_opportunity_matches_wait_state():
    opp = _opportunity(trade_action=TradeAction.WAIT)
    fingerprint = OpportunityFingerprint.for_opportunity(opp)
    found = find_reusable_opportunity([opp], fingerprint)
    assert found is opp


def test_find_reusable_opportunity_matches_ready_to_trade_state():
    opp = _opportunity(trade_action=TradeAction.READY_TO_TRADE)
    fingerprint = OpportunityFingerprint.for_opportunity(opp)
    found = find_reusable_opportunity([opp], fingerprint)
    assert found is opp


def test_find_reusable_opportunity_excludes_cancelled():
    opp = _opportunity(trade_action=TradeAction.CANCELLED)
    fingerprint = OpportunityFingerprint.for_opportunity(opp)
    assert find_reusable_opportunity([opp], fingerprint) is None


def test_find_reusable_opportunity_excludes_different_direction():
    opp = _opportunity(direction=Direction.SELL, trade_action=TradeAction.WAIT)
    fingerprint = OpportunityFingerprint(asset="EURUSD", direction=Direction.BUY, horizon=_HORIZON)
    assert find_reusable_opportunity([opp], fingerprint) is None


def test_find_reusable_opportunity_excludes_different_horizon():
    opp = _opportunity(horizon=_HORIZON, trade_action=TradeAction.WAIT)
    fingerprint = OpportunityFingerprint(
        asset="EURUSD", direction=Direction.SELL, horizon="A different, shorter horizon."
    )
    assert find_reusable_opportunity([opp], fingerprint) is None


def test_find_reusable_opportunity_excludes_different_asset():
    opp = _opportunity(asset="EURUSD", trade_action=TradeAction.WAIT)
    fingerprint = OpportunityFingerprint(asset="XAUUSD", direction=Direction.SELL, horizon=_HORIZON)
    assert find_reusable_opportunity([opp], fingerprint) is None


def test_find_reusable_opportunity_returns_none_for_empty_list():
    fingerprint = OpportunityFingerprint(asset="EURUSD", direction=Direction.SELL, horizon=_HORIZON)
    assert find_reusable_opportunity([], fingerprint) is None


def test_find_reusable_opportunity_picks_the_matching_one_among_several():
    other_asset = _opportunity(opportunity_id="other-asset", asset="XAUUSD")
    other_direction = _opportunity(opportunity_id="other-dir", direction=Direction.BUY)
    cancelled = _opportunity(opportunity_id="cancelled", trade_action=TradeAction.CANCELLED)
    match = _opportunity(opportunity_id="match", trade_action=TradeAction.WAIT)
    fingerprint = OpportunityFingerprint.for_opportunity(match)
    found = find_reusable_opportunity([other_asset, other_direction, cancelled, match], fingerprint)
    assert found is match
