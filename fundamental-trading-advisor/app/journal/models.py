"""RecommendationJournal entry model (section 22)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.enums import Direction, JournalStatus

SYSTEM_NAME = "FUNDAMENTAL_ONLY"


class JournalEntry(BaseModel):
    recommendation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    generated_at: datetime
    data_cutoff: datetime
    asset: str
    symbol: str
    direction: Direction
    conviction: int
    entry_condition: str
    recommended_entry: float | None
    stop_loss: float | None
    take_profit: float | None
    risk_reward: float | None
    time_stop: str
    fundamental_thesis: str
    drivers: list[str]
    catalysts: list[str]
    invalidation: str
    sources: list[str]
    status: JournalStatus = JournalStatus.PROPOSED

    # Set by TradeOpportunityMonitorService (V1.1) the moment a monitored
    # opportunity linked to this recommendation transitions WAIT -> READY_TO_TRADE.
    # Reaching READY_TO_TRADE is NOT the same as execution -- see `journal enter`.
    ready_to_trade_at: datetime | None = None

    # Filled in later by the (decoupled) paper-trade evaluator / manual update:
    entry_price_actual_or_simulated: float | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    pnl_points: float | None = None
    pnl_percent: float | None = None
    r_multiple: float | None = None
    maximum_favorable_excursion: float | None = None
    maximum_adverse_excursion: float | None = None
