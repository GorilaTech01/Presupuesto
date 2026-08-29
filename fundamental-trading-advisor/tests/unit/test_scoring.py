from __future__ import annotations

from app.domain.enums import DriverCategory
from app.fundamental import scoring


def test_score_monetary_policy_missing_data_returns_zero_contribution():
    driver = scoring.score_monetary_policy(policy_rate=None, headline_inflation=None)
    assert driver.contribution == 0.0
    assert "insufficient" in driver.rationale


def test_score_monetary_policy_uses_real_rate(make_fact):
    rate = make_fact("us_fed_funds_target_upper", 4.5)
    inflation = make_fact("us_cpi_yoy", 2.5)
    driver = scoring.score_monetary_policy(policy_rate=rate, headline_inflation=inflation)
    # nominal 4.5 + real (4.5-2.5)*0.5 = 4.5 + 1.0 = 5.5
    assert driver.contribution == 5.5
    assert driver.category is DriverCategory.MONETARY_POLICY


def test_score_inflation_above_target_is_positive(make_fact):
    core = make_fact("us_core_cpi_yoy", 3.5)
    driver = scoring.score_inflation(headline=None, core=core)
    assert driver.contribution > 0


def test_score_inflation_at_target_is_zero(make_fact):
    core = make_fact("us_core_cpi_yoy", 2.0)
    driver = scoring.score_inflation(headline=None, core=core)
    assert driver.contribution == 0.0


def test_score_inflation_below_target_is_negative(make_fact):
    core = make_fact("us_core_cpi_yoy", 1.0)
    driver = scoring.score_inflation(headline=None, core=core)
    assert driver.contribution < 0


def test_score_labor_improving_market_is_positive(make_fact):
    unemployment = make_fact("us_unemployment_rate", 3.8, revised_previous=4.0)
    payrolls = make_fact("us_nonfarm_payrolls", 158_000, revised_previous=150_000)
    driver = scoring.score_labor(
        unemployment_rate=unemployment, payrolls_level=payrolls, job_openings=None
    )
    assert driver.contribution > 0


def test_score_labor_missing_everything_is_flagged(make_fact):
    driver = scoring.score_labor(unemployment_rate=None, payrolls_level=None, job_openings=None)
    assert driver.contribution == 0.0
    assert "insufficient" in driver.rationale


def test_score_real_yield_and_dollar_rising_real_yield_is_bearish_gold(make_fact):
    real_yield = make_fact("us_real_10y_yield", 2.0)
    driver = scoring.score_real_yield_and_dollar(real_yield=real_yield, dollar_index=None)
    assert driver.contribution < 0


def test_score_liquidity_conditions_low_rate_is_positive_for_risk_assets(make_fact):
    rate = make_fact("us_fed_funds_target_upper", 1.0)
    driver = scoring.score_liquidity_conditions(policy_rate=rate)
    assert driver.contribution > 0


def test_score_supply_demand_missing_data(make_fact):
    driver = scoring.score_supply_demand(label="Gold", positioning=None, inventories=None)
    assert driver.contribution == 0.0
