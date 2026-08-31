"""Validates LLM narrative output against the deterministic facts it was
given (section 28/33): Claude may synthesize and explain, but every number
it states must trace back to something the pipeline already computed. If a
narrative introduces a number we can't find in the allowed set, we discard
the narrative entirely and fall back to the deterministic thesis text --
we never let an ungrounded LLM claim reach the user.
"""

from __future__ import annotations

import re

from app.common.errors import InvalidLLMResponse

_NUMBER_RE = re.compile(r"-?\d+\.\d+|-?\d{2,}")


def extract_numbers(text: str) -> set[float]:
    return {float(m) for m in _NUMBER_RE.findall(text)}


def validate_llm_narrative(
    narrative: str, allowed_numbers: set[float], *, tolerance: float = 0.05
) -> str:
    if not narrative or not narrative.strip():
        raise InvalidLLMResponse("empty narrative")
    found = extract_numbers(narrative)
    for value in found:
        if not any(
            abs(value - allowed) <= tolerance * max(1.0, abs(allowed))
            for allowed in allowed_numbers
        ):
            raise InvalidLLMResponse(
                f"narrative contains an ungrounded number ({value}) not present in the "
                "structured facts/scores/decision it was given"
            )
    return narrative.strip()
