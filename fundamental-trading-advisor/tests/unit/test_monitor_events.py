"""Domain event builders for the monitoring layer (spec section 5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.domain.enums import Direction, FundamentalBias, TradeAction, TriggerStatus
from app.domain.models import MonitoredTradeOpportunity
from app.monitor import events as monitor_events

_NOW = datetime(2026, 9, 1, tzinfo=UTC)


def _opportunity(**overrides: object) -> MonitoredTradeOpportunity:
    fields = dict(
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
    return MonitoredTradeOpportunity(**fields)


def test_trade_opportunity_created_event_carries_core_state():
    opp = _opportunity()
    event = monitor_events.trade_opportunity_created(opp)
    assert event.event_type == monitor_events.TRADE_OPPORTUNITY_CREATED
    assert event.opportunity_id == "abc"
    assert event.payload["symbol"] == "EURUSD"
    assert event.payload["trade_action"] == "WAIT"
    assert event.payload["fundamental_bias"] == "BEARISH"


def test_trade_opportunity_cancelled_event_carries_cancellation_reason():
    opp = _opportunity(
        trade_action=TradeAction.CANCELLED,
        cancellation_reason="fundamental catalyst contradicted the thesis",
    )
    event = monitor_events.trade_opportunity_cancelled(opp)
    assert event.event_type == monitor_events.TRADE_OPPORTUNITY_CANCELLED
    assert event.payload["reason"] == "fundamental catalyst contradicted the thesis"


def test_fundamental_bias_changed_event_carries_previous_bias():
    opp = _opportunity(fundamental_bias=FundamentalBias.NEUTRAL)
    event = monitor_events.fundamental_bias_changed(opp, previous_bias="BEARISH")
    assert event.event_type == monitor_events.FUNDAMENTAL_BIAS_CHANGED
    assert event.payload["previous_bias"] == "BEARISH"
    assert event.payload["fundamental_bias"] == "NEUTRAL"


def test_conviction_changed_materially_event_carries_previous_conviction():
    opp = _opportunity(conviction=80)
    event = monitor_events.conviction_changed_materially(opp, previous_conviction=55)
    assert event.event_type == monitor_events.CONVICTION_CHANGED_MATERIALLY
    assert event.payload["previous_conviction"] == 55
    assert event.payload["conviction"] == 80


def test_trade_opportunity_expired_event_type():
    opp = _opportunity(
        trade_action=TradeAction.CANCELLED, cancellation_reason="OPPORTUNITY_EXPIRED"
    )
    event = monitor_events.trade_opportunity_expired(opp)
    assert event.event_type == monitor_events.TRADE_OPPORTUNITY_EXPIRED


def test_event_bus_delivers_events_to_subscribers_in_order():
    from app.common.event_bus import DomainEvent, EventBus

    bus = EventBus()
    received: list[str] = []
    bus.subscribe(lambda e: received.append(f"first:{e.event_type}"))
    bus.subscribe(lambda e: received.append(f"second:{e.event_type}"))
    bus.publish(DomainEvent(event_type="X", opportunity_id="abc", payload={}))
    assert received == ["first:X", "second:X"]
