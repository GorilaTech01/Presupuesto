"""FundamentalDecisionEngine: turns scores + catalysts + data-quality
signals into BUY / SELL / NO_TRADE with an explainable conviction.

This engine never looks at price history or chart-derived levels. Its only
inputs are fundamental scores (see scoring.py/analysis.py), the catalyst
calendar, and data-quality metadata (freshness, missing indicators). It
returns a `DecisionDraft` -- not the final validated `FundamentalDecision`
-- because the trade plan (entry/SL/TP/RR) is a risk-engine concern that
needs a live price/spec, resolved by the pipeline afterward.

AUDIT NOTE (2026-08-29, see docs/decision_audit_eurusd_2026-08-31.md):
Two things were added/changed here as a direct result of a pre-push audit:

1. `direction` (the fundamental bias: BUY/SELL/NO_TRADE) is now explicitly
   distinguished from `trade_action` (whether that bias is immediately
   executable). A pending CRITICAL catalyst with an unresolved outcome
   means `trade_action = WAIT_FOR_TRIGGER` even when `direction` is BUY or
   SELL -- BUY/SELL must never be read as "enter now" on its own; check
   `trade_action`.
2. Conviction is now computed as an explicit, inspectable
   `ConvictionBreakdown` (raw score, data completeness, source quality,
   contradiction/event-risk/missing-data/expectations penalties) instead of
   a single opaque expression, and a fixed `EXPECTATIONS_INCOMPLETE_PENALTY`
   is always applied because this version has no OIS/Fed-funds-futures/
   FedWatch-equivalent forward-policy-path data source (see
   `scoring.score_market_expectations`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.enums import CatalystSeverity, Direction, Freshness, TradeAction
from app.domain.models import CatalystEvent, ConvictionBreakdown, DriverScore, FundamentalScore

MIN_BIAS_FOR_TRADE = 0.6
MIN_CONVICTION_FOR_TRADE = 55
MAX_TOLERATED_WARNINGS = 1
CONTRADICTION_DRIVER_THRESHOLD = 0.05
CONTRADICTION_COUNT_FOR_PENALTY = 2
CONTRADICTION_PENALTY_POINTS = 5

# Fixed, always-applied penalty reflecting a permanent, structural gap in
# this version: no forward-looking policy-path (OIS / Fed-funds-futures /
# FedWatch-equivalent) data source is implemented (see
# `scoring.score_market_expectations`). This is NOT tuned per-run -- it is
# the same number regardless of direction, symbol, or how the rest of the
# audit turned out, precisely so it cannot be (mis)used to steer a
# particular outcome.
EXPECTATIONS_INCOMPLETE_PENALTY = 8


@dataclass
class DecisionDraft:
    symbol: str
    direction: Direction
    trade_action: TradeAction
    conviction: int
    thesis: str
    top_drivers: list[DriverScore]
    catalysts: list[CatalystEvent]
    entry_condition: str
    fundamental_invalidation: str
    risks: list[str]
    time_stop: str
    data_freshness: Freshness
    sources: list[str]
    conviction_breakdown: ConvictionBreakdown | None = None
    reasons: list[str] = field(default_factory=list)


def _worst_freshness(scores: list[FundamentalScore], facts_freshness: list[Freshness]) -> Freshness:
    order = [Freshness.FRESH, Freshness.AGING, Freshness.STALE, Freshness.UNKNOWN]
    worst = Freshness.FRESH
    for f in facts_freshness:
        if order.index(f) > order.index(worst):
            worst = f
    return worst


def _has_critical_unresolved_catalyst(catalysts: list[CatalystEvent]) -> CatalystEvent | None:
    for c in catalysts:
        if c.severity == CatalystSeverity.CRITICAL and c.actual is None:
            return c
    return None


def _top_drivers(*scores: FundamentalScore, n: int = 4) -> list[DriverScore]:
    all_drivers = [d for s in scores for d in s.drivers if abs(d.contribution) > 1e-9]
    all_drivers.sort(key=lambda d: abs(d.contribution), reverse=True)
    return all_drivers[:n]


def _trade_action(direction: Direction, catalysts: list[CatalystEvent]) -> TradeAction:
    if direction is Direction.NO_TRADE:
        return TradeAction.NONE
    if _has_critical_unresolved_catalyst(catalysts) is not None:
        return TradeAction.WAIT_FOR_TRIGGER
    return TradeAction.ENTER_NOW


def _fx_contradiction_penalty(
    direction: Direction, base_score: FundamentalScore, quote_score: FundamentalScore
) -> int:
    """Counts drivers that point the opposite way from the chosen direction.

    A base-currency driver supports BUY when positive; a quote-currency
    driver supports BUY when *negative* (a stronger quote currency pushes
    the pair down). Two or more meaningfully-sized (>= 0.05) drivers
    disagreeing with the chosen direction triggers a fixed penalty -- this
    surfaces "the aggregate score says X but several individual drivers say
    Y" instead of letting it disappear inside the total.
    """
    contradicting = 0
    for d in base_score.drivers:
        if abs(d.contribution) < CONTRADICTION_DRIVER_THRESHOLD:
            continue
        supports_buy = d.contribution > 0
        if supports_buy != (direction is Direction.BUY):
            contradicting += 1
    for d in quote_score.drivers:
        if abs(d.contribution) < CONTRADICTION_DRIVER_THRESHOLD:
            continue
        supports_buy = d.contribution < 0
        if supports_buy != (direction is Direction.BUY):
            contradicting += 1
    return CONTRADICTION_PENALTY_POINTS if contradicting >= CONTRADICTION_COUNT_FOR_PENALTY else 0


def _single_asset_contradiction_penalty(direction: Direction, score: FundamentalScore) -> int:
    contradicting = 0
    for d in score.drivers:
        if abs(d.contribution) < CONTRADICTION_DRIVER_THRESHOLD:
            continue
        supports_buy = d.contribution > 0
        if supports_buy != (direction is Direction.BUY):
            contradicting += 1
    return CONTRADICTION_PENALTY_POINTS if contradicting >= CONTRADICTION_COUNT_FOR_PENALTY else 0


def _build_conviction_breakdown(
    *,
    raw_score: float,
    total_warnings: int,
    data_completeness: str,
    freshness: Freshness,
    catalysts: list[CatalystEvent],
    contradiction_penalty: int,
) -> ConvictionBreakdown:
    normalized_score = min(40.0, raw_score * 20.0)
    base = 50.0 + normalized_score
    missing_data_penalty = total_warnings * 10
    source_quality_penalty = 10 if freshness == Freshness.AGING else 0
    event_risk_penalty = 5 if any(c.severity == CatalystSeverity.CRITICAL for c in catalysts) else 0
    final_raw = (
        base
        - missing_data_penalty
        - source_quality_penalty
        - event_risk_penalty
        - EXPECTATIONS_INCOMPLETE_PENALTY
        - contradiction_penalty
    )
    final_conviction = max(MIN_CONVICTION_FOR_TRADE, min(95, round(final_raw)))
    source_quality = (
        "all inputs FRESH (no penalty)"
        if freshness == Freshness.FRESH
        else f"{freshness.value} input(s) present (-{source_quality_penalty})"
    )
    return ConvictionBreakdown(
        raw_score=round(raw_score, 4),
        normalized_score=round(normalized_score, 4),
        data_completeness=data_completeness,
        source_quality=source_quality,
        contradiction_penalty=contradiction_penalty,
        event_risk_penalty=event_risk_penalty,
        missing_data_penalty=missing_data_penalty,
        source_quality_penalty=source_quality_penalty,
        expectations_penalty=EXPECTATIONS_INCOMPLETE_PENALTY,
        final_conviction=final_conviction,
    )


class FundamentalDecisionEngine:
    def decide_fx_pair(
        self,
        *,
        symbol: str,
        base_ccy: str,
        quote_ccy: str,
        base_score: FundamentalScore,
        quote_score: FundamentalScore,
        bias: float,
        catalysts: list[CatalystEvent],
        facts_freshness: list[Freshness],
    ) -> DecisionDraft:
        sources = sorted(
            {
                fact.split(":", 1)[0]
                for s in (base_score, quote_score)
                for d in s.drivers
                for fact in d.supporting_facts
            }
        )
        reasons: list[str] = []
        freshness = _worst_freshness([base_score, quote_score], facts_freshness)
        total_warnings = len(base_score.warnings) + len(quote_score.warnings)

        blocking = self._blocking_reason(
            bias=bias,
            freshness=freshness,
            total_warnings=total_warnings,
            catalysts=catalysts,
        )
        if blocking is not None:
            reasons.append(blocking)
            return DecisionDraft(
                symbol=symbol,
                direction=Direction.NO_TRADE,
                trade_action=TradeAction.NONE,
                conviction=0,
                thesis=(
                    f"NO_TRADE on {symbol}: {blocking} "
                    f"(current fundamental bias {base_ccy}-{quote_ccy} = {bias:+.2f})."
                ),
                top_drivers=_top_drivers(base_score, quote_score),
                catalysts=catalysts,
                entry_condition="N/A -- no trade proposed",
                fundamental_invalidation="N/A",
                risks=["No position proposed; risk is limited to opportunity cost."],
                time_stop="N/A",
                data_freshness=freshness,
                sources=sources,
                conviction_breakdown=None,
                reasons=reasons,
            )

        direction = Direction.BUY if bias > 0 else Direction.SELL
        contradiction_penalty = _fx_contradiction_penalty(direction, base_score, quote_score)
        data_completeness = (
            f"{base_ccy}: {len(base_score.drivers) - len(base_score.warnings)} driver(s) fed, "
            f"{len(base_score.warnings)} indicator(s) missing; "
            f"{quote_ccy}: {len(quote_score.drivers) - len(quote_score.warnings)} driver(s) fed, "
            f"{len(quote_score.warnings)} indicator(s) missing"
        )
        breakdown = _build_conviction_breakdown(
            raw_score=abs(bias),
            total_warnings=total_warnings,
            data_completeness=data_completeness,
            freshness=freshness,
            catalysts=catalysts,
            contradiction_penalty=contradiction_penalty,
        )
        conviction = breakdown.final_conviction
        trade_action = _trade_action(direction, catalysts)
        favored_ccy = base_ccy if direction is Direction.BUY else quote_ccy
        unfavored_ccy = quote_ccy if direction is Direction.BUY else base_ccy

        critical = _has_critical_unresolved_catalyst(catalysts)
        entry_condition = (
            f"CONDITIONAL_POST_EVENT: wait for {critical.indicator} ({critical.country}) on "
            f"{critical.date_local:%Y-%m-%d %H:%M} local; enter only if result confirms the "
            f"{favored_ccy}-favorable scenario ({critical.favors_thesis_if})."
            if critical is not None
            else (
                f"Enter on confirmation that {favored_ccy} fundamentals remain relatively stronger "
                f"than {unfavored_ccy} through the horizon; avoid entering directly into a data "
                "release."
            )
        )
        invalidation = (
            f"Thesis invalidated if {favored_ccy} fundamentals weaken materially relative to "
            f"{unfavored_ccy} (e.g. a dovish surprise from the {favored_ccy} side, or a hawkish "
            f"surprise from the {unfavored_ccy} side) such that the score differential flips sign."
        )
        thesis = (
            f"{direction.value} {symbol} [{trade_action.value}]: {favored_ccy} fundamentals score "
            f"{base_score.total if direction is Direction.BUY else quote_score.total:+.2f} vs. "
            f"{unfavored_ccy} at "
            f"{quote_score.total if direction is Direction.BUY else base_score.total:+.2f} "
            f"(differential {bias:+.2f}, base_ccy - quote_ccy convention). " + " ".join(reasons)
        )
        return DecisionDraft(
            symbol=symbol,
            direction=direction,
            trade_action=trade_action,
            conviction=conviction,
            thesis=thesis,
            top_drivers=_top_drivers(base_score, quote_score),
            catalysts=catalysts,
            entry_condition=entry_condition,
            fundamental_invalidation=invalidation,
            risks=[
                "Fundamental thesis can be invalidated intraweek by a single surprise data print.",
                "Score model is a heuristic approximation, not a guarantee of central "
                "bank behavior.",
                "No forward-policy-path (OIS/FedWatch-equivalent) data source is wired "
                "in this version; scoring reflects CURRENT policy only "
                "(EXPECTATIONS_DATA_INCOMPLETE).",
            ],
            time_stop=(
                "Close/reassess by Friday market close of the analysis week regardless of P&L."
            ),
            data_freshness=freshness,
            sources=sources,
            conviction_breakdown=breakdown,
            reasons=reasons,
        )

    def decide_single_asset(
        self,
        *,
        symbol: str,
        score: FundamentalScore,
        catalysts: list[CatalystEvent],
        facts_freshness: list[Freshness],
        bullish_direction_label: str = "higher",
    ) -> DecisionDraft:
        sources = sorted(
            {fact.split(":", 1)[0] for d in score.drivers for fact in d.supporting_facts}
        )
        freshness = _worst_freshness([score], facts_freshness)
        blocking = self._blocking_reason(
            bias=score.total,
            freshness=freshness,
            total_warnings=len(score.warnings),
            catalysts=catalysts,
        )
        if blocking is not None:
            return DecisionDraft(
                symbol=symbol,
                direction=Direction.NO_TRADE,
                trade_action=TradeAction.NONE,
                conviction=0,
                thesis=f"NO_TRADE on {symbol}: {blocking} (score={score.total:+.2f}).",
                top_drivers=_top_drivers(score),
                catalysts=catalysts,
                entry_condition="N/A -- no trade proposed",
                fundamental_invalidation="N/A",
                risks=["No position proposed; risk is limited to opportunity cost."],
                time_stop="N/A",
                data_freshness=freshness,
                sources=sources,
                conviction_breakdown=None,
                reasons=[blocking],
            )
        direction = Direction.BUY if score.total > 0 else Direction.SELL
        contradiction_penalty = _single_asset_contradiction_penalty(direction, score)
        data_completeness = (
            f"{len(score.drivers) - len(score.warnings)} driver(s) fed, "
            f"{len(score.warnings)} indicator(s)/data point(s) missing"
        )
        breakdown = _build_conviction_breakdown(
            raw_score=abs(score.total),
            total_warnings=len(score.warnings),
            data_completeness=data_completeness,
            freshness=freshness,
            catalysts=catalysts,
            contradiction_penalty=contradiction_penalty,
        )
        conviction = breakdown.final_conviction
        trade_action = _trade_action(direction, catalysts)
        critical = _has_critical_unresolved_catalyst(catalysts)
        entry_condition = (
            f"CONDITIONAL_POST_EVENT: wait for {critical.indicator} on "
            f"{critical.date_local:%Y-%m-%d %H:%M} local; enter only if it confirms "
            f"({critical.favors_thesis_if})."
            if critical is not None
            else (
                f"Enter on confirmation that fundamentals continue to favor "
                f"{direction.value} over the horizon."
            )
        )
        return DecisionDraft(
            symbol=symbol,
            direction=direction,
            trade_action=trade_action,
            conviction=conviction,
            thesis=(
                f"{direction.value} {symbol} [{trade_action.value}]: net fundamental score "
                f"{score.total:+.2f} driven by " + "; ".join(d.label for d in _top_drivers(score))
            ),
            top_drivers=_top_drivers(score),
            catalysts=catalysts,
            entry_condition=entry_condition,
            fundamental_invalidation=(
                f"Thesis invalidated if the net fundamental score for {symbol} flips sign "
                "(e.g. a reversal in real yields/USD for gold, or in liquidity conditions for BTC)."
            ),
            risks=[
                "Fundamental thesis can be invalidated intraweek by a single surprise data print.",
                "Score model is a heuristic approximation, not a guarantee of market behavior.",
                "No forward-policy-path (OIS/FedWatch-equivalent) data source is wired "
                "in this version; scoring reflects CURRENT policy only "
                "(EXPECTATIONS_DATA_INCOMPLETE).",
            ],
            time_stop=(
                "Close/reassess by Friday market close of the analysis week regardless of P&L."
            ),
            data_freshness=freshness,
            sources=sources,
            conviction_breakdown=breakdown,
            reasons=[],
        )

    @staticmethod
    def _blocking_reason(
        *,
        bias: float,
        freshness: Freshness,
        total_warnings: int,
        catalysts: list[CatalystEvent],
    ) -> str | None:
        if freshness == Freshness.STALE:
            return "one or more critical inputs are STALE"
        if total_warnings > MAX_TOLERATED_WARNINGS:
            return f"insufficient evidence: {total_warnings} required indicators unavailable"
        if abs(bias) < MIN_BIAS_FOR_TRADE:
            return f"fundamental asymmetry too weak (|bias|={abs(bias):.2f} < {MIN_BIAS_FOR_TRADE})"
        critical = _has_critical_unresolved_catalyst(catalysts)
        if critical is not None and critical.consensus is None:
            return (
                f"upcoming CRITICAL catalyst ({critical.indicator}) has CONSENSUS_UNAVAILABLE, "
                "too uncertain to pre-position"
            )
        return None
