"""Per-asset orchestration: which indicators an asset needs, and how to turn
fetched facts into a FundamentalScore for it. This is the seam that lets
the weekly pipeline treat FX pairs, metals, and crypto uniformly.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.enums import AssetClass
from app.domain.models import FundamentalScore
from app.fundamental import analysis
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
