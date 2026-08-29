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
"""

from __future__ import annotations

from app.domain.enums import DriverCategory
from app.domain.models import DriverScore, FactObservation

MISSING_DATA_NOTE = "insufficient/unavailable data for this category"


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
    """Higher policy rate = more attractive carry (positive).
    Higher *real* policy rate (rate - inflation) = tighter/more hawkish
    stance = additional positive contribution, since a central bank holding
    real rates restrictive signals it is prioritizing currency-supportive
    tightness over growth.
    """
    if policy_rate is None:
        return _missing(DriverCategory.MONETARY_POLICY, "Policy rate", "no policy rate observation")
    nominal_component = policy_rate.value or 0.0
    facts = [f"{policy_rate.source}:{policy_rate.indicator}={policy_rate.value}{policy_rate.unit}"]
    real_component = 0.0
    rationale = f"Policy rate {policy_rate.value:.2f}% contributes {nominal_component:.2f} (carry)."
    if headline_inflation is not None and headline_inflation.value is not None:
        real_rate = (policy_rate.value or 0.0) - headline_inflation.value
        real_component = real_rate * 0.5
        facts.append(
            f"{headline_inflation.source}:{headline_inflation.indicator}={headline_inflation.value}{headline_inflation.unit}"
        )
        rationale += (
            f" Real policy rate ~{real_rate:.2f}pp (rate - headline inflation) "
            f"contributes {real_component:.2f} (restrictiveness)."
        )
    else:
        rationale += " Real-rate component skipped: no headline inflation observation."
    return DriverScore(
        category=DriverCategory.MONETARY_POLICY,
        label="Policy rate & real-rate stance",
        contribution=round(nominal_component + real_component, 4),
        rationale=rationale,
        supporting_facts=facts,
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
        and payrolls_level.revised_previous
    ):
        delta_k = payrolls_level.value - payrolls_level.revised_previous
        c = max(-0.3, min(0.3, delta_k / 300.0))
        contribution += c
        facts.append(f"{payrolls_level.source}:payrolls_change={delta_k:+.0f}k")
        parts.append(f"payrolls change {delta_k:+.0f}k -> {c:+.2f}")

    if (
        job_openings is not None
        and job_openings.value is not None
        and job_openings.revised_previous
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
        and dollar_index.revised_previous
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
