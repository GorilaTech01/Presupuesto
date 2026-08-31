from __future__ import annotations

import pytest

from app.common.errors import InvalidLLMResponse
from app.llm.validator import extract_numbers, validate_llm_narrative


def test_extract_numbers_finds_decimals_and_integers():
    numbers = extract_numbers("The score is 4.50 with conviction 82 and rate 150")
    assert 4.50 in numbers
    assert 82 in numbers
    assert 150 in numbers


def test_validate_accepts_narrative_using_only_allowed_numbers():
    narrative = "Conviction is 82 out of 100, driven by a rate differential of 4.50."
    result = validate_llm_narrative(narrative, allowed_numbers={82.0, 4.50, 100.0})
    assert "82" in result


def test_validate_rejects_ungrounded_number():
    narrative = "This will definitely return 25% next week."
    with pytest.raises(InvalidLLMResponse):
        validate_llm_narrative(narrative, allowed_numbers={82.0})


def test_validate_rejects_empty_narrative():
    with pytest.raises(InvalidLLMResponse):
        validate_llm_narrative("   ", allowed_numbers=set())


def test_validate_tolerates_rounding_within_tolerance():
    narrative = "Conviction near 82."
    result = validate_llm_narrative(narrative, allowed_numbers={81.6}, tolerance=0.01)
    assert result
