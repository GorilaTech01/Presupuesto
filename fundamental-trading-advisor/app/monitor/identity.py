"""OpportunityFingerprint: deterministic, price-independent identity used
to decide whether a freshly-evaluated candidate continues an existing
`MonitoredTradeOpportunity` or starts a new one (spec: avoid duplicate
opportunities for the same active thesis).

Fields are exclusively fundamental/thesis metadata:

- `asset`     -- the symbol (e.g. "EURUSD").
- `direction` -- BUY or SELL. A bias flip is a different thesis by
  definition, so it can never match an opposite-direction opportunity.
- `horizon`   -- the thesis's time_stop text (e.g. "Close/reassess by
  Friday market close..."). A materially different horizon is treated as
  a different thesis.

Current bid/ask/spread/entry price are deliberately EXCLUDED from the
fingerprint: per the V1.1.1 no-directional-price-signal guarantee, price
must never make an otherwise-unchanged thesis look like a new opportunity
(see `test_changing_price_or_spread_never_flips_fundamental_bias` and this
module's own `test_price_only_change_does_not_create_new_opportunity`).

A material break in the underlying catalyst framework or invalidation
structure is NOT diffed here directly -- it already surfaces through the
existing, unmodified state machine as a CANCELLED transition
(`FundamentalTriggerEvaluator` status FAILED contradicts the thesis), and
CANCELLED opportunities are excluded from `REUSABLE_TRADE_ACTIONS` by
construction. So a genuinely invalidated thesis naturally stops matching
future candidates without any additional thesis-text diffing -- keeping
this deterministic and auditable rather than a fuzzy similarity heuristic.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.enums import Direction, TradeAction
from app.domain.models import MonitoredTradeOpportunity

# Only these trade_action states represent a still-open, undecided
# opportunity eligible for reuse. CANCELLED covers three distinct causes --
# a contradicting catalyst, time-stop expiration (trigger_status=EXPIRED),
# and a manual skip (see TradeOpportunityMonitorService.cancel_opportunity,
# used by `journal skip`) -- all terminal, all excluded here.
REUSABLE_TRADE_ACTIONS = frozenset({TradeAction.WAIT, TradeAction.READY_TO_TRADE})


@dataclass(frozen=True)
class OpportunityFingerprint:
    asset: str
    direction: Direction
    horizon: str

    @classmethod
    def for_opportunity(cls, opportunity: MonitoredTradeOpportunity) -> OpportunityFingerprint:
        return cls(
            asset=opportunity.asset, direction=opportunity.direction, horizon=opportunity.horizon
        )


def find_reusable_opportunity(
    opportunities: list[MonitoredTradeOpportunity], fingerprint: OpportunityFingerprint
) -> MonitoredTradeOpportunity | None:
    """Returns the still-active opportunity matching `fingerprint`, if any.
    Never matches a CANCELLED (contradicted/expired/skipped) opportunity,
    however identical its asset/direction/horizon once were.
    """
    for opportunity in opportunities:
        if opportunity.trade_action not in REUSABLE_TRADE_ACTIONS:
            continue
        if OpportunityFingerprint.for_opportunity(opportunity) == fingerprint:
            return opportunity
    return None
