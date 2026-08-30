"""FundamentalTriggerEvaluator + build_surprise (V1.1 monitoring spec,
section 8). Every input here is a published-or-pending economic release
compared against consensus -- no price, no indicator value, nothing
chart-derived is ever constructed in these fixtures.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.domain.enums import CatalystSeverity, TriggerStatus
from app.domain.models import CatalystEvent
from app.monitor.trigger_evaluator import (
    CONSENSUS_UNAVAILABLE,
    NEUTRAL,
    NOT_YET_PUBLISHED,
    UNKNOWN_DIRECTIONALITY,
    FundamentalTriggerEvaluator,
    build_surprise,
)

_NOW = datetime(2026, 9, 1, tzinfo=UTC)


def _catalyst(
    *,
    indicator: str = "us_nonfarm_payrolls",
    country: str = "US",
    severity: CatalystSeverity = CatalystSeverity.CRITICAL,
    actual: float | None = None,
    consensus: float | None = None,
    previous: float | None = None,
) -> CatalystEvent:
    return CatalystEvent(
        symbol_context="US",
        date_utc=_NOW,
        date_local=_NOW,
        country=country,
        indicator=indicator,
        severity=severity,
        actual=actual,
        consensus=consensus,
        previous=previous,
    )


# --------------------------------------------------------------------------
# build_surprise
# --------------------------------------------------------------------------


def test_build_surprise_not_yet_published_when_no_actual():
    surprise = build_surprise(_catalyst(actual=None, consensus=150.0))
    assert surprise.direction_for_currency_or_asset == NOT_YET_PUBLISHED
    assert surprise.published_at is None
    assert surprise.absolute_surprise is None


def test_build_surprise_never_fabricates_a_missing_consensus():
    surprise = build_surprise(_catalyst(actual=120.0, consensus=None))
    assert surprise.direction_for_currency_or_asset == CONSENSUS_UNAVAILABLE
    assert surprise.consensus is None
    assert surprise.absolute_surprise is None


def test_build_surprise_unknown_directionality_for_unmapped_indicator():
    surprise = build_surprise(
        _catalyst(indicator="some_indicator_with_no_hawkish_mapping", actual=5.0, consensus=4.0)
    )
    assert surprise.direction_for_currency_or_asset == UNKNOWN_DIRECTIONALITY


def test_build_surprise_neutral_when_actual_equals_consensus():
    surprise = build_surprise(
        _catalyst(indicator="us_nonfarm_payrolls", actual=150.0, consensus=150.0)
    )
    assert surprise.direction_for_currency_or_asset == NEUTRAL
    assert surprise.absolute_surprise == 0


def test_build_surprise_hawkish_above_consensus():
    # a beat on payrolls (above consensus) is hawkish for the US
    surprise = build_surprise(
        _catalyst(indicator="us_nonfarm_payrolls", actual=200.0, consensus=150.0)
    )
    assert surprise.direction_for_currency_or_asset == "US_HAWKISH"
    assert surprise.absolute_surprise == 50.0
    assert surprise.normalized_surprise is not None


def test_build_surprise_dovish_below_consensus():
    surprise = build_surprise(
        _catalyst(indicator="us_nonfarm_payrolls", actual=100.0, consensus=150.0)
    )
    assert surprise.direction_for_currency_or_asset == "US_DOVISH"


# --------------------------------------------------------------------------
# FundamentalTriggerEvaluator.evaluate
# --------------------------------------------------------------------------


def test_no_required_catalysts_is_trivially_confirmed():
    evaluator = FundamentalTriggerEvaluator()
    result = evaluator.evaluate([_catalyst(severity=CatalystSeverity.LOW)], favored_country="US")
    assert result.status is TriggerStatus.CONFIRMED
    assert result.surprises == []


def test_pending_when_required_catalyst_not_yet_published():
    evaluator = FundamentalTriggerEvaluator()
    result = evaluator.evaluate([_catalyst(actual=None, consensus=150.0)], favored_country="US")
    assert result.status is TriggerStatus.PENDING


def test_confirmed_when_favored_country_surprise_confirms_thesis():
    evaluator = FundamentalTriggerEvaluator()
    # a hawkish US surprise, with the thesis favoring the US, confirms it
    result = evaluator.evaluate(
        [_catalyst(indicator="us_nonfarm_payrolls", actual=200.0, consensus=150.0)],
        favored_country="US",
    )
    assert result.status is TriggerStatus.CONFIRMED


def test_failed_when_surprise_contradicts_thesis():
    evaluator = FundamentalTriggerEvaluator()
    # a dovish US surprise while the thesis favors the US contradicts it
    result = evaluator.evaluate(
        [_catalyst(indicator="us_nonfarm_payrolls", actual=100.0, consensus=150.0)],
        favored_country="US",
    )
    assert result.status is TriggerStatus.FAILED


def test_partially_confirmed_when_some_confirm_and_rest_unresolved():
    evaluator = FundamentalTriggerEvaluator()
    confirming = _catalyst(
        indicator="us_nonfarm_payrolls",
        severity=CatalystSeverity.CRITICAL,
        actual=200.0,
        consensus=150.0,
    )
    pending = _catalyst(
        indicator="us_cpi_yoy", severity=CatalystSeverity.HIGH, actual=None, consensus=3.2
    )
    result = evaluator.evaluate([confirming, pending], favored_country="US")
    assert result.status is TriggerStatus.PARTIALLY_CONFIRMED


def test_any_contradiction_fails_even_if_others_confirm():
    evaluator = FundamentalTriggerEvaluator()
    confirming = _catalyst(
        indicator="us_nonfarm_payrolls",
        severity=CatalystSeverity.CRITICAL,
        actual=200.0,
        consensus=150.0,
    )
    contradicting = _catalyst(
        indicator="us_nonfarm_payrolls",
        severity=CatalystSeverity.HIGH,
        actual=80.0,
        consensus=150.0,
    )
    result = evaluator.evaluate([confirming, contradicting], favored_country="US")
    assert result.status is TriggerStatus.FAILED


def test_only_high_and_critical_severities_are_required():
    evaluator = FundamentalTriggerEvaluator()
    # a LOW-severity catalyst that would contradict is simply irrelevant
    result = evaluator.evaluate(
        [
            _catalyst(
                indicator="us_nonfarm_payrolls",
                severity=CatalystSeverity.LOW,
                actual=80.0,
                consensus=150.0,
            )
        ],
        favored_country="US",
    )
    assert result.status is TriggerStatus.CONFIRMED


def test_consensus_unavailable_counts_as_unresolved_not_confirmed_or_contradicted():
    evaluator = FundamentalTriggerEvaluator()
    result = evaluator.evaluate(
        [_catalyst(actual=150.0, consensus=None, severity=CatalystSeverity.CRITICAL)],
        favored_country="US",
    )
    assert result.status is TriggerStatus.PENDING


def test_future_dated_catalyst_still_treated_as_pending_not_fabricated():
    evaluator = FundamentalTriggerEvaluator()
    future = _catalyst(actual=None, consensus=150.0, severity=CatalystSeverity.CRITICAL).model_copy(
        update={"date_utc": _NOW + timedelta(days=3)}
    )
    result = evaluator.evaluate([future], favored_country="US")
    assert result.status is TriggerStatus.PENDING
