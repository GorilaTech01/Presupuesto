"""AlertPolicy + AlertSink (spec sections 14-15). Focused on idempotency
(no duplicate alerts for the same opportunity+state) and event filtering.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.common.event_bus import DomainEvent
from app.monitor.alerts import AlertPolicy, ConsoleAlertSink, JsonAlertSink


class _RecordingSink:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, message: str, *, event: DomainEvent) -> None:
        self.sent.append(message)


def _event(event_type: str, opportunity_id: str = "abc", **payload: object) -> DomainEvent:
    return DomainEvent(event_type=event_type, opportunity_id=opportunity_id, payload=payload)


def test_handle_sends_alert_for_ready_event():
    sink = _RecordingSink()
    policy = AlertPolicy(sink)
    sent = policy.handle(_event("TradeOpportunityReady", symbol="EURUSD"))
    assert sent is True
    assert len(sink.sent) == 1


def test_handle_filters_out_non_worthy_event_types():
    sink = _RecordingSink()
    policy = AlertPolicy(sink)
    sent = policy.handle(_event("TradeOpportunityUpdated", symbol="EURUSD"))
    assert sent is False
    assert sink.sent == []


def test_handle_is_idempotent_for_the_same_state():
    sink = _RecordingSink()
    policy = AlertPolicy(sink)
    event = _event(
        "TradeOpportunityReady", trade_action="READY_TO_TRADE", fundamental_bias="BEARISH"
    )
    first = policy.handle(event)
    second = policy.handle(event)
    assert first is True
    assert second is False
    assert len(sink.sent) == 1


def test_handle_alerts_again_when_state_actually_changes():
    sink = _RecordingSink()
    policy = AlertPolicy(sink)
    ready = _event(
        "TradeOpportunityReady", trade_action="READY_TO_TRADE", fundamental_bias="BEARISH"
    )
    cancelled = _event(
        "TradeOpportunityCancelled", trade_action="CANCELLED", fundamental_bias="BEARISH"
    )
    assert policy.handle(ready) is True
    assert policy.handle(cancelled) is True
    assert len(sink.sent) == 2


def test_handle_dedups_per_opportunity_id_independently():
    sink = _RecordingSink()
    policy = AlertPolicy(sink)
    event_a = _event("TradeOpportunityReady", opportunity_id="abc", trade_action="READY_TO_TRADE")
    event_b = _event("TradeOpportunityReady", opportunity_id="def", trade_action="READY_TO_TRADE")
    assert policy.handle(event_a) is True
    assert policy.handle(event_b) is True
    assert len(sink.sent) == 2


def test_conviction_changes_can_be_excluded():
    sink = _RecordingSink()
    policy = AlertPolicy(sink, include_conviction_changes=False)
    sent = policy.handle(_event("ConvictionChangedMaterially"))
    assert sent is False


def test_conviction_changes_included_by_default():
    sink = _RecordingSink()
    policy = AlertPolicy(sink)
    sent = policy.handle(_event("ConvictionChangedMaterially", trade_action="WAIT"))
    assert sent is True


def test_console_alert_sink_does_not_raise(capsys):
    sink = ConsoleAlertSink()
    sink.send("hello", event=_event("TradeOpportunityReady"))
    captured = capsys.readouterr()
    assert "hello" in captured.out


def test_json_alert_sink_appends_valid_json_lines(tmp_path: Path):
    sink = JsonAlertSink(tmp_path / "alerts.jsonl")
    event = _event("TradeOpportunityReady", symbol="EURUSD")
    sink.send("[ALERT] test", event=event)
    lines = (tmp_path / "alerts.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["message"] == "[ALERT] test"
    assert record["event"]["event_type"] == "TradeOpportunityReady"
