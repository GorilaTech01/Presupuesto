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
    """The fundamental bias/call. NOT, by itself, a statement that a
    position should be entered right now -- see `ExecutionReadiness`.
    """

    BUY = "BUY"
    SELL = "SELL"
    NO_TRADE = "NO_TRADE"


class ExecutionReadiness(StrEnum):
    """Whether a `Direction` bias is currently executable.

    Added after the pre-push audit (docs/decision_audit_eurusd_2026-08-31.md,
    section 7): BUY/SELL must not be read as "enter immediately" when a
    CRITICAL catalyst is still pending -- that case is WAIT_FOR_TRIGGER, not
    ENTER_NOW, even though `direction` is already BUY or SELL.
    """

    ENTER_NOW = "ENTER_NOW"
    WAIT_FOR_TRIGGER = "WAIT_FOR_TRIGGER"
    NONE = "NONE"


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


class FundamentalBias(StrEnum):
    """The directional lean of a *monitored* opportunity (V1.1 monitoring
    layer, docs/monitoring.md). Distinct from `Direction`: `Direction` is
    the one-shot weekly call (BUY/SELL/NO_TRADE); `FundamentalBias` is a
    monitored opportunity's current directional read, which can exist
    (BULLISH/BEARISH) even while `TradeAction` is still WAIT.
    """

    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class TradeAction(StrEnum):
    """The *operational* status of a monitored opportunity over time.

    Never conflate this with `FundamentalBias`: a BEARISH bias can sit at
    WAIT for weeks while a catalyst is pending. BUY/SELL is not a
    `TradeAction` value -- the executable direction, once READY_TO_TRADE,
    comes from the opportunity's `Direction` (via its trade plan), not from
    this enum. This is unrelated to `ExecutionReadiness`, which is a
    single-run (weekly) concept; this one is a persisted opportunity's
    lifecycle state.
    """

    WAIT = "WAIT"
    READY_TO_TRADE = "READY_TO_TRADE"
    NO_TRADE = "NO_TRADE"
    CANCELLED = "CANCELLED"


class TriggerStatus(StrEnum):
    """Whether the fundamental catalysts required by an opportunity's
    thesis have resolved, per `FundamentalTriggerEvaluator`."""

    PENDING = "PENDING"
    PARTIALLY_CONFIRMED = "PARTIALLY_CONFIRMED"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
