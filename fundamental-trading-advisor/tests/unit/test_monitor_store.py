"""OpportunityStore (mutable current-state JSONL) and OpportunityEventLog
(append-only audit log) -- spec section 16.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.common.event_bus import DomainEvent
from app.domain.enums import Direction, FundamentalBias, TradeAction, TriggerStatus
from app.domain.models import MonitoredTradeOpportunity
from app.monitor.store import OpportunityEventLog, OpportunityStore

_NOW = datetime(2026, 9, 1, tzinfo=UTC)


def _opportunity(
    opportunity_id: str, *, trade_action: TradeAction = TradeAction.WAIT
) -> MonitoredTradeOpportunity:
    return MonitoredTradeOpportunity(
        opportunity_id=opportunity_id,
        recommendation_id=f"rec-{opportunity_id}",
        created_at=_NOW,
        updated_at=_NOW,
        asset="EURUSD",
        symbol="EURUSD",
        fundamental_bias=FundamentalBias.BEARISH,
        trade_action=trade_action,
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


def test_store_load_all_on_missing_file_returns_empty(tmp_path: Path):
    store = OpportunityStore(tmp_path / "monitor" / "opportunities.jsonl")
    assert store.load_all() == []


def test_store_save_and_get_round_trips(tmp_path: Path):
    store = OpportunityStore(tmp_path / "opportunities.jsonl")
    opp = _opportunity("abc")
    store.save(opp)
    fetched = store.get("abc")
    assert fetched is not None
    assert fetched.opportunity_id == "abc"
    assert fetched.fundamental_bias is FundamentalBias.BEARISH


def test_store_get_missing_id_returns_none(tmp_path: Path):
    store = OpportunityStore(tmp_path / "opportunities.jsonl")
    store.save(_opportunity("abc"))
    assert store.get("does-not-exist") is None


def test_store_save_updates_in_place_without_duplicating(tmp_path: Path):
    store = OpportunityStore(tmp_path / "opportunities.jsonl")
    store.save(_opportunity("abc", trade_action=TradeAction.WAIT))
    updated = _opportunity("abc", trade_action=TradeAction.NO_TRADE)
    store.save(updated)
    all_opps = store.load_all()
    assert len(all_opps) == 1
    assert all_opps[0].trade_action is TradeAction.NO_TRADE


def test_store_save_appends_distinct_opportunities(tmp_path: Path):
    store = OpportunityStore(tmp_path / "opportunities.jsonl")
    store.save(_opportunity("abc"))
    store.save(_opportunity("def"))
    assert {o.opportunity_id for o in store.load_all()} == {"abc", "def"}


def test_event_log_is_append_only_and_never_overwritten(tmp_path: Path):
    log = OpportunityEventLog(tmp_path / "opportunity_events.jsonl")
    e1 = DomainEvent(event_type="TradeOpportunityCreated", opportunity_id="abc", payload={})
    e2 = DomainEvent(event_type="TradeOpportunityUpdated", opportunity_id="abc", payload={})
    log.append(e1)
    log.append(e2)
    all_events = log.load_all()
    assert len(all_events) == 2
    assert [e.event_type for e in all_events] == [
        "TradeOpportunityCreated",
        "TradeOpportunityUpdated",
    ]


def test_event_log_for_opportunity_filters_by_id(tmp_path: Path):
    log = OpportunityEventLog(tmp_path / "opportunity_events.jsonl")
    log.append(DomainEvent(event_type="TradeOpportunityCreated", opportunity_id="abc", payload={}))
    log.append(DomainEvent(event_type="TradeOpportunityCreated", opportunity_id="def", payload={}))
    abc_events = log.for_opportunity("abc")
    assert len(abc_events) == 1
    assert abc_events[0].opportunity_id == "abc"
