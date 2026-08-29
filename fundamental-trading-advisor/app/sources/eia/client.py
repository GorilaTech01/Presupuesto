"""U.S. Energy Information Administration adapter (API v2).

Requires a free API key (EIA_API_KEY): https://www.eia.gov/opendata/register.php
Used for oil/energy fundamentals relevant to XAUUSD's inflation/real-yield
context and to broader commodity risk sentiment.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.common.cache import DiskCache
from app.common.errors import DataSourceUnavailable
from app.domain.enums import Freshness, ObservationKind
from app.domain.models import FactObservation
from app.sources.base import OfficialSourceClient, SourceClientConfig

BASE_URL = "https://api.eia.gov/v2"

# indicator key -> (route, facets, label, unit)
SERIES_CATALOG: dict[str, tuple[str, dict[str, str], str]] = {
    "us_crude_stocks": (
        "petroleum/stoc/wstk/data",
        {"facets[series][]": "WCESTUS1"},
        "thousand barrels",
    ),
    "us_wti_spot_price": (
        "petroleum/pri/spt/data",
        {"facets[series][]": "RWTC"},
        "USD/barrel",
    ),
}


class EiaClient:
    def __init__(self, api_key: str | None, cache: DiskCache) -> None:
        self.api_key = api_key
        self._http = OfficialSourceClient(
            SourceClientConfig(name="eia", default_ttl=timedelta(hours=24)),
            cache,
        )

    def close(self) -> None:
        self._http.close()

    def fetch_indicator(self, indicator: str) -> FactObservation:
        if not self.api_key:
            raise DataSourceUnavailable(
                "eia",
                "EIA_API_KEY not configured (free key: https://www.eia.gov/opendata/register.php)",
            )
        if indicator not in SERIES_CATALOG:
            raise DataSourceUnavailable("eia", f"no series mapping for indicator '{indicator}'")
        route, facets, unit = SERIES_CATALOG[indicator]
        params = {
            "api_key": self.api_key,
            "frequency": "weekly",
            "data[0]": "value",
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
            "length": "2",
            **facets,
        }
        payload = self._http.get_json(f"{BASE_URL}/{route}", cache_key=indicator, params=params)
        rows = payload.get("response", {}).get("data", [])
        if not rows:
            raise DataSourceUnavailable("eia", f"no data rows for {indicator}")
        latest = rows[0]
        previous = rows[1] if len(rows) > 1 else None
        pub_date = datetime.strptime(latest["period"], "%Y-%m-%d").replace(tzinfo=UTC)
        return FactObservation(
            indicator=indicator,
            country="US",
            asset_relevance=["XAUUSD", "USOIL"],
            source="EIA",
            source_url="https://www.eia.gov/opendata/",
            publication_timestamp=pub_date,
            observation_period=latest["period"],
            kind=ObservationKind.ACTUAL,
            value=float(latest["value"]),
            unit=unit,
            consensus=None,
            revised_previous=float(previous["value"]) if previous else None,
            freshness=Freshness.UNKNOWN,
            retrieval_timestamp=datetime.now(UTC),
        )
