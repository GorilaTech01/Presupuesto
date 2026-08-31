"""Freshness classification for fundamental indicators.

Each indicator has a natural release cadence (daily rate, monthly CPI,
quarterly GDP, weekly claims...). An observation is classified relative to
that cadence rather than a single global threshold.
"""

from __future__ import annotations

from datetime import timedelta

from app.common.time_utils import age
from app.domain.enums import Freshness
from app.domain.models import FactObservation

# indicator -> (fresh_within, aging_within); beyond aging_within => STALE
_CADENCE: dict[str, tuple[timedelta, timedelta]] = {
    "us_fed_funds_target_upper": (timedelta(days=45), timedelta(days=90)),
    "us_fed_funds_target_lower": (timedelta(days=45), timedelta(days=90)),
    "ez_deposit_facility_rate": (timedelta(days=45), timedelta(days=90)),
    "ez_main_refinancing_rate": (timedelta(days=45), timedelta(days=90)),
    "us_cpi_yoy": (timedelta(days=40), timedelta(days=70)),
    "us_core_cpi_yoy": (timedelta(days=40), timedelta(days=70)),
    "us_pce_price_index": (timedelta(days=40), timedelta(days=70)),
    "us_core_pce_price_index": (timedelta(days=40), timedelta(days=70)),
    "ez_hicp_headline_yoy": (timedelta(days=40), timedelta(days=70)),
    "ez_hicp_core_yoy": (timedelta(days=40), timedelta(days=70)),
    "us_unemployment_rate": (timedelta(days=40), timedelta(days=70)),
    "us_nonfarm_payrolls": (timedelta(days=40), timedelta(days=70)),
    "us_jolts_openings": (timedelta(days=45), timedelta(days=75)),
    "us_initial_claims": (timedelta(days=10), timedelta(days=20)),
    "us_10y_yield": (timedelta(days=5), timedelta(days=10)),
    "us_2y_yield": (timedelta(days=5), timedelta(days=10)),
    "us_real_10y_yield": (timedelta(days=5), timedelta(days=10)),
    "us_dollar_index_broad": (timedelta(days=5), timedelta(days=10)),
    "ez_unemployment_rate": (timedelta(days=40), timedelta(days=70)),
    "ez_gdp_growth_yoy": (timedelta(days=100), timedelta(days=160)),
    "ez_retail_sales_yoy": (timedelta(days=45), timedelta(days=75)),
    "us_wti_spot_price": (timedelta(days=10), timedelta(days=20)),
    "us_crude_stocks": (timedelta(days=10), timedelta(days=20)),
    "eur_net_noncommercial_positioning": (timedelta(days=10), timedelta(days=20)),
    "gold_net_noncommercial_positioning": (timedelta(days=10), timedelta(days=20)),
}

_DEFAULT_CADENCE = (timedelta(days=30), timedelta(days=60))


def classify(observation: FactObservation) -> Freshness:
    fresh_within, aging_within = _CADENCE.get(observation.indicator, _DEFAULT_CADENCE)
    data_age = age(observation.publication_timestamp)
    if data_age <= fresh_within:
        return Freshness.FRESH
    if data_age <= aging_within:
        return Freshness.AGING
    return Freshness.STALE
