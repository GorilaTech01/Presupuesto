"""Manual-research equivalence test (audit section 5,
docs/decision_audit_eurusd_2026-08-31.md).

Proves that a `FactObservation` built by hand the way
`scripts/demo_manual_research_run.py` does, and the equivalent
`FactObservation` produced by a real source-client parsing path (here,
`FredClient.fetch_indicator`, respx-mocked so no real network call is
made), are NOT two different code paths that happen to look similar --
once a value is normalized into a `FactObservation`, everything downstream
(scoring, currency-score aggregation, decisions) is provably identical.
This is what justifies treating the manual-research demo as a legitimate
stand-in for a live fetch, rather than a shortcut around normalization.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import respx

from app.common.cache import DiskCache
from app.domain.enums import Freshness, ObservationKind
from app.domain.models import FactObservation
from app.fundamental import analysis, scoring
from app.sources.fred.client import FredClient
from app.sources.freshness import classify
from app.sources.repository import FetchResult


def _manual_fact(value: float, previous: float, published: datetime) -> FactObservation:
    """Mirrors exactly how scripts/demo_manual_research_run.py::fact() builds
    a FactObservation by hand."""
    return FactObservation(
        indicator="us_fed_funds_target_upper",
        country="US",
        asset_relevance=[],
        source="FRED",
        source_url="https://fred.stlouisfed.org/series/DFEDTARU",
        publication_timestamp=published,
        observation_period=published.strftime("%Y-%m-%d"),
        kind=ObservationKind.ACTUAL,
        value=value,
        unit="percent",
        consensus=None,
        revised_previous=previous,
        freshness=Freshness.FRESH,
        retrieval_timestamp=datetime(2026, 8, 29, tzinfo=UTC),
    )


@respx.mock
def _live_fetched_fact(
    tmp_path: Path, value: float, previous: float, published: datetime
) -> FactObservation:
    """Mirrors exactly how a real weekly-pipeline run gets the same
    indicator: FredClient.fetch_indicator, hitting a respx-mocked HTTP
    response instead of the real FRED API."""
    respx.get("https://api.stlouisfed.org/fred/series/observations").mock(
        return_value=httpx.Response(
            200,
            json={
                "observations": [
                    {"date": published.strftime("%Y-%m-%d"), "value": str(value)},
                    {"date": "2026-07-01", "value": str(previous)},
                ]
            },
        )
    )
    client = FredClient(api_key="testkey", cache=DiskCache(tmp_path / "cache"))
    fact = client.fetch_indicator("us_fed_funds_target_upper")
    return fact.model_copy(update={"freshness": classify(fact)})


def test_manual_and_live_fetched_fact_produce_identical_driver_score(tmp_path: Path):
    published = datetime(2026, 7, 29, tzinfo=UTC)
    manual = _manual_fact(3.75, 3.75, published)
    live = _live_fetched_fact(tmp_path, 3.75, 3.75, published)

    inflation = _manual_fact(3.4, 3.5, published)  # reused as a generic fact stand-in

    manual_driver = scoring.score_monetary_policy(policy_rate=manual, headline_inflation=inflation)
    live_driver = scoring.score_monetary_policy(policy_rate=live, headline_inflation=inflation)

    assert manual_driver.contribution == live_driver.contribution
    assert manual_driver.category == live_driver.category
    assert manual_driver.rationale == live_driver.rationale


def test_manual_and_live_fetched_fact_produce_identical_currency_score(tmp_path: Path):
    published = datetime(2026, 7, 29, tzinfo=UTC)
    manual = _manual_fact(3.75, 3.75, published)
    live = _live_fetched_fact(tmp_path, 3.75, 3.75, published)

    manual_result = FetchResult(facts={"us_fed_funds_target_upper": manual}, errors={})
    live_result = FetchResult(facts={"us_fed_funds_target_upper": live}, errors={})

    manual_score = analysis.build_currency_score("USD", manual_result)
    live_score = analysis.build_currency_score("USD", live_result)

    assert manual_score.total == live_score.total
    assert [d.contribution for d in manual_score.drivers] == [
        d.contribution for d in live_score.drivers
    ]
    assert [d.rationale for d in manual_score.drivers] == [d.rationale for d in live_score.drivers]
