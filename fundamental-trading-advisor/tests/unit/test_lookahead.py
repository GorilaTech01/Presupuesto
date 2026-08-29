from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.common.lookahead import assert_no_lookahead, find_lookahead_violations


def test_no_violations_when_all_facts_precede_decision_time(make_fact):
    decision_time = datetime(2026, 8, 29, tzinfo=UTC)
    facts = [
        make_fact("us_cpi_yoy", 3.4, publication_timestamp=decision_time - timedelta(days=17)),
        make_fact(
            "us_fed_funds_target_upper",
            3.75,
            publication_timestamp=decision_time - timedelta(days=31),
        ),
    ]
    assert find_lookahead_violations(facts, decision_time) == []
    assert_no_lookahead(facts, decision_time)  # must not raise


def test_violation_detected_for_future_fact(make_fact):
    decision_time = datetime(2026, 8, 29, tzinfo=UTC)
    future_fact = make_fact(
        "us_nonfarm_payrolls", 90, publication_timestamp=decision_time + timedelta(days=6)
    )
    violations = find_lookahead_violations([future_fact], decision_time)
    assert len(violations) == 1
    assert violations[0].indicator == "us_nonfarm_payrolls"


def test_assert_no_lookahead_raises_and_names_the_indicator(make_fact):
    decision_time = datetime(2026, 8, 29, tzinfo=UTC)
    future_fact = make_fact(
        "us_nonfarm_payrolls", 90, publication_timestamp=decision_time + timedelta(days=6)
    )
    with pytest.raises(ValueError, match="us_nonfarm_payrolls"):
        assert_no_lookahead([future_fact], decision_time)


def test_fact_published_exactly_at_decision_time_is_allowed(make_fact):
    decision_time = datetime(2026, 8, 29, tzinfo=UTC)
    fact = make_fact("us_cpi_yoy", 3.4, publication_timestamp=decision_time)
    assert find_lookahead_violations([fact], decision_time) == []
