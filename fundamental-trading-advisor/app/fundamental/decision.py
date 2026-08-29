"""FundamentalDecisionEngine: turns scores + catalysts + data-quality
signals into BUY / SELL / NO_TRADE with an explainable conviction.

This engine never looks at price history or chart-derived levels. Its only
inputs are fundamental scores (see scoring.py/analysis.py), the catalyst
calendar, and data-quality metadata (freshness, missing indicators). It
returns a `DecisionDraft` -- not the final validated `FundamentalDecision`
-- because the trade plan (entry/SL/TP/RR) is a risk-engine concern that
needs a live price/spec, resolved by the pipeline afterward.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.enums import CatalystSeverity, Direction, Freshness
from app.domain.models import CatalystEvent, DriverScore, FundamentalScore

MIN_BIAS_FOR_TRADE = 0.6
MIN_CONVICTION_FOR_TRADE = 55
MAX_TOLERATED_WARNINGS = 1


@dataclass
class DecisionDraft:
    symbol: str
    direction: Direction
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
                reasons=reasons,
            )

        direction = Direction.BUY if bias > 0 else Direction.SELL
        conviction = self._conviction(bias, total_warnings, freshness, catalysts)
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
            f"{direction.value} {symbol}: {favored_ccy} fundamentals score "
            f"{base_score.total if direction is Direction.BUY else quote_score.total:+.2f} vs. "
            f"{unfavored_ccy} at "
            f"{quote_score.total if direction is Direction.BUY else base_score.total:+.2f} "
            f"(differential {bias:+.2f}, base_ccy - quote_ccy convention). " + " ".join(reasons)
        )
        return DecisionDraft(
            symbol=symbol,
            direction=direction,
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
            ],
            time_stop=(
                "Close/reassess by Friday market close of the analysis week regardless of P&L."
            ),
            data_freshness=freshness,
            sources=sources,
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
                reasons=[blocking],
            )
        direction = Direction.BUY if score.total > 0 else Direction.SELL
        conviction = self._conviction(score.total, len(score.warnings), freshness, catalysts)
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
            conviction=conviction,
            thesis=(
                f"{direction.value} {symbol}: net fundamental score {score.total:+.2f} driven by "
                + "; ".join(d.label for d in _top_drivers(score))
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
            ],
            time_stop=(
                "Close/reassess by Friday market close of the analysis week regardless of P&L."
            ),
            data_freshness=freshness,
            sources=sources,
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

    @staticmethod
    def _conviction(
        bias: float, total_warnings: int, freshness: Freshness, catalysts: list[CatalystEvent]
    ) -> int:
        base = min(90, 50 + abs(bias) * 20)
        base -= total_warnings * 10
        if freshness == Freshness.AGING:
            base -= 10
        if any(c.severity == CatalystSeverity.CRITICAL for c in catalysts):
            base -= 5
        return max(MIN_CONVICTION_FOR_TRADE, min(95, round(base)))
