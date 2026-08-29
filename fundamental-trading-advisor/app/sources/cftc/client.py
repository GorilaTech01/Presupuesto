"""CFTC Commitments of Traders (COT) adapter.

No API key required. Uses the public Socrata dataset for the legacy
futures-only report. Used only for positioning context (market_expectations
driver), never as a directional technical signal.
https://publicreporting.cftc.gov/resource/6dca-aqww.json
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.common.cache import DiskCache
from app.common.errors import DataSourceUnavailable
from app.domain.enums import Freshness, ObservationKind
from app.domain.models import FactObservation
from app.sources.base import OfficialSourceClient, SourceClientConfig

BASE_URL = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"

# indicator key -> CFTC_Contract_Market_Name filter value
CONTRACT_CATALOG: dict[str, str] = {
    "eur_net_noncommercial_positioning": "EURO FX - CHICAGO MERCANTILE EXCHANGE",
    "gold_net_noncommercial_positioning": "GOLD - COMMODITY EXCHANGE INC.",
}


class CftcClient:
    def __init__(self, cache: DiskCache) -> None:
        self._http = OfficialSourceClient(
            SourceClientConfig(name="cftc", default_ttl=timedelta(hours=24)),
            cache,
        )

    def close(self) -> None:
        self._http.close()

    def fetch_indicator(self, indicator: str) -> FactObservation:
        if indicator not in CONTRACT_CATALOG:
            raise DataSourceUnavailable("cftc", f"no contract mapping for indicator '{indicator}'")
        contract_name = CONTRACT_CATALOG[indicator]
        params = {
            "$where": f"market_and_exchange_names='{contract_name}'",
            "$order": "report_date_as_yyyy_mm_dd DESC",
            "$limit": "2",
        }
        rows = self._http.get_json(BASE_URL, cache_key=indicator, params=params)
        if not rows:
            raise DataSourceUnavailable("cftc", f"no rows for {indicator}")
        latest = rows[0]
        previous = rows[1] if len(rows) > 1 else None
        try:
            net_long = float(latest["noncomm_positions_long_all"]) - float(
                latest["noncomm_positions_short_all"]
            )
            prev_net_long = (
                float(previous["noncomm_positions_long_all"])
                - float(previous["noncomm_positions_short_all"])
                if previous
                else None
            )
        except (KeyError, ValueError) as exc:
            raise DataSourceUnavailable("cftc", f"unexpected row shape: {exc}") from exc
        pub_date = datetime.strptime(latest["report_date_as_yyyy_mm_dd"][:10], "%Y-%m-%d").replace(
            tzinfo=UTC
        )
        return FactObservation(
            indicator=indicator,
            country="US",
            asset_relevance=[],
            source="CFTC",
            source_url="https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm",
            publication_timestamp=pub_date,
            observation_period=latest["report_date_as_yyyy_mm_dd"][:10],
            kind=ObservationKind.ACTUAL,
            value=net_long,
            unit="net non-commercial contracts",
            consensus=None,
            revised_previous=prev_net_long,
            freshness=Freshness.UNKNOWN,
            retrieval_timestamp=datetime.now(UTC),
        )
