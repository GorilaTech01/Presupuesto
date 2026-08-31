"""U.S. Bureau of Labor Statistics public API (v1, unregistered) adapter.

https://www.bls.gov/developers/api_signature.htm

The unregistered tier allows 25 queries/day and 10 years of data with no
API key. This is used as a cross-check against FRED (which mirrors most BLS
series); it is not the primary path because of the low daily quota.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.common.cache import DiskCache
from app.common.errors import DataSourceUnavailable
from app.domain.enums import Freshness, ObservationKind
from app.domain.models import FactObservation
from app.sources.base import OfficialSourceClient, SourceClientConfig

BASE_URL = "https://api.bls.gov/publicAPI/v1/timeseries/data"

SERIES_CATALOG: dict[str, tuple[str, str, str]] = {
    "us_cpi_index": ("CUUR0000SA0", "CPI-U, All Items (index)", "index"),
    "us_unemployment_rate_bls": ("LNS14000000", "Unemployment Rate", "percent"),
    "us_nonfarm_payrolls_bls": (
        "CES0000000001",
        "Total Nonfarm Employment (thousands)",
        "thousands",
    ),
}


class BlsClient:
    def __init__(self, cache: DiskCache) -> None:
        self._http = OfficialSourceClient(
            SourceClientConfig(name="bls", default_ttl=timedelta(hours=24)),
            cache,
        )

    def close(self) -> None:
        self._http.close()

    def fetch_indicator(self, indicator: str) -> FactObservation:
        if indicator not in SERIES_CATALOG:
            raise DataSourceUnavailable("bls", f"no series mapping for indicator '{indicator}'")
        series_id, _label, unit = SERIES_CATALOG[indicator]
        payload = self._http.get_json(
            f"{BASE_URL}/{series_id}",
            cache_key=series_id,
            params={"latest": "true"},
        )
        if payload.get("status") != "REQUEST_SUCCEEDED":
            raise DataSourceUnavailable("bls", f"request failed: {payload.get('message')}")
        try:
            series = payload["Results"]["series"][0]["data"]
        except (KeyError, IndexError) as exc:
            raise DataSourceUnavailable("bls", f"unexpected response shape: {exc}") from exc
        if not series:
            raise DataSourceUnavailable("bls", f"no data points for {series_id}")
        latest = series[0]
        previous = series[1] if len(series) > 1 else None
        period_month = latest["period"].replace("M", "").zfill(2)
        pub_date = datetime(int(latest["year"]), max(1, min(12, int(period_month))), 1, tzinfo=UTC)
        return FactObservation(
            indicator=indicator,
            country="US",
            asset_relevance=[],
            source="BLS",
            source_url=f"https://beta.bls.gov/dataViewer/view/timeseries/{series_id}",
            publication_timestamp=pub_date,
            observation_period=f"{latest['year']}-{latest['period']}",
            kind=ObservationKind.ACTUAL,
            value=float(latest["value"]),
            unit=unit,
            consensus=None,
            revised_previous=float(previous["value"]) if previous else None,
            freshness=Freshness.UNKNOWN,
            retrieval_timestamp=datetime.now(UTC),
        )
