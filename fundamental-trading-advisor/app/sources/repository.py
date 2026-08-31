"""Aggregates every source adapter behind one fetch surface.

This is the boundary between "DATA SOURCES" and "NORMALIZED FACTS" in the
architecture diagram. It never invents a value: any adapter failure is
recorded per-indicator and surfaced to the caller so the fundamental
analysis / decision layers can decide how to react (reduce confidence,
NO_TRADE, etc.) instead of silently continuing with partial data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.common.cache import DiskCache
from app.common.errors import DataSourceUnavailable
from app.common.logging import get_logger, log_event
from app.config.settings import Settings
from app.domain.models import FactObservation
from app.sources.bea.client import BeaClient
from app.sources.bls.client import BlsClient
from app.sources.cftc.client import CftcClient
from app.sources.ecb.client import EcbClient
from app.sources.eia.client import EiaClient
from app.sources.eurostat.client import EurostatClient
from app.sources.fred.client import FredClient
from app.sources.freshness import classify
from app.sources.ism.client import IsmClient

logger = get_logger("sources.repository")

# indicator -> adapter name that owns it (first-class / primary path)
_OWNER: dict[str, str] = {
    "us_fed_funds_target_upper": "fred",
    "us_fed_funds_target_lower": "fred",
    "us_cpi_yoy": "fred",
    "us_core_cpi_yoy": "fred",
    "us_pce_price_index": "fred",
    "us_core_pce_price_index": "fred",
    "us_unemployment_rate": "fred",
    "us_nonfarm_payrolls": "fred",
    "us_jolts_openings": "fred",
    "us_initial_claims": "fred",
    "us_10y_yield": "fred",
    "us_2y_yield": "fred",
    "us_real_10y_yield": "fred",
    "us_dollar_index_broad": "fred",
    "ez_deposit_facility_rate": "ecb",
    "ez_main_refinancing_rate": "ecb",
    "ez_hicp_headline_yoy": "ecb",
    "ez_hicp_core_yoy": "ecb",
    "ez_unemployment_rate": "eurostat",
    "ez_gdp_growth_yoy": "eurostat",
    "ez_retail_sales_yoy": "eurostat",
    "us_wti_spot_price": "eia",
    "us_crude_stocks": "eia",
    "eur_net_noncommercial_positioning": "cftc",
    "gold_net_noncommercial_positioning": "cftc",
    "us_ism_manufacturing_pmi": "ism",
    "us_ism_services_pmi": "ism",
    "us_ism_manufacturing_employment": "ism",
    "us_gdp_growth_annualized": "bea",
}


class IndicatorSource(Protocol):
    def fetch_indicator(self, indicator: str) -> FactObservation: ...


class CloseableSource(Protocol):
    def close(self) -> None: ...


@dataclass
class FetchResult:
    facts: dict[str, FactObservation] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    def missing(self, indicators: list[str]) -> list[str]:
        return [i for i in indicators if i not in self.facts]


class FundamentalDataRepository:
    def __init__(self, settings: Settings, cache: DiskCache | None = None) -> None:
        self.settings = settings
        self.cache = cache or DiskCache(settings.cache_dir)
        self.fred = FredClient(settings.fred_api_key, self.cache)
        self.ecb = EcbClient(self.cache)
        self.eurostat = EurostatClient(self.cache)
        self.bls = BlsClient(self.cache)
        self.eia = EiaClient(settings.eia_api_key, self.cache)
        self.cftc = CftcClient(self.cache)
        self.ism = IsmClient()
        self.bea = BeaClient()
        self._adapters: dict[str, IndicatorSource] = {
            "fred": self.fred,
            "ecb": self.ecb,
            "eurostat": self.eurostat,
            "bls": self.bls,
            "eia": self.eia,
            "cftc": self.cftc,
            "ism": self.ism,
            "bea": self.bea,
        }
        self._closeable: list[CloseableSource] = [
            self.fred,
            self.ecb,
            self.eurostat,
            self.bls,
            self.eia,
            self.cftc,
        ]

    def close(self) -> None:
        for adapter in self._closeable:
            adapter.close()

    def fetch_one(self, indicator: str) -> FactObservation:
        owner = _OWNER.get(indicator)
        if owner is None:
            raise DataSourceUnavailable("repository", f"unknown indicator '{indicator}'")
        adapter = self._adapters[owner]
        observation = adapter.fetch_indicator(indicator)
        return observation.model_copy(update={"freshness": classify(observation)})

    def fetch_many(self, indicators: list[str]) -> FetchResult:
        result = FetchResult()
        for indicator in indicators:
            try:
                result.facts[indicator] = self.fetch_one(indicator)
            except DataSourceUnavailable as exc:
                result.errors[indicator] = str(exc)
                log_event(logger, "indicator_unavailable", indicator=indicator, error=str(exc))
        return result
