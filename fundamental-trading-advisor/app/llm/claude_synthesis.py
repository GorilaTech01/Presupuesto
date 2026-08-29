"""Optional Claude synthesis layer (section 28).

Architecture:
    DATA SOURCES -> NORMALIZED FACTS -> DETERMINISTIC VALIDATION ->
    CLAUDE ANALYSIS/SYNTHESIS -> STRUCTURED DECISION -> VALIDATOR -> OUTPUT

Claude is given already-computed, already-validated structured facts and
scores and asked only to write a short plain-English narrative explaining
them. It is never asked to produce the decision, a number, a source, or a
consensus value -- those are computed deterministically before this layer
runs. Its output is validated (see app.llm.validator) and discarded if it
fails; the pipeline's deterministic thesis text is always used regardless
of whether this layer is enabled, so the system fully functions with
ANTHROPIC_API_KEY unset.
"""

from __future__ import annotations

from app.common.errors import InvalidLLMResponse
from app.common.logging import get_logger, log_event
from app.domain.models import FundamentalDecision
from app.llm.validator import validate_llm_narrative

logger = get_logger("llm.synthesis")

SYSTEM_PROMPT = (
    "You are a macro research assistant. You will be given a JSON object of already-"
    "computed fundamental drivers, scores, and catalysts for a trading decision. Write a "
    "3-5 sentence plain-English narrative explaining the decision. Rules: (1) Use ONLY the "
    "numbers given to you, restated or compared -- never introduce a new number, source, "
    "consensus figure, or statistic. (2) Do not mention technical analysis, chart patterns, "
    "or price history. (3) Be conservative and note the main way this thesis could be wrong."
)


def _decision_facts_payload(decision: FundamentalDecision) -> dict[str, object]:
    return {
        "symbol": decision.symbol,
        "direction": decision.direction.value,
        "conviction": decision.conviction,
        "drivers": [
            {
                "category": d.category.value,
                "label": d.label,
                "contribution": d.contribution,
                "rationale": d.rationale,
            }
            for d in decision.top_drivers
        ],
        "catalysts": [
            {
                "indicator": c.indicator,
                "severity": c.severity.value,
                "consensus": c.consensus,
                "previous": c.previous,
            }
            for c in decision.catalysts
        ],
    }


def _allowed_numbers(decision: FundamentalDecision) -> set[float]:
    numbers = {float(decision.conviction)}
    for d in decision.top_drivers:
        numbers.add(round(d.contribution, 4))
    for c in decision.catalysts:
        if c.consensus is not None:
            numbers.add(c.consensus)
        if c.previous is not None:
            numbers.add(c.previous)
        if c.actual is not None:
            numbers.add(c.actual)
    return numbers


class ClaudeSynthesisClient:
    def __init__(self, api_key: str | None, model: str) -> None:
        self.api_key = api_key
        self.model = model

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def synthesize_narrative(self, decision: FundamentalDecision) -> str | None:
        """Returns a validated narrative, or None if disabled/unavailable/invalid.

        Never raises: this layer is optional and additive to the human
        report. Any failure (network, API, or validation) results in None,
        and the caller keeps using the deterministic thesis text.
        """
        if not self.enabled:
            return None
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=self.api_key)
            payload = _decision_facts_payload(decision)
            response = client.messages.create(
                model=self.model,
                max_tokens=400,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": str(payload)}],
            )
            text = "".join(block.text for block in response.content if hasattr(block, "text"))
            return validate_llm_narrative(text, _allowed_numbers(decision))
        except InvalidLLMResponse as exc:
            log_event(logger, "llm_narrative_rejected", reason=str(exc))
            return None
        except Exception as exc:  # noqa: BLE001 -- any LLM/network failure is non-fatal here
            log_event(logger, "llm_narrative_failed", error=str(exc))
            return None
