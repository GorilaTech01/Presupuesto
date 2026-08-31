"""The shared opportunity-state engine (V1.1 monitoring spec, section 6):
`evaluate_opportunity` maps an already-computed `DecisionDraft` (the exact
same one `weekly` produces) plus a `FundamentalTriggerEvaluator` result into
FundamentalBias / TradeAction / TriggerStatus. No scoring or decision logic
is re-implemented here -- these tests only exercise the state-mapping.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.enums import (
    CatalystSeverity,
    Direction,
    ExecutionReadiness,
    Freshness,
    FundamentalBias,
    TradeAction,
    TriggerStatus,
)
from app.domain.models import CatalystEvent, TradePlan
from app.fundamental.decision import DecisionDraft
from app.monitor.opportunity_engine import (
    FUNDAMENTAL_BIAS_EPSILON,
    READINESS_BLOCKER_EXECUTION_BLOCKED_SPREAD,
    READINESS_BLOCKER_PRICE_STALE,
    READINESS_BLOCKER_PRICE_UNAVAILABLE,
    READINESS_BLOCKER_RISK_PLAN_INFEASIBLE,
    READINESS_BLOCKER_SYMBOL_UNVERIFIED,
    evaluate_opportunity,
    fundamental_bias_from_score,
    monitoring_interest_threshold,
)
from app.risk.trade_math import TradeMathResult

_NOW = datetime(2026, 9, 1, tzinfo=UTC)
_VALID_UNTIL = _NOW + timedelta(days=3)
MIN_BIAS = 0.6


def _draft(
    *,
    direction: Direction = Direction.SELL,
    trade_action: ExecutionReadiness = ExecutionReadiness.ENTER_NOW,
    catalysts: list[CatalystEvent] | None = None,
    conviction: int = 70,
    reasons: list[str] | None = None,
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
        reasons=reasons or [],
    )


def _catalyst(
    *,
    severity: CatalystSeverity = CatalystSeverity.CRITICAL,
    actual: float | None = None,
    consensus: float | None = 150.0,
    indicator: str = "us_nonfarm_payrolls",
    country: str = "US",
) -> CatalystEvent:
    return CatalystEvent(
        symbol_context="US",
        date_utc=_NOW,
        date_local=_NOW,
        country=country,
        indicator=indicator,
        severity=severity,
        actual=actual,
        consensus=consensus,
    )


_FEASIBLE_MATH = TradeMathResult(
    feasible=True,
    reason=None,
    entry=1.1000,
    stop_loss=1.1050,
    take_profit=1.0900,
    distance_to_sl=0.005,
    distance_to_tp=0.01,
    risk_reward=2.0,
)


def _build_plan(_draft: DecisionDraft, _math: TradeMathResult) -> TradePlan:
    return TradePlan(
        asset="EURUSD",
        symbol="EURUSD",
        direction=_draft.direction,
        conviction_1_10=7,
        horizon="3-5 trading days",
        order_type="manual",
        fundamental_trigger=_draft.entry_condition,
        estimated_entry=_math.entry,
        stop_loss=_math.stop_loss,
        distance_to_sl=_math.distance_to_sl,
        take_profit=_math.take_profit,
        distance_to_tp=_math.distance_to_tp,
        risk_reward=_math.risk_reward,
        time_stop=_draft.time_stop,
        cancellation_condition="n/a",
        fundamental_invalidation=_draft.fundamental_invalidation,
        early_exit_condition="n/a",
        main_catalysts=[],
        main_risks=[],
    )


# --------------------------------------------------------------------------
# fundamental_bias_from_score / monitoring_interest_threshold
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "score,expected",
    [
        (0.5, FundamentalBias.BULLISH),
        (-0.5, FundamentalBias.BEARISH),
        (0.0, FundamentalBias.NEUTRAL),
        (FUNDAMENTAL_BIAS_EPSILON, FundamentalBias.NEUTRAL),
        (-FUNDAMENTAL_BIAS_EPSILON, FundamentalBias.NEUTRAL),
        (FUNDAMENTAL_BIAS_EPSILON + 0.001, FundamentalBias.BULLISH),
    ],
)
def test_fundamental_bias_from_score(score: float, expected: FundamentalBias):
    assert fundamental_bias_from_score(score) is expected


def test_monitoring_interest_threshold_is_half_the_trade_threshold():
    assert monitoring_interest_threshold(0.6) == pytest.approx(0.3)


# --------------------------------------------------------------------------
# 1. Expiration always wins
# --------------------------------------------------------------------------


def test_expiration_wins_even_with_a_strong_confirmed_thesis():
    draft = _draft(direction=Direction.SELL, trade_action=ExecutionReadiness.ENTER_NOW)
    result = evaluate_opportunity(
        draft=draft,
        score=-0.9,
        favored_country="US",
        now=_NOW + timedelta(days=10),  # past valid_until
        valid_until=_VALID_UNTIL,
        min_bias_for_trade=MIN_BIAS,
        trade_math_result=_FEASIBLE_MATH,
        symbol_resolved=True,
        trade_plan_builder=_build_plan,
    )
    assert result.trade_action is TradeAction.CANCELLED
    assert result.trigger_status is TriggerStatus.EXPIRED
    assert result.cancellation_reason == "OPPORTUNITY_EXPIRED"


# --------------------------------------------------------------------------
# 2. A contradicting required catalyst cancels outright
# --------------------------------------------------------------------------


def test_contradicting_catalyst_cancels_the_opportunity():
    contradicting = _catalyst(actual=80.0, consensus=150.0)  # dovish, US favored -> contradicts
    draft = _draft(
        direction=Direction.SELL,
        trade_action=ExecutionReadiness.ENTER_NOW,
        catalysts=[contradicting],
    )
    result = evaluate_opportunity(
        draft=draft,
        score=-0.9,
        favored_country="US",
        now=_NOW,
        valid_until=_VALID_UNTIL,
        min_bias_for_trade=MIN_BIAS,
        trade_math_result=_FEASIBLE_MATH,
        symbol_resolved=True,
        trade_plan_builder=_build_plan,
    )
    assert result.trade_action is TradeAction.CANCELLED
    assert result.trigger_status is TriggerStatus.FAILED
    assert result.cancellation_reason is not None
    assert "contradicted" in result.cancellation_reason


# --------------------------------------------------------------------------
# 3. Decision engine NO_TRADE
# --------------------------------------------------------------------------


def test_no_trade_below_monitoring_interest_is_dropped():
    draft = _draft(direction=Direction.NO_TRADE, trade_action=ExecutionReadiness.NONE)
    result = evaluate_opportunity(
        draft=draft,
        score=0.1,  # well below half of MIN_BIAS (0.3)
        favored_country="US",
        now=_NOW,
        valid_until=_VALID_UNTIL,
        min_bias_for_trade=MIN_BIAS,
        trade_math_result=None,
        symbol_resolved=False,
    )
    assert result.trade_action is TradeAction.NO_TRADE


def test_no_trade_but_interesting_score_is_kept_at_wait():
    draft = _draft(direction=Direction.NO_TRADE, trade_action=ExecutionReadiness.NONE)
    result = evaluate_opportunity(
        draft=draft,
        score=-0.45,  # at/above half of MIN_BIAS (0.3), but below MIN_BIAS itself
        favored_country="US",
        now=_NOW,
        valid_until=_VALID_UNTIL,
        min_bias_for_trade=MIN_BIAS,
        trade_math_result=None,
        symbol_resolved=False,
    )
    assert result.trade_action is TradeAction.WAIT


# --------------------------------------------------------------------------
# 4. PREFER_CONDITIONAL_POST_EVENT
# --------------------------------------------------------------------------


def test_prefer_conditional_post_event_holds_at_wait_while_catalyst_pending():
    pending = _catalyst(actual=None, consensus=150.0)  # required, unresolved
    draft = _draft(
        direction=Direction.SELL,
        trade_action=ExecutionReadiness.ENTER_NOW,  # engine itself would enter
        catalysts=[pending],
    )
    result = evaluate_opportunity(
        draft=draft,
        score=-0.9,
        favored_country="US",
        now=_NOW,
        valid_until=_VALID_UNTIL,
        min_bias_for_trade=MIN_BIAS,
        trade_math_result=_FEASIBLE_MATH,
        symbol_resolved=True,
        trade_plan_builder=_build_plan,
    )
    assert result.trade_action is TradeAction.WAIT
    assert result.trigger_status is TriggerStatus.PENDING
    assert any("PREFER_CONDITIONAL_POST_EVENT" in r for r in result.reasons)


def test_partially_confirmed_catalysts_also_hold_at_wait():
    confirming = _catalyst(
        indicator="us_nonfarm_payrolls",
        severity=CatalystSeverity.CRITICAL,
        actual=200.0,
        consensus=150.0,
    )  # hawkish US surprise confirms a US-favored (quote-strong) SELL thesis
    pending = _catalyst(indicator="us_cpi_yoy", severity=CatalystSeverity.HIGH, actual=None)
    draft = _draft(
        direction=Direction.SELL,
        trade_action=ExecutionReadiness.ENTER_NOW,
        catalysts=[confirming, pending],
    )
    result = evaluate_opportunity(
        draft=draft,
        score=-0.9,
        favored_country="US",
        now=_NOW,
        valid_until=_VALID_UNTIL,
        min_bias_for_trade=MIN_BIAS,
        trade_math_result=_FEASIBLE_MATH,
        symbol_resolved=True,
        trade_plan_builder=_build_plan,
    )
    assert result.trade_action is TradeAction.WAIT
    assert result.trigger_status is TriggerStatus.PARTIALLY_CONFIRMED


# --------------------------------------------------------------------------
# 5. Operational gates: risk plan + symbol + price feed
# --------------------------------------------------------------------------


def test_confirmed_thesis_without_price_feed_stays_at_wait():
    draft = _draft(
        direction=Direction.SELL, trade_action=ExecutionReadiness.ENTER_NOW, catalysts=[]
    )
    result = evaluate_opportunity(
        draft=draft,
        score=-0.9,
        favored_country="US",
        now=_NOW,
        valid_until=_VALID_UNTIL,
        min_bias_for_trade=MIN_BIAS,
        trade_math_result=None,  # no price feed
        symbol_resolved=True,
        trade_plan_builder=_build_plan,
    )
    assert result.trade_action is TradeAction.WAIT
    assert any("no price feed" in r for r in result.reasons)


def test_confirmed_thesis_with_infeasible_trade_math_stays_at_wait():
    draft = _draft(
        direction=Direction.SELL, trade_action=ExecutionReadiness.ENTER_NOW, catalysts=[]
    )
    infeasible = TradeMathResult(feasible=False, reason="spread too wide")
    result = evaluate_opportunity(
        draft=draft,
        score=-0.9,
        favored_country="US",
        now=_NOW,
        valid_until=_VALID_UNTIL,
        min_bias_for_trade=MIN_BIAS,
        trade_math_result=infeasible,
        symbol_resolved=True,
        trade_plan_builder=_build_plan,
    )
    assert result.trade_action is TradeAction.WAIT
    assert any("infeasible" in r for r in result.reasons)


def test_confirmed_thesis_with_unresolved_symbol_stays_at_wait():
    draft = _draft(
        direction=Direction.SELL, trade_action=ExecutionReadiness.ENTER_NOW, catalysts=[]
    )
    result = evaluate_opportunity(
        draft=draft,
        score=-0.9,
        favored_country="US",
        now=_NOW,
        valid_until=_VALID_UNTIL,
        min_bias_for_trade=MIN_BIAS,
        trade_math_result=_FEASIBLE_MATH,
        symbol_resolved=False,
        trade_plan_builder=_build_plan,
    )
    assert result.trade_action is TradeAction.WAIT
    assert any("symbol not verifiable" in r for r in result.reasons)


def test_no_trade_plan_builder_stays_at_wait():
    draft = _draft(
        direction=Direction.SELL, trade_action=ExecutionReadiness.ENTER_NOW, catalysts=[]
    )
    result = evaluate_opportunity(
        draft=draft,
        score=-0.9,
        favored_country="US",
        now=_NOW,
        valid_until=_VALID_UNTIL,
        min_bias_for_trade=MIN_BIAS,
        trade_math_result=_FEASIBLE_MATH,
        symbol_resolved=True,
        trade_plan_builder=None,
    )
    assert result.trade_action is TradeAction.WAIT


# --------------------------------------------------------------------------
# Full green path: READY_TO_TRADE
# --------------------------------------------------------------------------


def test_all_criteria_met_produces_ready_to_trade_with_trade_plan():
    draft = _draft(
        direction=Direction.SELL, trade_action=ExecutionReadiness.ENTER_NOW, catalysts=[]
    )
    result = evaluate_opportunity(
        draft=draft,
        score=-0.9,
        favored_country="US",
        now=_NOW,
        valid_until=_VALID_UNTIL,
        min_bias_for_trade=MIN_BIAS,
        trade_math_result=_FEASIBLE_MATH,
        symbol_resolved=True,
        trade_plan_builder=_build_plan,
    )
    assert result.trade_action is TradeAction.READY_TO_TRADE
    assert result.trade_plan is not None
    assert result.trade_plan.direction is Direction.SELL
    assert result.readiness_reason is not None
    assert result.fundamental_bias is FundamentalBias.BEARISH


def test_ready_to_trade_preserves_conviction_and_breakdown_from_draft():
    from app.domain.models import ConvictionBreakdown

    breakdown = ConvictionBreakdown(
        raw_score=0.9,
        normalized_score=18.0,
        data_completeness="ok",
        source_quality="ok",
        contradiction_penalty=0,
        event_risk_penalty=0,
        missing_data_penalty=0,
        source_quality_penalty=0,
        expectations_penalty=8,
        final_conviction=68,
    )
    draft = DecisionDraft(
        symbol="EURUSD",
        direction=Direction.SELL,
        trade_action=ExecutionReadiness.ENTER_NOW,
        conviction=68,
        thesis="t",
        top_drivers=[],
        catalysts=[],
        entry_condition="e",
        fundamental_invalidation="i",
        risks=[],
        time_stop="Friday close",
        data_freshness=Freshness.FRESH,
        sources=["TESTSRC"],
        conviction_breakdown=breakdown,
    )
    result = evaluate_opportunity(
        draft=draft,
        score=-0.9,
        favored_country="US",
        now=_NOW,
        valid_until=_VALID_UNTIL,
        min_bias_for_trade=MIN_BIAS,
        trade_math_result=_FEASIBLE_MATH,
        symbol_resolved=True,
        trade_plan_builder=_build_plan,
    )
    assert result.trade_action is TradeAction.READY_TO_TRADE
    # conviction and its full breakdown -- including the never-removed
    # EXPECTATIONS_INCOMPLETE_PENALTY -- must never be inflated by the
    # monitoring layer just because a catalyst resolved.
    assert result.conviction == 68
    assert result.conviction_breakdown is breakdown
    assert result.conviction_breakdown.expectations_penalty == 8


# --------------------------------------------------------------------------
# V1.1.1: fundamental_setup_ready / readiness_blocker
# --------------------------------------------------------------------------


def test_fundamentally_pending_states_are_not_setup_ready():
    """WAIT states caused by fundamentals/catalysts (not price/symbol/risk)
    must not claim fundamental_setup_ready -- that flag is specifically for
    'fundamentals cleared, only an operational input is missing'."""
    pending = _catalyst(actual=None)
    draft = _draft(
        direction=Direction.SELL, trade_action=ExecutionReadiness.ENTER_NOW, catalysts=[pending]
    )
    result = evaluate_opportunity(
        draft=draft,
        score=-0.9,
        favored_country="US",
        now=_NOW,
        valid_until=_VALID_UNTIL,
        min_bias_for_trade=MIN_BIAS,
        trade_math_result=_FEASIBLE_MATH,
        symbol_resolved=True,
        trade_plan_builder=_build_plan,
    )
    assert result.trade_action is TradeAction.WAIT
    assert result.fundamental_setup_ready is False
    assert result.readiness_blocker is None


def test_no_price_feed_sets_price_unavailable_blocker_by_default():
    draft = _draft(
        direction=Direction.SELL, trade_action=ExecutionReadiness.ENTER_NOW, catalysts=[]
    )
    result = evaluate_opportunity(
        draft=draft,
        score=-0.9,
        favored_country="US",
        now=_NOW,
        valid_until=_VALID_UNTIL,
        min_bias_for_trade=MIN_BIAS,
        trade_math_result=None,
        symbol_resolved=True,
        trade_plan_builder=_build_plan,
    )
    assert result.trade_action is TradeAction.WAIT
    assert result.fundamental_setup_ready is True
    assert result.readiness_blocker == READINESS_BLOCKER_PRICE_UNAVAILABLE


def test_caller_supplied_price_blocker_overrides_generic_default():
    draft = _draft(
        direction=Direction.SELL, trade_action=ExecutionReadiness.ENTER_NOW, catalysts=[]
    )
    result = evaluate_opportunity(
        draft=draft,
        score=-0.9,
        favored_country="US",
        now=_NOW,
        valid_until=_VALID_UNTIL,
        min_bias_for_trade=MIN_BIAS,
        trade_math_result=None,
        symbol_resolved=True,
        trade_plan_builder=_build_plan,
        price_blocker=READINESS_BLOCKER_PRICE_STALE,
    )
    assert result.readiness_blocker == READINESS_BLOCKER_PRICE_STALE


def test_unresolved_symbol_blocker_takes_priority_over_missing_price():
    draft = _draft(
        direction=Direction.SELL, trade_action=ExecutionReadiness.ENTER_NOW, catalysts=[]
    )
    result = evaluate_opportunity(
        draft=draft,
        score=-0.9,
        favored_country="US",
        now=_NOW,
        valid_until=_VALID_UNTIL,
        min_bias_for_trade=MIN_BIAS,
        trade_math_result=None,
        symbol_resolved=False,
        trade_plan_builder=_build_plan,
        price_blocker=READINESS_BLOCKER_PRICE_STALE,
    )
    assert result.readiness_blocker == READINESS_BLOCKER_SYMBOL_UNVERIFIED


def test_spread_infeasibility_sets_execution_blocked_spread():
    draft = _draft(
        direction=Direction.SELL, trade_action=ExecutionReadiness.ENTER_NOW, catalysts=[]
    )
    infeasible = TradeMathResult(
        feasible=False,
        reason="spread (0.00500) is too wide relative to the computed stop distance",
    )
    result = evaluate_opportunity(
        draft=draft,
        score=-0.9,
        favored_country="US",
        now=_NOW,
        valid_until=_VALID_UNTIL,
        min_bias_for_trade=MIN_BIAS,
        trade_math_result=infeasible,
        symbol_resolved=True,
        trade_plan_builder=_build_plan,
    )
    assert result.readiness_blocker == READINESS_BLOCKER_EXECUTION_BLOCKED_SPREAD


def test_non_spread_infeasibility_sets_generic_risk_plan_blocker():
    draft = _draft(
        direction=Direction.SELL, trade_action=ExecutionReadiness.ENTER_NOW, catalysts=[]
    )
    infeasible = TradeMathResult(feasible=False, reason="risk/reward 1.20 below minimum 1.5")
    result = evaluate_opportunity(
        draft=draft,
        score=-0.9,
        favored_country="US",
        now=_NOW,
        valid_until=_VALID_UNTIL,
        min_bias_for_trade=MIN_BIAS,
        trade_math_result=infeasible,
        symbol_resolved=True,
        trade_plan_builder=_build_plan,
    )
    assert result.readiness_blocker == READINESS_BLOCKER_RISK_PLAN_INFEASIBLE


def test_ready_to_trade_has_no_readiness_blocker():
    draft = _draft(
        direction=Direction.SELL, trade_action=ExecutionReadiness.ENTER_NOW, catalysts=[]
    )
    result = evaluate_opportunity(
        draft=draft,
        score=-0.9,
        favored_country="US",
        now=_NOW,
        valid_until=_VALID_UNTIL,
        min_bias_for_trade=MIN_BIAS,
        trade_math_result=_FEASIBLE_MATH,
        symbol_resolved=True,
        trade_plan_builder=_build_plan,
    )
    assert result.trade_action is TradeAction.READY_TO_TRADE
    assert result.fundamental_setup_ready is True
    assert result.readiness_blocker is None


def test_price_becoming_available_flips_wait_to_ready_with_no_fundamental_change():
    """The exact scenario from the V1.1.1 spec: same fundamentals, only a
    price feed appears -- trade_action must flip to READY_TO_TRADE without
    any fundamental input changing."""
    draft = _draft(
        direction=Direction.SELL, trade_action=ExecutionReadiness.ENTER_NOW, catalysts=[]
    )
    common_kwargs = dict(
        draft=draft,
        score=-0.9,
        favored_country="US",
        now=_NOW,
        valid_until=_VALID_UNTIL,
        min_bias_for_trade=MIN_BIAS,
        symbol_resolved=True,
        trade_plan_builder=_build_plan,
    )
    before = evaluate_opportunity(trade_math_result=None, **common_kwargs)
    after = evaluate_opportunity(trade_math_result=_FEASIBLE_MATH, **common_kwargs)

    assert before.trade_action is TradeAction.WAIT
    assert after.trade_action is TradeAction.READY_TO_TRADE
    assert before.fundamental_bias == after.fundamental_bias


# --------------------------------------------------------------------------
# V1.1.1: price can never act as a directional signal
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "other_math",
    [
        TradeMathResult(
            feasible=True,
            reason=None,
            entry=1.5000,
            stop_loss=1.4000,
            take_profit=1.7000,
            distance_to_sl=0.1,
            distance_to_tp=0.2,
            risk_reward=2.0,
        ),
        TradeMathResult(
            feasible=True,
            reason=None,
            entry=0.9000,
            stop_loss=0.9500,
            take_profit=0.8000,
            distance_to_sl=0.05,
            distance_to_tp=0.1,
            risk_reward=2.0,
        ),
        None,
    ],
)
def test_changing_price_or_spread_never_flips_fundamental_bias(other_math):
    """BULLISH/BEARISH must come only from the fundamental score -- varying
    entry/stop/spread (or removing the price feed entirely) must never
    change fundamental_bias, only operational trade_action."""
    draft = _draft(
        direction=Direction.SELL, trade_action=ExecutionReadiness.ENTER_NOW, catalysts=[]
    )
    baseline = evaluate_opportunity(
        draft=draft,
        score=-0.9,
        favored_country="US",
        now=_NOW,
        valid_until=_VALID_UNTIL,
        min_bias_for_trade=MIN_BIAS,
        trade_math_result=_FEASIBLE_MATH,
        symbol_resolved=True,
        trade_plan_builder=_build_plan,
    )
    varied = evaluate_opportunity(
        draft=draft,
        score=-0.9,
        favored_country="US",
        now=_NOW,
        valid_until=_VALID_UNTIL,
        min_bias_for_trade=MIN_BIAS,
        trade_math_result=other_math,
        symbol_resolved=True,
        trade_plan_builder=_build_plan,
    )
    assert baseline.fundamental_bias == varied.fundamental_bias == FundamentalBias.BEARISH
    assert baseline.conviction == varied.conviction
    assert baseline.conviction_breakdown == varied.conviction_breakdown
