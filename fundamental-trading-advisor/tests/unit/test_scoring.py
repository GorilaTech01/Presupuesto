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
    # policy_stance = clamp((4.5-2.5)*0.15) = 0.30
    # real_rate = 4.5-2.5 = 2.0; real_rate_stance = clamp((2.0-0.5)*0.3) = 0.45
    assert driver.contribution == 0.75
    assert driver.category is DriverCategory.MONETARY_POLICY


def test_score_monetary_policy_is_bounded_like_other_drivers(make_fact):
    """A very high absolute rate must NOT blow past the same +/-0.5 clamp
    every other driver uses -- this is the audited fix for the bug where
    the raw rate level dominated the whole score (see decision audit doc).
    """
    rate = make_fact("us_fed_funds_target_upper", 15.0)
    inflation = make_fact("us_cpi_yoy", 2.0)
    driver = scoring.score_monetary_policy(policy_rate=rate, headline_inflation=inflation)
    assert abs(driver.contribution) <= 1.0  # sum of two +/-0.5-clamped sub-components


def test_score_monetary_policy_shared_reference_cancels_in_differential(make_fact):
    """Two currencies scored against the same neutral-rate reference should
    produce a rate-driven differential that reflects their *relative* gap,
    not an arbitrary absolute offset from the reference choice."""
    high_rate = make_fact("us_fed_funds_target_upper", 4.0)
    low_rate = make_fact("us_fed_funds_target_upper", 2.0)
    high = scoring.score_monetary_policy(policy_rate=high_rate, headline_inflation=None)
    low = scoring.score_monetary_policy(policy_rate=low_rate, headline_inflation=None)
    assert high.contribution > low.contribution


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


def test_score_labor_does_not_drop_a_legitimate_zero_baseline(make_fact):
    """Regression test (found during the pre-push audit): a bare truthiness
    check on `revised_previous` silently skipped payrolls/JOLTS whenever the
    previous value was exactly 0.0 (falsy in Python), instead of treating 0
    as a real, present value. A -50k MoM payrolls change against a 0
    baseline must be scored, not ignored.
    """
    payrolls = make_fact("us_nonfarm_payrolls", -50, revised_previous=0)
    driver = scoring.score_labor(unemployment_rate=None, payrolls_level=payrolls, job_openings=None)
    assert driver.contribution != 0.0
    assert "payrolls change -50k" in driver.rationale

    job_openings = make_fact("us_jolts_openings", -100, revised_previous=0)
    driver2 = scoring.score_labor(
        unemployment_rate=None, payrolls_level=None, job_openings=job_openings
    )
    assert driver2.contribution != 0.0


def test_score_labor_missing_everything_is_flagged(make_fact):
    driver = scoring.score_labor(unemployment_rate=None, payrolls_level=None, job_openings=None)
    assert driver.contribution == 0.0
    assert "insufficient" in driver.rationale


def test_score_real_yield_and_dollar_rising_real_yield_is_bearish_gold(make_fact):
    real_yield = make_fact("us_real_10y_yield", 2.0)
    driver = scoring.score_real_yield_and_dollar(real_yield=real_yield, dollar_index=None)
    assert driver.contribution < 0


def test_score_real_yield_and_dollar_zero_previous_dxy_does_not_crash(make_fact):
    """A zero `revised_previous` for the dollar index would divide by zero
    if naively fixed to `is not None` without also guarding against zero --
    it must be skipped (not scored), not raise.
    """
    real_yield = make_fact("us_real_10y_yield", 2.0)
    dollar_index = make_fact("us_dollar_index_broad", 99.6, revised_previous=0)
    driver = scoring.score_real_yield_and_dollar(real_yield=real_yield, dollar_index=dollar_index)
    assert "broad USD index" not in driver.rationale


def test_score_liquidity_conditions_low_rate_is_positive_for_risk_assets(make_fact):
    rate = make_fact("us_fed_funds_target_upper", 1.0)
    driver = scoring.score_liquidity_conditions(policy_rate=rate)
    assert driver.contribution > 0


def test_score_supply_demand_missing_data(make_fact):
    driver = scoring.score_supply_demand(label="Gold", positioning=None, inventories=None)
    assert driver.contribution == 0.0


def test_score_market_expectations_is_always_zero_contribution_and_labeled():
    """No OIS/FedWatch-equivalent source is wired in this version -- this
    driver must never contribute to the score, only flag the gap so it is
    never hidden inside an aggregate number."""
    driver = scoring.score_market_expectations()
    assert driver.contribution == 0.0
    assert "EXPECTATIONS_DATA_INCOMPLETE" in driver.rationale
    assert driver.category is DriverCategory.MARKET_EXPECTATIONS
