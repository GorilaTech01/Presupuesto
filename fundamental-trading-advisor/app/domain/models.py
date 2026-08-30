"""Typed domain models shared across the pipeline.

These are the "normalized facts" and "structured decision" objects referenced
in the architecture: DATA SOURCES -> NORMALIZED FACTS -> DETERMINISTIC
VALIDATION -> CLAUDE ANALYSIS/SYNTHESIS -> STRUCTURED DECISION -> VALIDATOR ->
USER OUTPUT. Every stage passes typed models, never bare dicts, so a broken
contract fails loudly instead of silently.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.enums import (
    AssetClass,
    CatalystSeverity,
    Direction,
    DriverCategory,
    ExecutionReadiness,
    Freshness,
    FundamentalBias,
    ObservationKind,
    TradeAction,
    TriggerStatus,
)


class FactObservation(BaseModel):
    """One normalized fundamental data point, traceable back to its source.

    `kind` records whether `value` is an ACTUAL, PREVIOUS, REVISED or
    CONSENSUS figure -- these must never be conflated.
    """

    model_config = ConfigDict(frozen=True)

    indicator: str
    country: str
    asset_relevance: list[str] = Field(default_factory=list)
    source: str
    source_url: str
    publication_timestamp: datetime
    observation_period: str
    kind: ObservationKind
    value: float | None
    unit: str
    consensus: float | None = None
    revised_previous: float | None = None
    freshness: Freshness = Freshness.UNKNOWN
    retrieval_timestamp: datetime


class DriverScore(BaseModel):
    """One explainable component of a fundamental score.

    `contribution` is the signed amount this driver added to the total
    score, so a score can always be decomposed back into `sum(contributions)`.
    """

    category: DriverCategory
    label: str
    contribution: float
    rationale: str
    supporting_facts: list[str] = Field(default_factory=list)


class FundamentalScore(BaseModel):
    """An explainable fundamental attractiveness score for one entity
    (a currency, or an asset like XAUUSD/BTCUSD).
    """

    subject: str
    total: float
    drivers: list[DriverScore]
    data_cutoff_utc: datetime
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _total_matches_drivers(self) -> FundamentalScore:
        expected = sum(d.contribution for d in self.drivers)
        if abs(expected - self.total) > 1e-6:
            raise ValueError(
                f"score total {self.total} does not equal sum of driver "
                f"contributions {expected} for {self.subject}"
            )
        return self


class CatalystEvent(BaseModel):
    symbol_context: str
    date_utc: datetime
    date_local: datetime
    country: str
    indicator: str
    severity: CatalystSeverity
    actual: float | None = None
    consensus: float | None = None
    previous: float | None = None
    favors_thesis_if: str = ""
    weakens_thesis_if: str = ""
    invalidates_thesis_if: str = ""
    source: str = ""
    source_url: str = ""


class CandidateAssessment(BaseModel):
    """One row of the mandatory 3-candidate weekly comparison table."""

    asset: str
    broker_symbol: str
    current_price: float | None
    price_as_of: datetime | None
    liquidity_note: str
    expected_event_volatility: str
    main_catalysts: list[str]
    bullish_fundamentals: list[str]
    bearish_fundamentals: list[str]
    event_slippage_risk: str
    thesis_quality_1_10: int
    final_reason: str
    score: FundamentalScore


class TradePlan(BaseModel):
    asset: str
    symbol: str
    direction: Direction
    conviction_1_10: int
    horizon: str
    order_type: str
    fundamental_trigger: str
    estimated_entry: float | None
    stop_loss: float | None
    distance_to_sl: float | None
    take_profit: float | None
    distance_to_tp: float | None
    risk_reward: float | None
    time_stop: str
    cancellation_condition: str
    fundamental_invalidation: str
    early_exit_condition: str
    main_catalysts: list[str]
    main_risks: list[str]


class ConvictionBreakdown(BaseModel):
    """Fully auditable decomposition of how `conviction` was computed.

    Added after the pre-push audit (docs/decision_audit_eurusd_2026-08-31.md,
    section 4) so conviction is never a single opaque number: every point
    added or subtracted is named here. `None` on a NO_TRADE decision
    (conviction is trivially 0; there is nothing to decompose).
    """

    raw_score: float
    normalized_score: float
    data_completeness: str
    source_quality: str
    contradiction_penalty: int
    event_risk_penalty: int
    missing_data_penalty: int
    source_quality_penalty: int
    expectations_penalty: int
    final_conviction: int


class FundamentalDecision(BaseModel):
    """The single structured decision produced for a given run.

    `conviction` is 0-100 internally; `conviction_1_10` is the user-facing
    rounding of it. Both must agree.

    `direction` is the fundamental bias (BUY/SELL/NO_TRADE). `trade_action`
    says whether that bias is immediately executable (`ENTER_NOW`) or
    pending a catalyst (`WAIT_FOR_TRIGGER`) -- added after the pre-push
    audit so BUY/SELL is never misread as "enter now" (section 7).
    """

    symbol: str
    asset_class: AssetClass
    direction: Direction
    trade_action: ExecutionReadiness
    conviction: int = Field(ge=0, le=100)
    horizon: str
    thesis: str
    top_drivers: list[DriverScore]
    catalysts: list[CatalystEvent]
    entry_condition: str
    fundamental_invalidation: str
    risks: list[str]
    time_stop: str
    data_freshness: Freshness
    sources: list[str]
    data_cutoff_utc: datetime
    data_cutoff_local: str
    trade_plan: TradePlan | None = None
    conviction_breakdown: ConvictionBreakdown | None = None
    reasons: list[str] = Field(default_factory=list)

    @property
    def conviction_1_10(self) -> int:
        return max(1, round(self.conviction / 10)) if self.conviction > 0 else 0

    @model_validator(mode="after")
    def _no_trade_has_no_plan(self) -> FundamentalDecision:
        if self.direction is Direction.NO_TRADE and self.trade_plan is not None:
            raise ValueError("NO_TRADE decisions must not carry a trade_plan")
        if self.direction is not Direction.NO_TRADE and self.trade_plan is None:
            raise ValueError("BUY/SELL decisions must carry a trade_plan")
        return self


class WeeklyComparison(BaseModel):
    generated_at: datetime
    data_cutoff_utc: datetime
    data_cutoff_local: str
    candidates: list[CandidateAssessment]
    selected_symbol: str | None
    decision: FundamentalDecision
    incomplete_reason: str | None = None

    @model_validator(mode="after")
    def _exactly_three_candidates(self) -> WeeklyComparison:
        if len(self.candidates) != 3:
            raise ValueError(
                f"weekly comparison must contain exactly 3 finalists, got {len(self.candidates)}"
            )
        return self


# ---------------------------------------------------------------------------
# V1.1 monitoring layer (docs/monitoring.md)
# ---------------------------------------------------------------------------


class EconomicReleaseSurprise(BaseModel):
    """A standardized, structured read of one economic release once (or if)
    it publishes. Never fabricates a consensus: `consensus=None` and
    `direction_for_currency_or_asset="CONSENSUS_UNAVAILABLE"` together mean
    exactly that, and callers must treat the surprise as unresolved rather
    than guessing a direction.
    """

    indicator: str
    country: str
    actual: float | None
    consensus: float | None
    previous: float | None
    revised_previous: float | None
    absolute_surprise: float | None
    normalized_surprise: float | None
    direction_for_currency_or_asset: str
    materiality: CatalystSeverity
    published_at: datetime | None
    source: str


class OpportunityHistoryEntry(BaseModel):
    """One append-only snapshot in a MonitoredTradeOpportunity's
    `decision_history`. Written every time the opportunity is (re)evaluated,
    whether or not anything changed, so the full evaluation timeline is
    auditable -- not just the moments something changed.
    """

    at: datetime
    fundamental_bias: FundamentalBias
    trade_action: TradeAction
    trigger_status: TriggerStatus
    conviction: int
    score: float
    reason: str


class MonitoredTradeOpportunity(BaseModel):
    """A weekly recommendation kept under fundamental observation so it can
    be re-evaluated as new data publishes, per docs/monitoring.md.

    `fundamental_bias` and `trade_action` are deliberately separate fields
    (section 1 of the V1.1 spec): a BEARISH bias can sit at WAIT for weeks.
    BUY/SELL only becomes an executable direction via `trade_plan`, and only
    once `trade_action == READY_TO_TRADE`.
    """

    opportunity_id: str
    recommendation_id: str
    created_at: datetime
    updated_at: datetime
    asset: str
    symbol: str
    fundamental_bias: FundamentalBias
    trade_action: TradeAction
    direction: Direction
    conviction: int = Field(ge=0, le=100)
    conviction_breakdown: ConvictionBreakdown | None = None
    original_score: float
    current_score: float
    threshold: float
    horizon: str
    entry_condition: str
    catalysts: list[CatalystEvent]
    fundamental_invalidation: str
    cancellation_conditions: list[str]
    time_stop: str
    valid_until: datetime
    data_cutoff: datetime
    last_evaluated_at: datetime
    next_relevant_event: CatalystEvent | None
    trigger_status: TriggerStatus
    readiness_reason: str | None = None
    cancellation_reason: str | None = None
    source_snapshot: list[str] = Field(default_factory=list)
    decision_history: list[OpportunityHistoryEntry] = Field(default_factory=list)
    trade_plan: TradePlan | None = None

    @model_validator(mode="after")
    def _ready_requires_plan_cancelled_requires_reason(self) -> MonitoredTradeOpportunity:
        if self.trade_action is TradeAction.READY_TO_TRADE and self.trade_plan is None:
            raise ValueError("READY_TO_TRADE opportunities must carry a trade_plan")
        if self.trade_action is TradeAction.CANCELLED and not self.cancellation_reason:
            raise ValueError("CANCELLED opportunities must carry a cancellation_reason")
        if self.trade_action is not TradeAction.READY_TO_TRADE and self.trade_plan is not None:
            raise ValueError("only READY_TO_TRADE opportunities may carry a trade_plan")
        return self
