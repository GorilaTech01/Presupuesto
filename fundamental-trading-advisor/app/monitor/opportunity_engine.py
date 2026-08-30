"""The single, shared state-evaluation function for monitored opportunities
(V1.1 monitoring spec, sections 4 and 28: "No duplicar scoring ni decision
engine").

This module does NOT recompute scores or decisions. It calls the existing,
audited `FundamentalDecisionEngine` (the exact same one `weekly` uses) to
get a `DecisionDraft`, runs the new `FundamentalTriggerEvaluator` over the
same catalysts, and maps the result into the monitoring-layer's
`FundamentalBias` / `TradeAction` / `TriggerStatus` vocabulary. Both
`WeeklyPipeline` (when it creates a `MonitoredTradeOpportunity`) and
`TradeOpportunityMonitorService` (when it re-evaluates one) call this same
function on freshly normalized facts -- so the same normalized information
always produces the same result, regardless of which caller it came from.

PREFER_CONDITIONAL_POST_EVENT (section 7): even once a score crosses the
trade threshold, a pending HIGH or CRITICAL catalyst keeps the opportunity
at WAIT rather than READY_TO_TRADE, unless it has already been confirmed by
`FundamentalTriggerEvaluator`. This is a stricter gate than the underlying
decision engine's own `ExecutionReadiness` (which only blocks on CRITICAL,
not HIGH) -- a deliberate, disclosed strengthening for the monitoring
layer, not a contradiction of it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from app.domain.enums import (
    Direction,
    ExecutionReadiness,
    FundamentalBias,
    TradeAction,
    TriggerStatus,
)
from app.domain.models import ConvictionBreakdown, TradePlan
from app.fundamental.decision import DecisionDraft
from app.monitor.trigger_evaluator import FundamentalTriggerEvaluator
from app.risk.trade_math import TradeMathResult

TradePlanBuilder = Callable[[DecisionDraft, TradeMathResult], "TradePlan | None"]

PREFER_CONDITIONAL_POST_EVENT = True

# A candidate whose |score| falls below the full trade threshold but at or
# above this fraction of it is still "worth watching" -- created as a
# monitored opportunity at WAIT rather than discarded as NO_TRADE. Fixed at
# half the trade threshold; not tuned per-run.
MONITORING_INTEREST_RATIO = 0.5

FUNDAMENTAL_BIAS_EPSILON = 0.05


def monitoring_interest_threshold(min_bias_for_trade: float) -> float:
    return min_bias_for_trade * MONITORING_INTEREST_RATIO


def fundamental_bias_from_score(
    score: float, epsilon: float = FUNDAMENTAL_BIAS_EPSILON
) -> FundamentalBias:
    if score > epsilon:
        return FundamentalBias.BULLISH
    if score < -epsilon:
        return FundamentalBias.BEARISH
    return FundamentalBias.NEUTRAL


@dataclass
class OpportunityEvaluation:
    fundamental_bias: FundamentalBias
    trade_action: TradeAction
    trigger_status: TriggerStatus
    conviction: int
    conviction_breakdown: ConvictionBreakdown | None
    readiness_reason: str | None
    cancellation_reason: str | None
    reasons: list[str] = field(default_factory=list)
    trade_plan: TradePlan | None = None


def evaluate_opportunity(
    *,
    draft: DecisionDraft,
    score: float,
    favored_country: str,
    now: datetime,
    valid_until: datetime,
    min_bias_for_trade: float,
    trade_math_result: TradeMathResult | None,
    symbol_resolved: bool,
    trade_plan_builder: TradePlanBuilder | None = None,
) -> OpportunityEvaluation:
    """Evaluates the 12 READY_TO_TRADE criteria (spec section 6) against an
    already-computed `DecisionDraft`. `trade_plan_builder`, if given, is
    called only when every other criterion is satisfied, to build the
    `TradePlan` that a READY_TO_TRADE opportunity must carry -- kept as a
    callback so this module never needs to import price/broker plumbing
    directly.
    """
    bias = fundamental_bias_from_score(score)
    trigger_eval = FundamentalTriggerEvaluator().evaluate(draft.catalysts, favored_country)

    # 1. Expiration always wins, regardless of how strong the thesis looks.
    if now > valid_until:
        return OpportunityEvaluation(
            fundamental_bias=bias,
            trade_action=TradeAction.CANCELLED,
            trigger_status=TriggerStatus.EXPIRED,
            conviction=draft.conviction,
            conviction_breakdown=draft.conviction_breakdown,
            readiness_reason=None,
            cancellation_reason="OPPORTUNITY_EXPIRED",
            reasons=[f"valid_until ({valid_until.isoformat()}) has passed"],
        )

    # 2. A required catalyst outcome contradicting the thesis cancels it
    # outright -- this is a fundamental invalidation, not a data gap.
    if trigger_eval.status is TriggerStatus.FAILED:
        return OpportunityEvaluation(
            fundamental_bias=bias,
            trade_action=TradeAction.CANCELLED,
            trigger_status=TriggerStatus.FAILED,
            conviction=draft.conviction,
            conviction_breakdown=draft.conviction_breakdown,
            readiness_reason=None,
            cancellation_reason=(
                "fundamental catalyst contradicted the thesis: " + "; ".join(trigger_eval.reasons)
            ),
            reasons=trigger_eval.reasons,
        )

    # 3. Decision engine says NO_TRADE (stale data, insufficient evidence,
    # asymmetry too weak, or an unresolved CRITICAL catalyst with
    # CONSENSUS_UNAVAILABLE). Downgrade to WAIT only if the score is still
    # "interesting"; otherwise this candidate isn't worth monitoring.
    if draft.direction is Direction.NO_TRADE:
        interesting = abs(score) >= monitoring_interest_threshold(min_bias_for_trade)
        action = TradeAction.WAIT if interesting else TradeAction.NO_TRADE
        return OpportunityEvaluation(
            fundamental_bias=bias,
            trade_action=action,
            trigger_status=trigger_eval.status,
            conviction=draft.conviction,
            conviction_breakdown=draft.conviction_breakdown,
            readiness_reason=None,
            cancellation_reason=None,
            reasons=list(draft.reasons) + trigger_eval.reasons,
        )

    # 4. Decision engine already produced BUY/SELL. PREFER_CONDITIONAL_POST_EVENT:
    # stay at WAIT while a HIGH/CRITICAL catalyst this thesis depends on is
    # still pending or only partially confirmed, even if the engine itself
    # would otherwise treat it as immediately executable.
    if PREFER_CONDITIONAL_POST_EVENT and trigger_eval.status in (
        TriggerStatus.PENDING,
        TriggerStatus.PARTIALLY_CONFIRMED,
    ):
        return OpportunityEvaluation(
            fundamental_bias=bias,
            trade_action=TradeAction.WAIT,
            trigger_status=trigger_eval.status,
            conviction=draft.conviction,
            conviction_breakdown=draft.conviction_breakdown,
            readiness_reason=None,
            cancellation_reason=None,
            reasons=["PREFER_CONDITIONAL_POST_EVENT: waiting for catalyst confirmation"]
            + trigger_eval.reasons,
        )

    if draft.trade_action is ExecutionReadiness.WAIT_FOR_TRIGGER:
        return OpportunityEvaluation(
            fundamental_bias=bias,
            trade_action=TradeAction.WAIT,
            trigger_status=trigger_eval.status,
            conviction=draft.conviction,
            conviction_breakdown=draft.conviction_breakdown,
            readiness_reason=None,
            cancellation_reason=None,
            reasons=["waiting for pending CRITICAL catalyst"] + trigger_eval.reasons,
        )

    # 5. Everything fundamental checks out (score, conviction, freshness,
    # catalysts all confirmed). The remaining gates are operational: a
    # valid risk plan, a resolvable broker symbol, and a live price feed.
    if trade_math_result is None or not trade_math_result.feasible or not symbol_resolved:
        blocking = []
        if not symbol_resolved:
            blocking.append("symbol not verifiable for this broker")
        if trade_math_result is None:
            blocking.append("no price feed available to build a risk plan")
        elif not trade_math_result.feasible:
            blocking.append(f"trade math infeasible: {trade_math_result.reason}")
        return OpportunityEvaluation(
            fundamental_bias=bias,
            trade_action=TradeAction.WAIT,
            trigger_status=trigger_eval.status,
            conviction=draft.conviction,
            conviction_breakdown=draft.conviction_breakdown,
            readiness_reason=None,
            cancellation_reason=None,
            reasons=blocking + trigger_eval.reasons,
        )

    trade_plan = trade_plan_builder(draft, trade_math_result) if trade_plan_builder else None
    if trade_plan is None:
        return OpportunityEvaluation(
            fundamental_bias=bias,
            trade_action=TradeAction.WAIT,
            trigger_status=trigger_eval.status,
            conviction=draft.conviction,
            conviction_breakdown=draft.conviction_breakdown,
            readiness_reason=None,
            cancellation_reason=None,
            reasons=["no trade plan builder available"] + trigger_eval.reasons,
        )

    return OpportunityEvaluation(
        fundamental_bias=bias,
        trade_action=TradeAction.READY_TO_TRADE,
        trigger_status=trigger_eval.status,
        conviction=draft.conviction,
        conviction_breakdown=draft.conviction_breakdown,
        readiness_reason=(
            "score crosses threshold; conviction floor met; data fresh; required catalysts "
            "confirmed; within horizon; symbol verified; risk plan meets minimum R:R"
        ),
        cancellation_reason=None,
        reasons=trigger_eval.reasons,
        trade_plan=trade_plan,
    )
