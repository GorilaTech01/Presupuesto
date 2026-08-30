from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import UTC, datetime  # noqa: E402

import pytest  # noqa: E402

from app.domain.enums import Freshness, ObservationKind
from app.domain.models import FactObservation


@pytest.fixture
def make_fact():
    def _make(
        indicator: str,
        value: float | None,
        *,
        country: str = "US",
        unit: str = "percent",
        revised_previous: float | None = None,
        consensus: float | None = None,
        freshness: Freshness = Freshness.FRESH,
        publication_timestamp: datetime | None = None,
        source: str = "TESTSRC",
    ) -> FactObservation:
        return FactObservation(
            indicator=indicator,
            country=country,
            asset_relevance=[],
            source=source,
            source_url="https://example.invalid/series",
            publication_timestamp=publication_timestamp or datetime(2026, 8, 1, tzinfo=UTC),
            observation_period="2026-08",
            kind=ObservationKind.ACTUAL,
            value=value,
            unit=unit,
            consensus=consensus,
            revised_previous=revised_previous,
            freshness=freshness,
            retrieval_timestamp=datetime(2026, 8, 29, tzinfo=UTC),
        )

    return _make
