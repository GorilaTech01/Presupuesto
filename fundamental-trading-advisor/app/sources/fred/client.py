"""FRED (Federal Reserve Economic Data) adapter.

FRED aggregates official U.S. series (BLS, BEA, Federal Reserve Board,
Treasury) behind one free API. Requires a free API key (FRED_API_KEY) --
see https://fred.stlouisfed.org/docs/api/api_key.html. If no key is
configured this adapter raises DataSourceUnavailable rather than degrading
silently; callers must treat that as a reason to reduce confidence or
NO_TRADE, not as license to guess a value.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.common.cache import DiskCache
from app.common.errors import DataSourceUnavailable
from app.domain.enums import Freshness, ObservationKind
from app.domain.models import FactObservation
from app.sources.base import OfficialSourceClient, SourceClientConfig

BASE_URL = "https://api.stlouisfed.org/fred"

# Curated map of well-known series relevant to this project's universe.
# indicator key -> (FRED series id, human label, country, unit)
SERIES_CATALOG: dict[str, tuple[str, str, str, str]] = {
    "us_fed_funds_target_upper": ("DFEDTARU", "Fed Funds Target Rate (Upper)", "US", "percent"),
    "us_fed_funds_target_lower": ("DFEDTARL", "Fed Funds Target Rate (Lower)", "US", "percent"),
    "us_cpi_yoy": ("CPIAUCSL", "CPI YoY (derived from index)", "US", "percent"),
    "us_core_cpi_yoy": ("CPILFESL", "Core CPI YoY (derived from index)", "US", "percent"),
    "us_pce_price_index": ("PCEPI", "PCE Price Index YoY (derived from index)", "US", "percent"),
    "us_core_pce_price_index": (
        "PCEPILFE",
        "Core PCE Price Index YoY (derived from index)",
        "US",
        "percent",
    ),
    "us_unemployment_rate": ("UNRATE", "Unemployment Rate", "US", "percent"),
    "us_nonfarm_payrolls": (
        "PAYEMS",
        "Nonfarm Payrolls (level, use MoM change)",
        "US",
        "thousands",
    ),
    "us_jolts_openings": ("JTSJOL", "JOLTS Job Openings", "US", "thousands"),
    "us_initial_claims": ("ICSA", "Initial Jobless Claims", "US", "level"),
    "us_10y_yield": ("DGS10", "10-Year Treasury Yield", "US", "percent"),
    "us_2y_yield": ("DGS2", "2-Year Treasury Yield", "US", "percent"),
    "us_real_10y_yield": ("DFII10", "10-Year TIPS (real) Yield", "US", "percent"),
    "us_dollar_index_broad": ("DTWEXBGS", "Trade Weighted US Dollar Index (Broad)", "US", "index"),
}

# These are level/index series where the analytically meaningful figure is
# the year-over-year percent change, not the raw index level.
YOY_DERIVED_SERIES = {
    "us_cpi_yoy",
    "us_core_cpi_yoy",
    "us_pce_price_index",
    "us_core_pce_price_index",
}

RELEASE_IDS: dict[str, tuple[str, str]] = {
    "us_cpi_yoy": ("10", "Consumer Price Index"),
    "us_core_cpi_yoy": ("10", "Consumer Price Index"),
    "us_pce_price_index": ("54", "Personal Income and Outlays"),
    "us_core_pce_price_index": ("54", "Personal Income and Outlays"),
    "us_nonfarm_payrolls": ("50", "Employment Situation"),
    "us_unemployment_rate": ("50", "Employment Situation"),
    "us_jolts_openings": ("119", "Job Openings and Labor Turnover Survey"),
    "us_initial_claims": ("15", "Unemployment Insurance Weekly Claims Report"),
}


@dataclass
class FredObservationRaw:
    date: str
    value: str


class FredClient:
    def __init__(self, api_key: str | None, cache: DiskCache) -> None:
        self.api_key = api_key
        self._http = OfficialSourceClient(
            SourceClientConfig(name="fred", default_ttl=timedelta(hours=12)),
            cache,
        )

    def close(self) -> None:
        self._http.close()

    def _require_key(self) -> str:
        if not self.api_key:
            raise DataSourceUnavailable(
                "fred",
                "FRED_API_KEY not configured (free key: https://fred.stlouisfed.org/docs/api/api_key.html)",
            )
        return self.api_key

    def fetch_indicator(self, indicator: str) -> FactObservation:
        if indicator not in SERIES_CATALOG:
            raise DataSourceUnavailable("fred", f"no series mapping for indicator '{indicator}'")
        series_id, label, country, unit = SERIES_CATALOG[indicator]
        key = self._require_key()
        needs_yoy = indicator in YOY_DERIVED_SERIES
        limit = 15 if needs_yoy else 6
        payload = self._http.get_json(
            f"{BASE_URL}/series/observations",
            cache_key=f"obs_{series_id}",
            params={
                "series_id": series_id,
                "api_key": key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": limit,
            },
        )
        observations = payload.get("observations", [])
        numeric = [o for o in observations if o.get("value") not in (None, ".", "")]
        if not numeric:
            raise DataSourceUnavailable("fred", f"no numeric observations for {series_id}")
        latest = numeric[0]
        pub_date = datetime.strptime(latest["date"], "%Y-%m-%d").replace(tzinfo=UTC)

        if needs_yoy:
            if len(numeric) < 13:
                raise DataSourceUnavailable(
                    "fred", f"not enough history to derive YoY change for {series_id}"
                )
            latest_value = float(latest["value"])
            year_ago_value = float(numeric[12]["value"])
            yoy_now = (latest_value / year_ago_value - 1.0) * 100.0
            prev_value = float(numeric[1]["value"])
            prev_year_ago_value = float(numeric[13]["value"]) if len(numeric) > 13 else None
            yoy_prev = (
                (prev_value / prev_year_ago_value - 1.0) * 100.0 if prev_year_ago_value else None
            )
            return FactObservation(
                indicator=indicator,
                country=country,
                asset_relevance=[],
                source="FRED",
                source_url=f"https://fred.stlouisfed.org/series/{series_id}",
                publication_timestamp=pub_date,
                observation_period=latest["date"],
                kind=ObservationKind.ACTUAL,
                value=round(yoy_now, 3),
                unit=unit,
                consensus=None,
                revised_previous=round(yoy_prev, 3) if yoy_prev is not None else None,
                freshness=Freshness.UNKNOWN,
                retrieval_timestamp=datetime.now(UTC),
            )

        previous = numeric[1] if len(numeric) > 1 else None
        return FactObservation(
            indicator=indicator,
            country=country,
            asset_relevance=[],
            source="FRED",
            source_url=f"https://fred.stlouisfed.org/series/{series_id}",
            publication_timestamp=pub_date,
            observation_period=latest["date"],
            kind=ObservationKind.ACTUAL,
            value=float(latest["value"]),
            unit=unit,
            consensus=None,
            revised_previous=float(previous["value"]) if previous else None,
            freshness=Freshness.UNKNOWN,
            retrieval_timestamp=datetime.now(UTC),
        )

    def fetch_upcoming_release_dates(
        self, indicator: str, horizon_days: int = 14
    ) -> list[datetime]:
        if indicator not in RELEASE_IDS:
            return []
        release_id, _label = RELEASE_IDS[indicator]
        key = self._require_key()
        today = datetime.now(UTC).date()
        payload = self._http.get_json(
            f"{BASE_URL}/release/dates",
            cache_key=f"release_dates_{release_id}",
            params={
                "release_id": release_id,
                "api_key": key,
                "file_type": "json",
                "include_release_dates_with_no_data": "false",
                "sort_order": "asc",
                "realtime_start": today.isoformat(),
            },
        )
        dates = []
        for entry in payload.get("release_dates", []):
            d = datetime.strptime(entry["date"], "%Y-%m-%d").replace(tzinfo=UTC)
            if 0 <= (d.date() - today).days <= horizon_days:
                dates.append(d)
        return dates
