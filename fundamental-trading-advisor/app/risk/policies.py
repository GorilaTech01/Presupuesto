"""Named risk/exit policies (audit section 6, docs/decision_audit_eurusd_2026-08-31.md).

The audit asked for PRICE STOP to be conceptually separated from
FUNDAMENTAL INVALIDATION: a thesis can be wrong (and worth exiting) well
before -- or after -- price ever reaches the numeric stop-loss level. This
module doesn't change any numbers computed elsewhere (SL/TP math stays in
`app.risk.trade_math`; the invalidation rule text stays in
`app.fundamental.decision`) -- it names the three independent exit
mechanisms explicitly and gives each one its own typed object, so "what
closes this trade" is never just one undifferentiated "stop":

  PriceStopPolicy               a price level. Deterministic: a
                                 preconfigured percent-of-price band times
                                 an instrument-class multiplier, widened
                                 around CRITICAL catalysts, sized to a
                                 minimum 1.5 R:R. See `app.risk.trade_math`.
                                 No technical analysis (no ATR, no support/
                                 resistance) feeds this number.

  FundamentalInvalidationPolicy a RULE, not a price: exit if the
                                 underlying fundamental differential/score
                                 that justified the trade reverses sign, or
                                 a named catalyst outcome contradicts it --
                                 regardless of where price currently is.

  TimeStopPolicy                a calendar rule: close/reassess by a fixed
                                 point in time regardless of price or
                                 fundamentals.

Any one of these can fire independently, in any order, before the others.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import FundamentalDecision


@dataclass(frozen=True)
class PriceStopPolicy:
    stop_loss: float
    take_profit: float
    risk_reward: float
    method: str = (
        "percent-of-price band by instrument class, widened for CRITICAL "
        "event risk, sized to >= 1.5 R:R -- see app.risk.trade_math.build_trade_math"
    )


@dataclass(frozen=True)
class FundamentalInvalidationPolicy:
    rule: str
    trigger_category: str = "fundamental_score_sign_flip_or_named_catalyst_outcome"


@dataclass(frozen=True)
class TimeStopPolicy:
    deadline_description: str


def extract_policies(
    decision: FundamentalDecision,
) -> tuple[PriceStopPolicy | None, FundamentalInvalidationPolicy, TimeStopPolicy]:
    """Pulls the three policies out of an already-built FundamentalDecision
    for display/audit purposes. `PriceStopPolicy` is None for a NO_TRADE
    decision (there is no price plan) or for a WAIT_FOR_TRIGGER trade_action
    with no trade_plan attached; the other two policies always exist,
    because "when do I stop waiting" and "what proves this thesis wrong"
    are meaningful even before a price plan exists.
    """
    price_stop = None
    if decision.trade_plan is not None:
        price_stop = PriceStopPolicy(
            stop_loss=decision.trade_plan.stop_loss or 0.0,
            take_profit=decision.trade_plan.take_profit or 0.0,
            risk_reward=decision.trade_plan.risk_reward or 0.0,
        )
    invalidation = FundamentalInvalidationPolicy(rule=decision.fundamental_invalidation)
    time_stop = TimeStopPolicy(deadline_description=decision.time_stop)
    return price_stop, invalidation, time_stop
