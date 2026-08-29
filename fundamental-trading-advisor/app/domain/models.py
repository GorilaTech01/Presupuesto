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
    Freshness,
    ObservationKind,
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


class FundamentalDecision(BaseModel):
    """The single structured decision produced for a given run.

    `conviction` is 0-100 internally; `conviction_1_10` is the user-facing
    rounding of it. Both must agree.
    """

    symbol: str
    asset_class: AssetClass
    direction: Direction
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
