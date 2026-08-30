"""Shared manual-acknowledgment actions: `journal enter` / `journal skip`.

This is the single implementation the CLI and the desktop app's "I Entered
This Trade" / "Skip Trade" buttons both call -- neither re-implements it.
Never sends an order, never touches MT5, never modifies a real or
simulated position: these functions only write to the local journal and
mark a `MonitoredTradeOpportunity` accordingly.
"""

from __future__ import annotations

from app.config.settings import Settings
from app.domain.enums import JournalStatus
from app.journal.journal import RecommendationJournal
from app.journal.models import JournalEntry
from app.monitor.service import TradeOpportunityMonitorService
from app.monitor.store import OpportunityStore


class OpportunityNotFound(LookupError):
    def __init__(self, opportunity_id: str) -> None:
        self.opportunity_id = opportunity_id
        super().__init__(f"No monitored opportunity with id {opportunity_id}")


class JournalEntryNotLinked(LookupError):
    def __init__(self, recommendation_id: str) -> None:
        self.recommendation_id = recommendation_id
        super().__init__(f"No journal entry linked to recommendation_id {recommendation_id}")


def record_manual_entry(settings: Settings, *, opportunity_id: str, price: float) -> JournalEntry:
    """Records that the user manually entered this trade in MT5. Never
    sends an order -- only writes a journal line."""
    store = OpportunityStore(settings.data_dir / "monitor" / "opportunities.jsonl")
    opportunity = store.get(opportunity_id)
    if opportunity is None:
        raise OpportunityNotFound(opportunity_id)
    journal = RecommendationJournal(settings.journal_dir / "journal.jsonl")
    try:
        return journal.update(
            opportunity.recommendation_id,
            status=JournalStatus.ACTIVE_SIMULATION,
            entry_price_actual_or_simulated=price,
        )
    except KeyError:
        raise JournalEntryNotLinked(opportunity.recommendation_id) from None


def record_skip(settings: Settings, *, opportunity_id: str) -> JournalEntry:
    """Records that the user decided not to take this opportunity, and
    cancels the underlying `MonitoredTradeOpportunity` (see
    `app.monitor.identity`) so it is excluded from both future reuse and
    future `monitor --all` re-evaluation -- not just marked in the journal.
    """
    store = OpportunityStore(settings.data_dir / "monitor" / "opportunities.jsonl")
    opportunity = store.get(opportunity_id)
    if opportunity is None:
        raise OpportunityNotFound(opportunity_id)
    journal = RecommendationJournal(settings.journal_dir / "journal.jsonl")
    try:
        entry = journal.update(
            opportunity.recommendation_id,
            status=JournalStatus.CANCELLED,
            exit_reason="USER_SKIPPED",
        )
    except KeyError:
        raise JournalEntryNotLinked(opportunity.recommendation_id) from None
    service = TradeOpportunityMonitorService(settings)
    try:
        service.cancel_opportunity(opportunity, reason="USER_SKIPPED")
    finally:
        service.close()
    return entry
