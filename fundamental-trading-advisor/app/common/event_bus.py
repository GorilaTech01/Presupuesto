"""A minimal in-process, synchronous publish/subscribe bus.

No external message broker is introduced (section 5 of the V1.1 monitoring
spec explicitly says this isn't needed yet). Handlers run synchronously, in
subscription order, in the same process and call -- this is intentionally
as simple as it can be while still decoupling "something happened" from
"what to do about it" (e.g. logging vs. alerting vs. persistence).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class DomainEvent(BaseModel):
    event_type: str
    opportunity_id: str
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    payload: dict[str, Any] = Field(default_factory=dict)


EventHandler = Callable[[DomainEvent], None]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[EventHandler] = []

    def subscribe(self, handler: EventHandler) -> None:
        self._subscribers.append(handler)

    def publish(self, event: DomainEvent) -> None:
        for handler in self._subscribers:
            handler(event)
