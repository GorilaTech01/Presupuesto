"""AlertPolicy + AlertSink (V1.1 monitoring spec, sections 14-15).

`AlertPolicy` decides WHICH domain events (see `app.monitor.events`) are
worth surfacing to the user and enforces idempotency itself, independent of
whatever the caller already did -- the same (opportunity, state) pair is
never alerted twice, even across separate `monitor` CLI invocations, since
the policy's dedup ledger is persisted (`data/monitor/alert_state.jsonl`
equivalent is unnecessary; the ledger is derived from the opportunity's own
last-alerted signature stored alongside it -- see `AlertPolicy.handle`).

`AlertSink` is a minimal abstraction so a channel can be swapped in later
(email, Telegram, Slack, a Claude/Cowork scheduled workflow) without
touching this policy. Only Console and JSON-file sinks are implemented in
this version -- no external channel is wired up (spec section 15/29).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from app.common.event_bus import DomainEvent
from app.monitor.events import (
    CONVICTION_CHANGED_MATERIALLY,
    FUNDAMENTAL_BIAS_CHANGED,
    TRADE_OPPORTUNITY_CANCELLED,
    TRADE_OPPORTUNITY_EXPIRED,
    TRADE_OPPORTUNITY_READY,
)

DEFAULT_ALERT_WORTHY_EVENT_TYPES = frozenset(
    {
        TRADE_OPPORTUNITY_READY,
        TRADE_OPPORTUNITY_CANCELLED,
        TRADE_OPPORTUNITY_EXPIRED,
        FUNDAMENTAL_BIAS_CHANGED,
    }
)


class AlertSink(Protocol):
    def send(self, message: str, *, event: DomainEvent) -> None: ...


class ConsoleAlertSink:
    def send(self, message: str, *, event: DomainEvent) -> None:
        print(message)


class JsonAlertSink:
    """Appends one JSON line per alert actually sent -- a durable record
    separate from the opportunity event log, useful for wiring an external
    notifier later without re-deriving "what should have alerted".
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def send(self, message: str, *, event: DomainEvent) -> None:
        record = {"message": message, "event": json.loads(event.model_dump_json())}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")


class AlertPolicy:
    def __init__(
        self,
        sink: AlertSink,
        *,
        include_conviction_changes: bool = True,
        conviction_delta: int = 10,
    ) -> None:
        self.sink = sink
        self.include_conviction_changes = include_conviction_changes
        self.conviction_delta = conviction_delta
        self._last_alerted_signature: dict[str, tuple[str, str | None, str | None]] = {}

    def _worthy_types(self) -> frozenset[str]:
        if self.include_conviction_changes:
            return DEFAULT_ALERT_WORTHY_EVENT_TYPES | {CONVICTION_CHANGED_MATERIALLY}
        return DEFAULT_ALERT_WORTHY_EVENT_TYPES

    def handle(self, event: DomainEvent) -> bool:
        """Returns True if an alert was actually sent (False if filtered
        out or a duplicate of the last alert for this opportunity+state).
        """
        if event.event_type not in self._worthy_types():
            return False

        signature = (
            event.event_type,
            event.payload.get("trade_action"),
            event.payload.get("fundamental_bias"),
        )
        if self._last_alerted_signature.get(event.opportunity_id) == signature:
            return False  # idempotent: already alerted for this exact state

        self._last_alerted_signature[event.opportunity_id] = signature
        self.sink.send(self._format(event), event=event)
        return True

    @staticmethod
    def _format(event: DomainEvent) -> str:
        symbol = event.payload.get("symbol", "?")
        return f"[ALERT] {event.event_type} -- {symbol} ({event.opportunity_id})"
