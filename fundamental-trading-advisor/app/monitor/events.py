"""Domain event names + builders for the monitoring layer (spec section 5).

Every event carries just enough payload to explain itself in a log line or
an alert; the full current state always lives in the persisted
`MonitoredTradeOpportunity`, so events are notifications, not the source of
truth.
"""

from __future__ import annotations

from typing import Any

from app.common.event_bus import DomainEvent
from app.domain.models import MonitoredTradeOpportunity

TRADE_OPPORTUNITY_CREATED = "TradeOpportunityCreated"
TRADE_OPPORTUNITY_UPDATED = "TradeOpportunityUpdated"
TRADE_OPPORTUNITY_READY = "TradeOpportunityReady"
TRADE_OPPORTUNITY_CANCELLED = "TradeOpportunityCancelled"
TRADE_OPPORTUNITY_EXPIRED = "TradeOpportunityExpired"
FUNDAMENTAL_BIAS_CHANGED = "FundamentalBiasChanged"
CONVICTION_CHANGED_MATERIALLY = "ConvictionChangedMaterially"


def _event(event_type: str, opportunity: MonitoredTradeOpportunity, **extra: Any) -> DomainEvent:
    payload = {
        "symbol": opportunity.symbol,
        "fundamental_bias": opportunity.fundamental_bias.value,
        "trade_action": opportunity.trade_action.value,
        "conviction": opportunity.conviction,
        "current_score": opportunity.current_score,
        **extra,
    }
    return DomainEvent(
        event_type=event_type, opportunity_id=opportunity.opportunity_id, payload=payload
    )


def trade_opportunity_created(opportunity: MonitoredTradeOpportunity) -> DomainEvent:
    return _event(TRADE_OPPORTUNITY_CREATED, opportunity)


def trade_opportunity_updated(opportunity: MonitoredTradeOpportunity) -> DomainEvent:
    return _event(TRADE_OPPORTUNITY_UPDATED, opportunity)


def trade_opportunity_ready(opportunity: MonitoredTradeOpportunity) -> DomainEvent:
    return _event(TRADE_OPPORTUNITY_READY, opportunity)


def trade_opportunity_cancelled(opportunity: MonitoredTradeOpportunity) -> DomainEvent:
    return _event(TRADE_OPPORTUNITY_CANCELLED, opportunity, reason=opportunity.cancellation_reason)


def trade_opportunity_expired(opportunity: MonitoredTradeOpportunity) -> DomainEvent:
    return _event(TRADE_OPPORTUNITY_EXPIRED, opportunity)


def fundamental_bias_changed(
    opportunity: MonitoredTradeOpportunity, previous_bias: str
) -> DomainEvent:
    return _event(FUNDAMENTAL_BIAS_CHANGED, opportunity, previous_bias=previous_bias)


def conviction_changed_materially(
    opportunity: MonitoredTradeOpportunity, previous_conviction: int
) -> DomainEvent:
    return _event(
        CONVICTION_CHANGED_MATERIALLY, opportunity, previous_conviction=previous_conviction
    )
