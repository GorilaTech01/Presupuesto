"""Builds explainable FundamentalScore objects for countries/currencies and
for non-FX assets (XAUUSD, BTCUSD) from normalized facts.

This module owns the mapping from "which indicators matter for this
subject" -> scoring functions. It never talks to the network directly; it
consumes a `FetchResult` from `app.sources.repository`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.domain.models import FactObservation, FundamentalScore
from app.fundamental import scoring
from app.sources.repository import FetchResult

US_INDICATORS = [
    "us_fed_funds_target_upper",
    "us_cpi_yoy",
    "us_core_cpi_yoy",
    "us_core_pce_price_index",
    "us_unemployment_rate",
    "us_nonfarm_payrolls",
    "us_jolts_openings",
    "us_real_10y_yield",
    "us_dollar_index_broad",
]

EZ_INDICATORS = [
    "ez_deposit_facility_rate",
    "ez_hicp_headline_yoy",
    "ez_hicp_core_yoy",
    "ez_unemployment_rate",
    "ez_gdp_growth_yoy",
    "ez_retail_sales_yoy",
]

CURRENCY_INDICATORS: dict[str, list[str]] = {
    "USD": US_INDICATORS,
    "EUR": EZ_INDICATORS,
}


def _cutoff(facts: list[FactObservation]) -> datetime:
    if not facts:
        return datetime.now(UTC)
    return max(f.retrieval_timestamp for f in facts)


def build_currency_score(currency: str, result: FetchResult) -> FundamentalScore:
    facts = result.facts
    relevant = set(CURRENCY_INDICATORS.get(currency, []))
    warnings = [f"missing {ind}: {err}" for ind, err in result.errors.items() if ind in relevant]

    if currency == "USD":
        drivers = [
            scoring.score_monetary_policy(
                policy_rate=facts.get("us_fed_funds_target_upper"),
                headline_inflation=facts.get("us_cpi_yoy"),
            ),
            scoring.score_inflation(
                headline=facts.get("us_cpi_yoy"),
                core=facts.get("us_core_cpi_yoy"),
            ),
            scoring.score_labor(
                unemployment_rate=facts.get("us_unemployment_rate"),
                payrolls_level=facts.get("us_nonfarm_payrolls"),
                job_openings=facts.get("us_jolts_openings"),
            ),
            scoring.score_growth(
                gdp_growth=facts.get("us_gdp_growth_annualized"),
                retail_sales=None,
            ),
            scoring.score_market_expectations(),
        ]
    elif currency == "EUR":
        drivers = [
            scoring.score_monetary_policy(
                policy_rate=facts.get("ez_deposit_facility_rate"),
                headline_inflation=facts.get("ez_hicp_headline_yoy"),
            ),
            scoring.score_inflation(
                headline=facts.get("ez_hicp_headline_yoy"),
                core=facts.get("ez_hicp_core_yoy"),
            ),
            scoring.score_labor(
                unemployment_rate=facts.get("ez_unemployment_rate"),
                payrolls_level=None,
                job_openings=None,
            ),
            scoring.score_growth(
                gdp_growth=facts.get("ez_gdp_growth_yoy"),
                retail_sales=facts.get("ez_retail_sales_yoy"),
            ),
            scoring.score_market_expectations(),
        ]
    else:
        raise ValueError(f"no scoring model defined for currency '{currency}'")

    total = round(sum(d.contribution for d in drivers), 4)
    return FundamentalScore(
        subject=currency,
        total=total,
        drivers=drivers,
        data_cutoff_utc=_cutoff(list(facts.values())),
        warnings=warnings,
    )


def build_fx_pair_bias(base_score: FundamentalScore, quote_score: FundamentalScore) -> float:
    """EUR_SCORE - USD_SCORE style differential. Positive favors the base
    currency (e.g. BUY EURUSD thesis); negative favors the quote currency.
    """
    return round(base_score.total - quote_score.total, 4)


_XAU_RELEVANT = {
    "us_real_10y_yield",
    "us_dollar_index_broad",
    "us_cpi_yoy",
    "us_core_cpi_yoy",
    "gold_net_noncommercial_positioning",
}
_BTC_RELEVANT = {"us_fed_funds_target_upper"}


def build_xau_score(result: FetchResult) -> FundamentalScore:
    facts = result.facts
    warnings = [
        f"missing {ind}: {err}" for ind, err in result.errors.items() if ind in _XAU_RELEVANT
    ]
    drivers = [
        scoring.score_real_yield_and_dollar(
            real_yield=facts.get("us_real_10y_yield"),
            dollar_index=facts.get("us_dollar_index_broad"),
        ),
        scoring.score_inflation(
            headline=facts.get("us_cpi_yoy"),
            core=facts.get("us_core_cpi_yoy"),
        ),
        scoring.score_supply_demand(
            label="Gold positioning & official-sector demand",
            positioning=facts.get("gold_net_noncommercial_positioning"),
            inventories=None,
        ),
        scoring.score_market_expectations(),
    ]
    total = round(sum(d.contribution for d in drivers), 4)
    return FundamentalScore(
        subject="XAUUSD",
        total=total,
        drivers=drivers,
        data_cutoff_utc=_cutoff(list(facts.values())),
        warnings=warnings,
    )


def build_btc_score(result: FetchResult) -> FundamentalScore:
    facts = result.facts
    warnings = [
        f"missing {ind}: {err}" for ind, err in result.errors.items() if ind in _BTC_RELEVANT
    ]
    warnings.append(
        "No verified free source for ETF flows / on-chain supply metrics is wired in this "
        "version; liquidity proxy uses Fed policy rate only (see README limitations)."
    )
    drivers = [
        scoring.score_liquidity_conditions(policy_rate=facts.get("us_fed_funds_target_upper")),
        scoring.score_market_expectations(),
    ]
    total = round(sum(d.contribution for d in drivers), 4)
    return FundamentalScore(
        subject="BTCUSD",
        total=total,
        drivers=drivers,
        data_cutoff_utc=_cutoff(list(facts.values())),
        warnings=warnings,
    )
