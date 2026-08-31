from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.domain.enums import Freshness
from app.sources.freshness import classify


def test_fresh_recent_rate(make_fact):
    fact = make_fact(
        "us_fed_funds_target_upper",
        4.0,
        publication_timestamp=datetime.now(UTC) - timedelta(days=1),
    )
    assert classify(fact) is Freshness.FRESH


def test_stale_old_cpi(make_fact):
    fact = make_fact(
        "us_cpi_yoy", 3.0, publication_timestamp=datetime.now(UTC) - timedelta(days=200)
    )
    assert classify(fact) is Freshness.STALE


def test_aging_between_thresholds(make_fact):
    fact = make_fact(
        "us_cpi_yoy", 3.0, publication_timestamp=datetime.now(UTC) - timedelta(days=50)
    )
    assert classify(fact) is Freshness.AGING


def test_unknown_indicator_uses_default_cadence(make_fact):
    fact = make_fact(
        "some_unmapped_indicator", 1.0, publication_timestamp=datetime.now(UTC) - timedelta(days=1)
    )
    assert classify(fact) is Freshness.FRESH
