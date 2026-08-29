"""Explainable fundamental scoring primitives.

Every scoring function below returns a `DriverScore` whose `contribution`
is a plain, auditable number computed from one or more `FactObservation`s
using documented thresholds -- never a hidden/opaque formula. When the
facts needed for a category are missing, the function returns a
zero-contribution driver that says exactly what was missing, rather than
guessing. `FundamentalScore.total` is validated (see domain.models) to
always equal the sum of driver contributions, so nothing can be added to
the headline score without an explainable driver behind it.

Sign convention: a positive contribution means "more fundamentally
attractive for holding this currency / asset over the horizon", i.e. more
hawkish central bank, stronger labor market, stronger growth. For
inflation, the convention is documented per-function since inflation is not
monotonically bullish or bearish for a currency.

MAGNITUDE CONVENTION (audited 2026-08-29, see docs/decision_audit_eurusd_2026-08-31.md):
Every driver in this module is deliberately clamped to roughly the same
order of magnitude (+/-0.2 to +/-0.5 per sub-component) so that no single
category can mechanically dominate a FundamentalScore just because its raw
unit happens to be a bigger number than another category's. `score_labor`,
`score_growth`, `score_liquidity_conditions`, `score_real_yield_and_dollar`
and `score_supply_demand` all measure a *change* or a *deviation from a
reference point*, scaled down and clamped. `score_monetary_policy` was
originally the one exception -- it added the raw policy-rate level (e.g.
3.75) directly to the score, which is 10-20x larger than every other
driver's contribution and therefore silently reduced the whole model to
"whoever has the higher nominal rate wins", no matter what inflation,
labor, or growth said. That bug is fixed below: monetary policy is now
scored the same way as every other driver, as a bounded deviation from a
neutral reference.

A second, unrelated bug was found while writing that audit: `score_labor`
and `score_real_yield_and_dollar` guarded their `revised_previous`-based
branches with a bare truthiness check (`and payrolls_level.revised_previous`)
instead of `is not None`. Since 0.0 is falsy in Python, a legitimate
previous value of exactly zero silently skipped the whole branch instead of
being used -- e.g. an NFP "MoM change" fact modeled with a zero baseline
had its entire contribution dropped without any warning. Fixed by checking
`is not None` explicitly everywhere a revised_previous is consumed (the
dollar-index branch additionally guards against a zero denominator, since
that value is also used to compute a percent change).
"""

from __future__ import annotations

from app.domain.enums import DriverCategory
from app.domain.models import DriverScore, FactObservation

MISSING_DATA_NOTE = "insufficient/unavailable data for this category"

# Approximate, cross-economy neutral-rate references used only to turn an
# absolute rate level into a bounded "how far from neutral" signal -- NOT a
# claim that the Fed's and ECB's true r* are identical. Documented as a
# simplification: a more accurate model would use each central bank's own
# published/estimated neutral rate. Because both currencies in a pair are
# scored against the *same* constant, using one shared reference does not
# by itself bias the pair toward either currency; it only affects how much
# of the true differential gets clipped by the +/-0.5 bound below.
NEUTRAL_NOMINAL_RATE_REFERENCE = 2.5
NEUTRAL_REAL_RATE_REFERENCE = 0.5
POLICY_STANCE_SCALE = 0.15
REAL_RATE_SCALE = 0.3
_DRIVER_CLAMP = 0.5


def _missing(category: DriverCategory, label: str, detail: str) -> DriverScore:
    return DriverScore(
        category=category,
        label=label,
        contribution=0.0,
        rationale=f"{MISSING_DATA_NOTE}: {detail}",
        supporting_facts=[],
    )


def score_monetary_policy(
    *,
    policy_rate: FactObservation | None,
    headline_inflation: FactObservation | None,
) -> DriverScore:
    """Policy stance relative to a neutral reference, on the same bounded
    scale as every other driver in this module (see MAGNITUDE CONVENTION in
    the module docstring). Two bounded sub-components, each clamped to
    +/-0.5:

    1. `policy_stance`: how far the *nominal* policy rate sits above/below
       an approximate neutral nominal rate -- a rate meaningfully above
       neutral is a hawkish/currency-supportive stance.
    2. `real_rate_stance`: how far the *real* policy rate (nominal rate -
       headline inflation) sits above/below an approximate neutral real
       rate (r*) -- a restrictive real rate is currency-supportive.

    This intentionally does NOT use the raw rate level as the score (that
    was the pre-audit bug): a 3.75% rate and a 2.25% rate are each turned
    into a small, bounded deviation from a shared reference, not a 1.5-point
    swing that would dwarf every other category.
    """
    if policy_rate is None:
        return _missing(DriverCategory.MONETARY_POLICY, "Policy rate", "no policy rate observation")
    facts = [f"{policy_rate.source}:{policy_rate.indicator}={policy_rate.value}{policy_rate.unit}"]
    stance_raw = (policy_rate.value or 0.0) - NEUTRAL_NOMINAL_RATE_REFERENCE
    policy_stance = max(-_DRIVER_CLAMP, min(_DRIVER_CLAMP, stance_raw * POLICY_STANCE_SCALE))
    rationale = (
        f"Policy rate {policy_rate.value:.2f}% vs. ~{NEUTRAL_NOMINAL_RATE_REFERENCE:.1f}% "
        f"neutral reference (deviation {stance_raw:+.2f}pp) -> {policy_stance:+.2f} "
        "(nominal stance)."
    )
    real_rate_stance = 0.0
    if headline_inflation is not None and headline_inflation.value is not None:
        real_rate = (policy_rate.value or 0.0) - headline_inflation.value
        real_dev = real_rate - NEUTRAL_REAL_RATE_REFERENCE
        real_rate_stance = max(-_DRIVER_CLAMP, min(_DRIVER_CLAMP, real_dev * REAL_RATE_SCALE))
        facts.append(
            f"{headline_inflation.source}:{headline_inflation.indicator}="
            f"{headline_inflation.value}{headline_inflation.unit}"
        )
        rationale += (
            f" Real policy rate ~{real_rate:+.2f}pp vs. ~{NEUTRAL_REAL_RATE_REFERENCE:.1f}% "
            f"neutral real-rate reference (deviation {real_dev:+.2f}pp) -> "
            f"{real_rate_stance:+.2f} (real-rate stance)."
        )
    else:
        rationale += " Real-rate component skipped: no headline inflation observation."
    return DriverScore(
        category=DriverCategory.MONETARY_POLICY,
        label="Policy rate & real-rate stance (vs. neutral reference)",
        contribution=round(policy_stance + real_rate_stance, 4),
        rationale=rationale,
        supporting_facts=facts,
    )


def score_market_expectations(*, expectations_available: bool = False) -> DriverScore:
    """Placeholder for the forward-looking policy-path driver (section 3 of
    the audit): whether markets are pricing further hikes/cuts, and how far
    current data has already been "priced in". No free, reliable OIS/
    Fed-Funds-futures/FedWatch-equivalent feed is wired in this version (see
    README limitations), so this always returns a zero-contribution,
    explicitly labeled EXPECTATIONS_DATA_INCOMPLETE driver rather than
    inferring a forward path from the current rate alone. The decision
    engine applies a separate, fixed conviction penalty for this same gap
    (see `FundamentalDecisionEngine`), so the gap is never silently hidden
    inside an aggregate score.
    """
    if expectations_available:  # pragma: no cover -- no implementation wired yet
        raise NotImplementedError("no expectations data source is wired in this version")
    return DriverScore(
        category=DriverCategory.MARKET_EXPECTATIONS,
        label="Forward policy-path expectations",
        contribution=0.0,
        rationale=(
            "EXPECTATIONS_DATA_INCOMPLETE: no OIS/Fed-funds-futures/FedWatch-equivalent "
            "forward-path data source is implemented in this version. This driver reflects "
            "CURRENT policy only; it cannot say how much of it is already priced in or "
            "whether a hike/cut is expected at the next meeting. Conviction is reduced "
            "accordingly (see conviction breakdown)."
        ),
        supporting_facts=[],
    )


def score_inflation(
    *,
    headline: FactObservation | None,
    core: FactObservation | None,
    target: float = 2.0,
) -> DriverScore:
    """Inflation is scored as distance above/below the ~2% central-bank
    target. Inflation persistently ABOVE target pressures the central bank
    toward a hawkish/restrictive stance -> treated as a mild POSITIVE for
    currency attractiveness (keeps real rates a live issue, tightening
    bias), while inflation AT or BELOW target removes that pressure and is
    treated as a mild NEGATIVE (room to ease). This is a policy-reaction
    heuristic, not a claim that inflation itself is "good".
    """
    if headline is None and core is None:
        return _missing(DriverCategory.INFLATION, "Inflation", "no CPI/HICP/PCE observation")
    reference = core if core is not None else headline
    assert reference is not None
    if reference.value is None:
        return _missing(DriverCategory.INFLATION, "Inflation", "observation had no value")
    deviation = reference.value - target
    contribution = max(-1.0, min(1.0, deviation)) * 0.4
    facts = [f"{reference.source}:{reference.indicator}={reference.value}{reference.unit}"]
    rationale = (
        f"{'Core' if core is not None else 'Headline'} inflation {reference.value:.2f}% vs "
        f"~{target:.1f}% target (deviation {deviation:+.2f}pp) -> {contribution:+.2f} "
        "(above target sustains tightening pressure; below/at target removes it)."
    )
    return DriverScore(
        category=DriverCategory.INFLATION,
        label="Inflation vs. target",
        contribution=round(contribution, 4),
        rationale=rationale,
        supporting_facts=facts,
    )


def score_labor(
    *,
    unemployment_rate: FactObservation | None,
    payrolls_level: FactObservation | None,
    job_openings: FactObservation | None,
) -> DriverScore:
    """Falling unemployment / rising payrolls / rising job openings ->
    tighter labor market -> hawkish -> positive. Deteriorating labor data
    -> dovish -> negative.
    """
    facts: list[str] = []
    contribution = 0.0
    parts: list[str] = []

    if unemployment_rate is not None and unemployment_rate.value is not None:
        delta = (
            (unemployment_rate.value - unemployment_rate.revised_previous)
            if (unemployment_rate.revised_previous is not None)
            else 0.0
        )
        c = -delta * 0.5
        contribution += c
        facts.append(f"{unemployment_rate.source}:unemployment_rate={unemployment_rate.value}%")
        parts.append(f"unemployment change {delta:+.2f}pp -> {c:+.2f}")

    if (
        payrolls_level is not None
        and payrolls_level.value is not None
        and payrolls_level.revised_previous is not None
    ):
        delta_k = payrolls_level.value - payrolls_level.revised_previous
        c = max(-0.3, min(0.3, delta_k / 300.0))
        contribution += c
        facts.append(f"{payrolls_level.source}:payrolls_change={delta_k:+.0f}k")
        parts.append(f"payrolls change {delta_k:+.0f}k -> {c:+.2f}")

    if (
        job_openings is not None
        and job_openings.value is not None
        and job_openings.revised_previous is not None
    ):
        delta = job_openings.value - job_openings.revised_previous
        c = max(-0.2, min(0.2, delta / 500.0))
        contribution += c
        facts.append(f"{job_openings.source}:jolts_change={delta:+.0f}k")
        parts.append(f"JOLTS openings change {delta:+.0f}k -> {c:+.2f}")

    if not facts:
        return _missing(
            DriverCategory.LABOR, "Labor market", "no unemployment/payrolls/JOLTS observation"
        )

    return DriverScore(
        category=DriverCategory.LABOR,
        label="Labor market tightness",
        contribution=round(contribution, 4),
        rationale="; ".join(parts),
        supporting_facts=facts,
    )


def score_growth(
    *,
    gdp_growth: FactObservation | None,
    retail_sales: FactObservation | None,
) -> DriverScore:
    facts: list[str] = []
    contribution = 0.0
    parts: list[str] = []
    if gdp_growth is not None and gdp_growth.value is not None:
        c = max(-0.4, min(0.4, gdp_growth.value * 0.15))
        contribution += c
        facts.append(f"{gdp_growth.source}:{gdp_growth.indicator}={gdp_growth.value}%")
        parts.append(f"GDP growth {gdp_growth.value:+.2f}% -> {c:+.2f}")
    if retail_sales is not None and retail_sales.value is not None:
        c = max(-0.2, min(0.2, retail_sales.value * 0.05))
        contribution += c
        facts.append(f"{retail_sales.source}:{retail_sales.indicator}={retail_sales.value}%")
        parts.append(f"Retail sales {retail_sales.value:+.2f}% -> {c:+.2f}")
    if not facts:
        return _missing(DriverCategory.GROWTH, "Growth", "no GDP/retail sales observation")
    return DriverScore(
        category=DriverCategory.GROWTH,
        label="Growth momentum",
        contribution=round(contribution, 4),
        rationale="; ".join(parts),
        supporting_facts=facts,
    )


def score_supply_demand(
    *,
    label: str,
    positioning: FactObservation | None,
    inventories: FactObservation | None,
) -> DriverScore:
    """Generic supply/demand & positioning driver for commodities/crypto.
    Positioning is used only as a fundamental-flow indicator (net
    non-commercial futures positioning from CFTC), never as a technical
    momentum signal.
    """
    facts: list[str] = []
    contribution = 0.0
    parts: list[str] = []
    if (
        positioning is not None
        and positioning.value is not None
        and positioning.revised_previous is not None
    ):
        delta = positioning.value - positioning.revised_previous
        c = max(-0.3, min(0.3, delta / 20000.0))
        contribution += c
        facts.append(f"{positioning.source}:{positioning.indicator}={positioning.value:+.0f}")
        parts.append(f"net positioning change {delta:+.0f} contracts -> {c:+.2f}")
    if (
        inventories is not None
        and inventories.value is not None
        and inventories.revised_previous is not None
    ):
        delta = inventories.value - inventories.revised_previous
        c = max(-0.2, min(0.2, -delta / 5000.0))
        contribution += c
        facts.append(f"{inventories.source}:{inventories.indicator}={inventories.value:+.0f}")
        parts.append(f"inventories change {delta:+.0f} -> {c:+.2f}")
    if not facts:
        return _missing(DriverCategory.SUPPLY_DEMAND, label, "no positioning/inventory observation")
    return DriverScore(
        category=DriverCategory.SUPPLY_DEMAND,
        label=label,
        contribution=round(contribution, 4),
        rationale="; ".join(parts),
        supporting_facts=facts,
    )


def score_real_yield_and_dollar(
    *,
    real_yield: FactObservation | None,
    dollar_index: FactObservation | None,
) -> DriverScore:
    """XAUUSD-specific driver: rising real yields and a stronger dollar are
    fundamentally NEGATIVE for gold (higher opportunity cost of holding a
    non-yielding asset, cheaper for USD holders is irrelevant since we
    already price in USD); falling real yields / weaker dollar are
    POSITIVE for gold.
    """
    facts: list[str] = []
    contribution = 0.0
    parts: list[str] = []
    if real_yield is not None and real_yield.value is not None:
        c = -max(-0.5, min(0.5, real_yield.value * 0.25))
        contribution += c
        facts.append(f"{real_yield.source}:{real_yield.indicator}={real_yield.value}%")
        parts.append(f"10Y real yield {real_yield.value:+.2f}% -> {c:+.2f} for gold")
    if (
        dollar_index is not None
        and dollar_index.value is not None
        and dollar_index.revised_previous is not None
        and dollar_index.revised_previous != 0
    ):
        pct_change = (
            (dollar_index.value - dollar_index.revised_previous)
            / dollar_index.revised_previous
            * 100
        )
        c = -max(-0.3, min(0.3, pct_change * 0.3))
        contribution += c
        facts.append(f"{dollar_index.source}:{dollar_index.indicator} change={pct_change:+.2f}%")
        parts.append(f"broad USD index change {pct_change:+.2f}% -> {c:+.2f} for gold")
    if not facts:
        return _missing(
            DriverCategory.MARKET_EXPECTATIONS, "Real yields & USD", "no real yield/DXY observation"
        )
    return DriverScore(
        category=DriverCategory.MARKET_EXPECTATIONS,
        label="Real yields & broad USD (gold-specific)",
        contribution=round(contribution, 4),
        rationale="; ".join(parts),
        supporting_facts=facts,
    )


def score_liquidity_conditions(*, policy_rate: FactObservation | None) -> DriverScore:
    """Crypto/risk-asset-specific driver: a lower/falling policy rate
    implies looser global liquidity, generally supportive of risk appetite
    and speculative assets like BTC/ETH. A higher/rising rate is treated as
    a headwind.
    """
    if policy_rate is None or policy_rate.value is None:
        return _missing(
            DriverCategory.LIQUIDITY, "Policy-rate liquidity proxy", "no policy rate observation"
        )
    contribution = -max(-0.5, min(0.5, (policy_rate.value - 2.0) * 0.15))
    facts = [f"{policy_rate.source}:{policy_rate.indicator}={policy_rate.value}%"]
    rationale = (
        f"Policy rate {policy_rate.value:.2f}% vs. a neutral ~2% reference -> "
        f"{contribution:+.2f} liquidity-conditions proxy for risk assets."
    )
    return DriverScore(
        category=DriverCategory.LIQUIDITY,
        label="Global liquidity proxy",
        contribution=round(contribution, 4),
        rationale=rationale,
        supporting_facts=facts,
    )
