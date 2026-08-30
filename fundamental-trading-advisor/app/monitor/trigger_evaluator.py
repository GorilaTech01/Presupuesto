"""FundamentalTriggerEvaluator (V1.1 monitoring spec, section 8).

Evaluates whether the fundamental catalysts a monitored opportunity's
thesis depends on have resolved -- confirming, contradicting, or still
pending. Every input is a published (or still-pending) economic release
compared against its consensus; nothing here is derived from price history
or any chart-based indicator (no moving averages, support/resistance,
RSI/MACD/ATR, candles, breakouts, order blocks, or market structure --
none of that data even exists in this module's inputs).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.catalysts.service import hawkish_direction_for_indicator
from app.domain.enums import CatalystSeverity, TriggerStatus
from app.domain.models import CatalystEvent, EconomicReleaseSurprise

REQUIRED_SEVERITIES = {CatalystSeverity.HIGH, CatalystSeverity.CRITICAL}

NOT_YET_PUBLISHED = "NOT_YET_PUBLISHED"
CONSENSUS_UNAVAILABLE = "CONSENSUS_UNAVAILABLE"
UNKNOWN_DIRECTIONALITY = "UNKNOWN_DIRECTIONALITY"
NEUTRAL = "NEUTRAL"

_UNRESOLVED_DIRECTIONS = {NOT_YET_PUBLISHED, CONSENSUS_UNAVAILABLE, UNKNOWN_DIRECTIONALITY}


def build_surprise(catalyst: CatalystEvent) -> EconomicReleaseSurprise:
    """Turns one CatalystEvent into a standardized EconomicReleaseSurprise.
    Never invents a consensus: if `catalyst.consensus` is None, the
    direction is explicitly CONSENSUS_UNAVAILABLE, not guessed.
    """
    absolute_surprise: float | None = None
    normalized_surprise: float | None = None

    if catalyst.actual is None:
        direction = NOT_YET_PUBLISHED
    elif catalyst.consensus is None:
        direction = CONSENSUS_UNAVAILABLE
    else:
        absolute_surprise = catalyst.actual - catalyst.consensus
        normalized_surprise = (
            absolute_surprise / abs(catalyst.consensus) if catalyst.consensus != 0 else None
        )
        hawkish_side = hawkish_direction_for_indicator(catalyst.indicator)
        if hawkish_side is None:
            direction = UNKNOWN_DIRECTIONALITY
        elif absolute_surprise == 0:
            direction = NEUTRAL
        elif (absolute_surprise > 0) == (hawkish_side == "above"):
            direction = f"{catalyst.country}_HAWKISH"
        else:
            direction = f"{catalyst.country}_DOVISH"

    return EconomicReleaseSurprise(
        indicator=catalyst.indicator,
        country=catalyst.country,
        actual=catalyst.actual,
        consensus=catalyst.consensus,
        previous=catalyst.previous,
        revised_previous=None,
        absolute_surprise=absolute_surprise,
        normalized_surprise=normalized_surprise,
        direction_for_currency_or_asset=direction,
        materiality=catalyst.severity,
        published_at=catalyst.date_utc if catalyst.actual is not None else None,
        source=catalyst.source,
    )


@dataclass
class TriggerEvaluation:
    status: TriggerStatus
    surprises: list[EconomicReleaseSurprise] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


class FundamentalTriggerEvaluator:
    """Evaluates ONLY fundamental conditions -- economic-release surprises
    versus consensus, central-bank decisions, and similar. Never technical:
    no field on `CatalystEvent`/`EconomicReleaseSurprise` carries a price,
    an indicator value, or anything chart-derived.
    """

    def evaluate(self, catalysts: list[CatalystEvent], favored_country: str) -> TriggerEvaluation:
        required = [c for c in catalysts if c.severity in REQUIRED_SEVERITIES]
        if not required:
            return TriggerEvaluation(
                TriggerStatus.CONFIRMED, [], ["no high-impact catalysts required by this thesis"]
            )

        surprises = [build_surprise(c) for c in required]
        reasons: list[str] = []
        confirmed = 0
        contradicted = 0

        for surprise in surprises:
            direction = surprise.direction_for_currency_or_asset
            if direction in _UNRESOLVED_DIRECTIONS:
                reasons.append(f"{surprise.indicator}: {direction}")
                continue
            if direction == NEUTRAL:
                reasons.append(f"{surprise.indicator}: neutral surprise, inconclusive")
                continue

            is_favored_side = surprise.country == favored_country
            is_hawkish = direction.endswith("_HAWKISH")
            # A hawkish surprise on the favored side, or a dovish surprise on
            # the unfavored side, confirms the thesis; the opposite of
            # either contradicts it.
            if is_favored_side == is_hawkish:
                confirmed += 1
                reasons.append(f"{surprise.indicator}: confirms thesis ({direction})")
            else:
                contradicted += 1
                reasons.append(f"{surprise.indicator}: contradicts thesis ({direction})")

        if contradicted > 0:
            return TriggerEvaluation(TriggerStatus.FAILED, surprises, reasons)
        if confirmed == len(required):
            return TriggerEvaluation(TriggerStatus.CONFIRMED, surprises, reasons)
        if confirmed > 0:
            return TriggerEvaluation(TriggerStatus.PARTIALLY_CONFIRMED, surprises, reasons)
        return TriggerEvaluation(TriggerStatus.PENDING, surprises, reasons)
