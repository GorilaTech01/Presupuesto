"""Shared enumerations. Keeping these centralized prevents concept-mixing
(e.g. accidentally treating a SCENARIO as a FACT) across the codebase.
"""

from __future__ import annotations

from enum import StrEnum


class ObservationKind(StrEnum):
    """What kind of value a data point represents. Never mix these."""

    ACTUAL = "ACTUAL"
    PREVIOUS = "PREVIOUS"
    REVISED = "REVISED"
    CONSENSUS = "CONSENSUS"


class AnalyticalKind(StrEnum):
    """What kind of statement a piece of analysis represents."""

    FACT = "FACT"
    INFERENCE = "INFERENCE"
    SCENARIO = "SCENARIO"
    RECOMMENDATION = "RECOMMENDATION"


class AssetClass(StrEnum):
    FX = "FX"
    METAL = "METAL"
    INDEX = "INDEX"
    CRYPTO = "CRYPTO"


class Direction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    NO_TRADE = "NO_TRADE"


class CatalystSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class DriverCategory(StrEnum):
    MONETARY_POLICY = "monetary_policy"
    INFLATION = "inflation"
    LABOR = "labor"
    GROWTH = "growth"
    LIQUIDITY = "liquidity"
    FISCAL = "fiscal"
    GEOPOLITICAL = "geopolitical"
    SUPPLY_DEMAND = "supply_demand"
    EVENT_RISK = "event_risk"
    MARKET_EXPECTATIONS = "market_expectations"


class Freshness(StrEnum):
    FRESH = "FRESH"
    AGING = "AGING"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class JournalStatus(StrEnum):
    PROPOSED = "PROPOSED"
    NOT_TRIGGERED = "NOT_TRIGGERED"
    ACTIVE_SIMULATION = "ACTIVE_SIMULATION"
    STOPPED = "STOPPED"
    TAKE_PROFIT = "TAKE_PROFIT"
    FUNDAMENTAL_EXIT = "FUNDAMENTAL_EXIT"
    TIME_EXIT = "TIME_EXIT"
    CANCELLED = "CANCELLED"


class DataSourceTier(StrEnum):
    PRIMARY_OFFICIAL = "PRIMARY_OFFICIAL"
    CONTEXT_CONSENSUS = "CONTEXT_CONSENSUS"
    NEWS_RESEARCH = "NEWS_RESEARCH"
