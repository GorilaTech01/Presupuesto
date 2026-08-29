"""Domain-level exceptions used to enforce fail-closed behavior.

Any of these being raised must result in NO_TRADE or ANALYSIS_INCOMPLETE
at the pipeline boundary -- never a fabricated fallback value.
"""

from __future__ import annotations


class FundamentalAdvisorError(Exception):
    """Base class for all errors raised by this project."""


class DataSourceUnavailable(FundamentalAdvisorError):
    """A primary data source could not be reached or returned no usable data."""

    def __init__(self, source: str, detail: str) -> None:
        self.source = source
        self.detail = detail
        super().__init__(f"[{source}] unavailable: {detail}")


class StaleDataError(FundamentalAdvisorError):
    """A required observation is older than its configured freshness threshold."""

    def __init__(self, indicator: str, age_description: str) -> None:
        self.indicator = indicator
        self.age_description = age_description
        super().__init__(f"stale data for {indicator}: {age_description}")


class ConsensusUnavailable(FundamentalAdvisorError):
    """No reliable consensus figure could be found for an indicator.

    Callers should surface the literal string CONSENSUS_UNAVAILABLE rather
    than inventing a number.
    """

    def __init__(self, indicator: str) -> None:
        self.indicator = indicator
        super().__init__(f"CONSENSUS_UNAVAILABLE for {indicator}")


class SymbolNotVerifiable(FundamentalAdvisorError):
    """The broker symbol for an asset could not be resolved/verified."""

    def __init__(self, asset: str) -> None:
        self.asset = asset
        super().__init__(f"symbol not verifiable for {asset}")


class InvalidLLMResponse(FundamentalAdvisorError):
    """The LLM synthesis layer returned a response that failed validation."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"invalid LLM response: {detail}")


class AnalysisIncomplete(FundamentalAdvisorError):
    """Raised to short-circuit a pipeline run with a clear, reported reason."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"ANALYSIS_INCOMPLETE: {reason}")
