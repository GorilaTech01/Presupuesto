"""Per-asset orchestration: which indicators an asset needs, and how to turn
fetched facts into a FundamentalScore for it. This is the seam that lets
the weekly pipeline treat FX pairs, metals, and crypto uniformly.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.catalysts.service import CatalystService, annotate_thesis_impact
from app.domain.enums import AssetClass, Freshness
from app.domain.models import FundamentalScore
from app.fundamental import analysis
from app.fundamental.decision import DecisionDraft, FundamentalDecisionEngine
from app.market.universe import AssetDefinition
from app.sources.repository import FetchResult

XAU_INDICATORS = [
    "us_real_10y_yield",
    "us_dollar_index_broad",
    "us_cpi_yoy",
    "us_core_cpi_yoy",
    "gold_net_noncommercial_positioning",
]
CRYPTO_INDICATORS = ["us_fed_funds_target_upper"]


@dataclass
class CandidateEvaluation:
    definition: AssetDefinition
    score: FundamentalScore
    bias: float  # for FX: base-quote differential; otherwise == score.total
    base_score: FundamentalScore | None = None  # FX only
    quote_score: FundamentalScore | None = None  # FX only


def indicators_for_asset(definition: AssetDefinition) -> list[str]:
    if definition.asset_class == AssetClass.FX:
        assert definition.base_ccy and definition.quote_ccy
        base_inds = analysis.CURRENCY_INDICATORS.get(definition.base_ccy, [])
        quote_inds = analysis.CURRENCY_INDICATORS.get(definition.quote_ccy, [])
        return list(dict.fromkeys(base_inds + quote_inds))
    if definition.asset == "XAUUSD":
        return XAU_INDICATORS
    if definition.asset_class == AssetClass.CRYPTO:
        return CRYPTO_INDICATORS
    return []


def evaluate_candidate(definition: AssetDefinition, result: FetchResult) -> CandidateEvaluation:
    if definition.asset_class == AssetClass.FX:
        assert definition.base_ccy and definition.quote_ccy
        if (
            definition.base_ccy not in analysis.CURRENCY_INDICATORS
            or definition.quote_ccy not in analysis.CURRENCY_INDICATORS
        ):
            raise ValueError(
                f"no currency scoring model for {definition.base_ccy}/{definition.quote_ccy} yet"
            )
        base_score = analysis.build_currency_score(definition.base_ccy, result)
        quote_score = analysis.build_currency_score(definition.quote_ccy, result)
        bias = analysis.build_fx_pair_bias(base_score, quote_score)
        combined = FundamentalScore(
            subject=definition.asset,
            total=bias,
            drivers=base_score.drivers + quote_score.drivers,
            data_cutoff_utc=max(base_score.data_cutoff_utc, quote_score.data_cutoff_utc),
            warnings=base_score.warnings + quote_score.warnings,
        )
        return CandidateEvaluation(
            definition=definition,
            score=combined,
            bias=bias,
            base_score=base_score,
            quote_score=quote_score,
        )
    if definition.asset == "XAUUSD":
        score = analysis.build_xau_score(result)
        return CandidateEvaluation(definition=definition, score=score, bias=score.total)
    if definition.asset_class == AssetClass.CRYPTO:
        score = analysis.build_btc_score(result)
        return CandidateEvaluation(definition=definition, score=score, bias=score.total)
    raise ValueError(f"no scoring model for asset '{definition.asset}'")


def favored_country_for(definition: AssetDefinition, bias: float) -> str:
    """Which country's fundamentals the thesis leans on, given the sign of
    `bias`. Shared by `WeeklyPipeline` and `TradeOpportunityMonitorService`
    so both annotate catalysts (favors/weakens/invalidates) identically.
    """
    if definition.asset_class == AssetClass.FX:
        if bias < 0:
            return "US"
        return "EZ" if definition.base_ccy == "EUR" else (definition.base_ccy or "US")
    return "US"


def build_decision_draft(
    definition: AssetDefinition,
    fetch_result: FetchResult,
    *,
    catalyst_service: CatalystService,
    decision_engine: FundamentalDecisionEngine,
    timezone_name: str,
) -> tuple[DecisionDraft, CandidateEvaluation, str]:
    """The one place that turns normalized facts into a `DecisionDraft` for
    a given asset. `WeeklyPipeline` (creating a recommendation) and
    `TradeOpportunityMonitorService` (re-evaluating one) both call this --
    neither runs its own copy of the scoring/catalyst/decision sequence, so
    the same normalized facts always produce the same decision regardless
    of which caller asked (V1.1 monitoring spec, section 4).
    """
    evaluation = evaluate_candidate(definition, fetch_result)
    needed = indicators_for_asset(definition)
    calendar = catalyst_service.build_calendar(
        needed, timezone_name=timezone_name, facts=fetch_result.facts
    )
    facts_freshness = [
        fetch_result.facts[i].freshness for i in needed if i in fetch_result.facts
    ] or [Freshness.UNKNOWN]
    favored_country = favored_country_for(definition, evaluation.bias)
    annotated = annotate_thesis_impact(
        calendar,
        favored_country=favored_country,
        direction_label="BUY" if evaluation.bias > 0 else "SELL",
    )
    if evaluation.base_score is not None and evaluation.quote_score is not None:
        draft = decision_engine.decide_fx_pair(
            symbol=definition.asset,
            base_ccy=definition.base_ccy or "",
            quote_ccy=definition.quote_ccy or "",
            base_score=evaluation.base_score,
            quote_score=evaluation.quote_score,
            bias=evaluation.bias,
            catalysts=annotated,
            facts_freshness=facts_freshness,
        )
    else:
        draft = decision_engine.decide_single_asset(
            symbol=definition.asset,
            score=evaluation.score,
            catalysts=annotated,
            facts_freshness=facts_freshness,
        )
    return draft, evaluation, favored_country
