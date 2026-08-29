"""Eurostat adapter (JSON-stat 2.0 API). No API key required.

https://ec.europa.eu/eurostat/web/main/data/web-services
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.common.cache import DiskCache
from app.common.errors import DataSourceUnavailable
from app.domain.enums import Freshness, ObservationKind
from app.domain.models import FactObservation
from app.sources.base import OfficialSourceClient, SourceClientConfig

BASE_URL = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"

# indicator key -> (dataset code, extra filters, label, unit)
SERIES_CATALOG: dict[str, tuple[str, dict[str, str], str]] = {
    "ez_unemployment_rate": (
        "une_rt_m",
        {"geo": "EA20", "s_adj": "SA", "sex": "T", "age": "TOTAL", "unit": "PC_ACT"},
        "percent",
    ),
    "ez_gdp_growth_yoy": (
        "namq_10_gdp",
        {"geo": "EA20", "unit": "CLV_PCH_SM", "na_item": "B1GQ", "s_adj": "SCA"},
        "percent",
    ),
    "ez_retail_sales_yoy": (
        "sts_trtu_m",
        {"geo": "EA20", "indic_bt": "TOVV", "s_adj": "SCA", "unit": "PCH_SM"},
        "percent",
    ),
}


def _parse_jsonstat(payload: dict[str, Any]) -> list[tuple[str, float]]:
    try:
        time_dim = payload["dimension"]["time"]["category"]
        time_index = time_dim["index"]
        values = payload["value"]
        size = payload["size"]
        dim_ids = payload["id"]
        time_pos = dim_ids.index("time")
    except (KeyError, ValueError) as exc:
        raise DataSourceUnavailable("eurostat", f"unexpected JSON-stat shape: {exc}") from exc

    # With all other dimensions fixed to a single category (our filters do
    # that), the flat `value` map is indexed purely by the time dimension's
    # stride. Compute that stride from `size`.
    stride = 1
    for s in size[time_pos + 1 :]:
        stride *= s

    inv_time_index = {v: k for k, v in time_index.items()}
    results: list[tuple[str, float]] = []
    for flat_idx_str, val in values.items():
        flat_idx = int(flat_idx_str)
        t_idx = (flat_idx // stride) % size[time_pos]
        period = inv_time_index.get(t_idx)
        if period is None or val is None:
            continue
        results.append((period, float(val)))
    results.sort(key=lambda t: t[0])
    return results


class EurostatClient:
    def __init__(self, cache: DiskCache) -> None:
        self._http = OfficialSourceClient(
            SourceClientConfig(name="eurostat", default_ttl=timedelta(hours=24)),
            cache,
        )

    def close(self) -> None:
        self._http.close()

    def fetch_indicator(self, indicator: str) -> FactObservation:
        if indicator not in SERIES_CATALOG:
            raise DataSourceUnavailable(
                "eurostat", f"no dataset mapping for indicator '{indicator}'"
            )
        dataset, filters, unit = SERIES_CATALOG[indicator]
        params = {"format": "JSON", "lang": "EN", **filters}
        payload = self._http.get_json(
            f"{BASE_URL}/{dataset}",
            cache_key=indicator,
            params=params,
        )
        series = _parse_jsonstat(payload)
        if not series:
            raise DataSourceUnavailable("eurostat", f"no observations for {indicator}")
        latest_period, latest_value = series[-1]
        previous_value = series[-2][1] if len(series) > 1 else None
        return FactObservation(
            indicator=indicator,
            country="EZ",
            asset_relevance=[],
            source="Eurostat",
            source_url=f"https://ec.europa.eu/eurostat/databrowser/view/{dataset}",
            publication_timestamp=_period_to_date(latest_period),
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
    try:
        if "Q" in period:
            year_str, q = period.split("-Q")
            month = (int(q) - 1) * 3 + 1
            return datetime(int(year_str), month, 1, tzinfo=UTC)
        year_str, month_str = period.split("-")
        return datetime(int(year_str), int(month_str), 1, tzinfo=UTC)
    except ValueError:
        return datetime.now(UTC)
