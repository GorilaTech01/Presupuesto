"""Persistence for monitored opportunities (spec section 16).

Two files, two different write disciplines:

  `opportunities.jsonl`       -- current state, one line per opportunity.
                                 Updates rewrite that opportunity's line
                                 (via read-all/replace/write-all, same
                                 pattern as `RecommendationJournal`); never
                                 silently drops history.
  `opportunity_events.jsonl`  -- append-only audit log. Every material
                                 change is appended, never rewritten or
                                 deleted, so the full history is always
                                 reconstructable.
"""

from __future__ import annotations

from pathlib import Path

from app.common.event_bus import DomainEvent
from app.domain.models import MonitoredTradeOpportunity


class OpportunityStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load_all(self) -> list[MonitoredTradeOpportunity]:
        if not self.path.exists():
            return []
        opportunities = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            opportunities.append(MonitoredTradeOpportunity.model_validate_json(line))
        return opportunities

    def get(self, opportunity_id: str) -> MonitoredTradeOpportunity | None:
        for opportunity in self.load_all():
            if opportunity.opportunity_id == opportunity_id:
                return opportunity
        return None

    def save(self, opportunity: MonitoredTradeOpportunity) -> None:
        """Insert or update (by opportunity_id)."""
        opportunities = self.load_all()
        for i, existing in enumerate(opportunities):
            if existing.opportunity_id == opportunity.opportunity_id:
                opportunities[i] = opportunity
                break
        else:
            opportunities.append(opportunity)
        self._write_all(opportunities)

    def _write_all(self, opportunities: list[MonitoredTradeOpportunity]) -> None:
        with self.path.open("w", encoding="utf-8") as f:
            for o in opportunities:
                f.write(o.model_dump_json() + "\n")


class OpportunityEventLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: DomainEvent) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(event.model_dump_json() + "\n")

    def load_all(self) -> list[DomainEvent]:
        if not self.path.exists():
            return []
        events = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            events.append(DomainEvent.model_validate_json(line))
        return events

    def for_opportunity(self, opportunity_id: str) -> list[DomainEvent]:
        return [e for e in self.load_all() if e.opportunity_id == opportunity_id]
