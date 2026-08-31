from __future__ import annotations

from app.fundamental import analysis
from app.sources.repository import FetchResult


def test_build_currency_score_filters_warnings_to_own_indicators(make_fact):
    result = FetchResult(
        facts={
            "us_fed_funds_target_upper": make_fact("us_fed_funds_target_upper", 4.0),
            "us_cpi_yoy": make_fact("us_cpi_yoy", 2.9),
        },
        errors={
            "us_unemployment_rate": "boom",
            "ez_hicp_headline_yoy": "should not leak into USD warnings",
        },
    )
    score = analysis.build_currency_score("USD", result)
    assert any("us_unemployment_rate" in w for w in score.warnings)
    assert not any("ez_hicp_headline_yoy" in w for w in score.warnings)


def test_build_fx_pair_bias_sign(make_fact):
    result_eur = FetchResult(
        facts={"ez_deposit_facility_rate": make_fact("ez_deposit_facility_rate", 4.0)}, errors={}
    )
    result_usd = FetchResult(
        facts={"us_fed_funds_target_upper": make_fact("us_fed_funds_target_upper", 1.0)}, errors={}
    )
    eur_score = analysis.build_currency_score("EUR", result_eur)
    usd_score = analysis.build_currency_score("USD", result_usd)
    bias = analysis.build_fx_pair_bias(eur_score, usd_score)
    assert bias > 0  # EUR more hawkish -> bias favors EUR (BUY EURUSD)


def test_build_xau_score_warnings_scoped_to_xau_indicators(make_fact):
    result = FetchResult(
        facts={"us_real_10y_yield": make_fact("us_real_10y_yield", 1.5)},
        errors={"us_nonfarm_payrolls": "irrelevant to gold", "us_dollar_index_broad": "missing"},
    )
    score = analysis.build_xau_score(result)
    assert any("us_dollar_index_broad" in w for w in score.warnings)
    assert not any("us_nonfarm_payrolls" in w for w in score.warnings)


def test_build_btc_score_always_notes_limitation(make_fact):
    result = FetchResult(
        facts={"us_fed_funds_target_upper": make_fact("us_fed_funds_target_upper", 2.0)}, errors={}
    )
    score = analysis.build_btc_score(result)
    assert any("ETF flows" in w for w in score.warnings)
