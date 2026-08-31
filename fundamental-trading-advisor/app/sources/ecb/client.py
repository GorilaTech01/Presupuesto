"""European Central Bank Data Portal (SDW) adapter.

No API key required. Uses the SDMX-JSON REST API:
https://data.ecb.europa.eu/help/api/data
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.common.cache import DiskCache
from app.common.errors import DataSourceUnavailable
from app.domain.enums import Freshness, ObservationKind
from app.domain.models import FactObservation
from app.sources.base import OfficialSourceClient, SourceClientConfig

BASE_URL = "https://data-api.ecb.europa.eu/service/data"

# indicator key -> (flow/key path, label, unit)
SERIES_CATALOG: dict[str, tuple[str, str, str]] = {
    "ez_deposit_facility_rate": (
        "FM/D.U2.EUR.4F.KR.DFR.LEV",
        "ECB Deposit Facility Rate",
        "percent",
    ),
    "ez_main_refinancing_rate": (
        "FM/D.U2.EUR.4F.KR.MRR_FR.LEV",
        "ECB Main Refinancing Rate",
        "percent",
    ),
    "ez_hicp_headline_yoy": ("ICP/M.U2.N.000000.4.ANR", "Eurozone HICP YoY", "percent"),
    "ez_hicp_core_yoy": (
        "ICP/M.U2.N.XEF000.4.ANR",
        "Eurozone HICP ex food & energy YoY",
        "percent",
    ),
}


def _parse_sdmx_json(payload: dict[str, Any]) -> list[tuple[str, float]]:
    """Return [(period, value), ...] sorted by period ascending."""
    try:
        datasets = payload["dataSets"]
        if not datasets:
            return []
        series_map = datasets[0]["series"]
        if not series_map:
            return []
        first_series_key = next(iter(series_map))
        observations = series_map[first_series_key]["observations"]
        time_values = payload["structure"]["dimensions"]["observation"][0]["values"]
    except (KeyError, IndexError, StopIteration) as exc:
        raise DataSourceUnavailable("ecb", f"unexpected SDMX-JSON shape: {exc}") from exc

    results: list[tuple[str, float]] = []
    for idx_str, obs_value in observations.items():
        idx = int(idx_str)
        if idx >= len(time_values):
            continue
        period = time_values[idx]["id"]
        value = obs_value[0] if isinstance(obs_value, list) else obs_value
        if value is None:
            continue
        results.append((period, float(value)))
    results.sort(key=lambda t: t[0])
    return results


class EcbClient:
    def __init__(self, cache: DiskCache) -> None:
        self._http = OfficialSourceClient(
            SourceClientConfig(name="ecb", default_ttl=timedelta(hours=12)),
            cache,
        )

    def close(self) -> None:
        self._http.close()

    def fetch_indicator(self, indicator: str) -> FactObservation:
        if indicator not in SERIES_CATALOG:
            raise DataSourceUnavailable("ecb", f"no series mapping for indicator '{indicator}'")
        key_path, label, unit = SERIES_CATALOG[indicator]
        payload = self._http.get_json(
            f"{BASE_URL}/{key_path}",
            cache_key=indicator,
            params={"format": "jsondata", "lastNObservations": 6},
            headers={"Accept": "application/json"},
        )
        series = _parse_sdmx_json(payload)
        if not series:
            raise DataSourceUnavailable("ecb", f"no observations for {indicator}")
        latest_period, latest_value = series[-1]
        previous_value = series[-2][1] if len(series) > 1 else None
        pub_date = _period_to_date(latest_period)
        return FactObservation(
            indicator=indicator,
            country="EZ",
            asset_relevance=[],
            source="ECB Data Portal (SDW)",
            source_url=f"https://data.ecb.europa.eu/data/datasets/{key_path.split('/')[0]}",
            publication_timestamp=pub_date,
            observation_period=latest_period,
            kind=ObservationKind.ACTUAL,
            value=latest_value,
            unit=unit,
            consensus=None,
            revised_previous=previous_value,
            freshness=Freshness.UNKNOWN,
            retrieval_timestamp=datetime.now(UTC),
        )


def _period_to_date(period: str) -> datetime:
    if "-" in period and len(period.split("-")[1]) == 2 and "Q" not in period:
        year, month = period.split("-")
        return datetime(int(year), int(month), 1, tzinfo=UTC)
    try:
        return datetime.strptime(period, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return datetime.now(UTC)
