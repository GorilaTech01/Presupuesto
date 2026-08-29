"""Orchestrates the full pipeline (section 16):

MARKET UNIVERSE -> FUNDAMENTAL DATA -> NEWS/EVENT RESEARCH -> FILTER ->
3 FINALISTS -> FUNDAMENTAL COMPARISON -> SELECT BEST -> BUY/SELL/NO_TRADE ->
TRADE PLAN

This is the only module that is allowed to combine data-fetching,
scoring, catalysts, decisioning, risk math, and journaling into one flow --
every other module stays single-purpose and independently testable.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime

from app.broker.symbol_resolver import BrokerSymbolResolver
from app.catalysts.service import CatalystService, annotate_thesis_impact
from app.common.errors import DataSourceUnavailable, SymbolNotVerifiable
from app.common.time_utils import format_local
from app.config.settings import Settings
from app.domain.enums import AssetClass, Direction, Freshness
from app.domain.models import (
    CandidateAssessment,
    FundamentalDecision,
    TradePlan,
    WeeklyComparison,
)
from app.fundamental.candidate import CandidateEvaluation, evaluate_candidate, indicators_for_asset
from app.fundamental.decision import DecisionDraft, FundamentalDecisionEngine
from app.journal.journal import RecommendationJournal
from app.journal.models import JournalEntry
from app.market.price_provider import ManualPriceFileProvider, PriceQuote
from app.market.universe import AssetDefinition, get_asset
from app.risk.trade_math import build_trade_math
from app.sources.repository import FetchResult, FundamentalDataRepository

DEFAULT_CANDIDATES = ["EURUSD", "XAUUSD", "BTCUSD"]


@dataclass
class _CandidateBundle:
    evaluation: CandidateEvaluation
    draft: DecisionDraft
    price: PriceQuote | None
    price_error: str | None


class WeeklyPipeline:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.repository = FundamentalDataRepository(settings)
        self.catalyst_service = CatalystService(
            self.repository.fred if settings.fred_api_key else None
        )
        self.decision_engine = FundamentalDecisionEngine()
        self.symbol_resolver = BrokerSymbolResolver()
        self.price_provider = ManualPriceFileProvider(settings.data_dir / "manual_prices.json")
        self.journal = RecommendationJournal(settings.journal_dir / "journal.jsonl")

    def close(self) -> None:
        self.repository.close()

    def run(self, candidate_symbols: list[str] | None = None) -> WeeklyComparison:
        candidate_symbols = candidate_symbols or DEFAULT_CANDIDATES
        if len(candidate_symbols) != 3:
            raise ValueError("exactly 3 finalist candidates are required per run (section 16)")

        definitions = [get_asset(s) for s in candidate_symbols]
        all_indicators = sorted({ind for d in definitions for ind in indicators_for_asset(d)})
        fetch_result = self.repository.fetch_many(all_indicators)

        bundles: list[_CandidateBundle] = []
        for definition in definitions:
            bundles.append(self._evaluate_one(definition, fetch_result))

        winner = self._select_winner(bundles)
        candidates_table = [self._to_candidate_assessment(b, winner) for b in bundles]

        generated_at = datetime.now(UTC)
        data_cutoff_utc = max(
            (b.evaluation.score.data_cutoff_utc for b in bundles), default=generated_at
        )
        data_cutoff_local = format_local(data_cutoff_utc, self.settings.timezone)

        if winner is None:
            decision = self._no_trade_decision(bundles, data_cutoff_utc, data_cutoff_local)
            comparison = WeeklyComparison(
                generated_at=generated_at,
                data_cutoff_utc=data_cutoff_utc,
                data_cutoff_local=data_cutoff_local,
                candidates=candidates_table,
                selected_symbol=None,
                decision=decision,
                incomplete_reason=None,
            )
        else:
            decision = self._finalize_decision(winner, data_cutoff_utc, data_cutoff_local)
            comparison = WeeklyComparison(
                generated_at=generated_at,
                data_cutoff_utc=data_cutoff_utc,
                data_cutoff_local=data_cutoff_local,
                candidates=candidates_table,
                selected_symbol=winner.evaluation.definition.asset,
                decision=decision,
                incomplete_reason=None,
            )

        self._journal_entry(comparison)
        return comparison

    # -- per-candidate evaluation -------------------------------------------------

    def _evaluate_one(
        self, definition: AssetDefinition, fetch_result: FetchResult
    ) -> _CandidateBundle:
        evaluation = evaluate_candidate(definition, fetch_result)
        needed = indicators_for_asset(definition)
        calendar = self.catalyst_service.build_calendar(
            needed, timezone_name=self.settings.timezone, facts=fetch_result.facts
        )
        facts_freshness = [
            fetch_result.facts[i].freshness for i in needed if i in fetch_result.facts
        ] or [Freshness.UNKNOWN]

        if evaluation.base_score is not None and evaluation.quote_score is not None:
            favored_ccy_code: str = (
                "US"
                if (evaluation.bias < 0)
                else ("EZ" if definition.base_ccy == "EUR" else definition.base_ccy or "US")
            )
            annotated = annotate_thesis_impact(
                calendar,
                favored_country=favored_ccy_code,
                direction_label="BUY" if evaluation.bias > 0 else "SELL",
            )
            draft = self.decision_engine.decide_fx_pair(
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
            annotated = annotate_thesis_impact(
                calendar,
                favored_country="US",
                direction_label="BUY" if evaluation.bias > 0 else "SELL",
            )
            draft = self.decision_engine.decide_single_asset(
                symbol=definition.asset,
                score=evaluation.score,
                catalysts=annotated,
                facts_freshness=facts_freshness,
            )

        price, price_error = None, None
        try:
            resolved = self.symbol_resolver.resolve(definition.asset)
            price = self.price_provider.get_quote(resolved.broker_symbol)
        except (DataSourceUnavailable, SymbolNotVerifiable) as exc:
            price_error = str(exc)

        return _CandidateBundle(
            evaluation=evaluation, draft=draft, price=price, price_error=price_error
        )

    def _select_winner(self, bundles: list[_CandidateBundle]) -> _CandidateBundle | None:
        tradeable = [b for b in bundles if b.draft.direction is not Direction.NO_TRADE]
        if not tradeable:
            return None
        best = max(tradeable, key=lambda b: b.draft.conviction)
        return best

    def _to_candidate_assessment(
        self, bundle: _CandidateBundle, winner: _CandidateBundle | None
    ) -> CandidateAssessment:
        definition = bundle.evaluation.definition
        resolved = None
        with contextlib.suppress(SymbolNotVerifiable):
            resolved = self.symbol_resolver.resolve(definition.asset)
        bullish = [d.rationale for d in bundle.evaluation.score.drivers if d.contribution > 0]
        bearish = [d.rationale for d in bundle.evaluation.score.drivers if d.contribution < 0]
        is_winner = winner is not None and winner is bundle
        if is_winner:
            reason = (
                "SELECTED: strongest defensible fundamental asymmetry "
                f"(conviction {bundle.draft.conviction}/100)."
            )
        elif bundle.draft.direction is Direction.NO_TRADE:
            not_traded = bundle.draft.reasons[0] if bundle.draft.reasons else "NO_TRADE"
            reason = f"Not selected: {not_traded}."
        else:
            reason = (
                f"Not selected: weaker conviction ({bundle.draft.conviction}/100) "
                "than the chosen candidate."
            )
        main_catalysts = [
            f"{c.indicator} ({c.country}, {c.severity.value})" for c in bundle.draft.catalysts[:3]
        ]
        return CandidateAssessment(
            asset=definition.asset,
            broker_symbol=resolved.broker_symbol if resolved else "UNVERIFIED",
            current_price=bundle.price.mid if bundle.price else None,
            price_as_of=bundle.price.as_of if bundle.price else None,
            liquidity_note=(
                "Major/standard Pepperstone MT5 instrument; verify live spread before sizing."
            ),
            expected_event_volatility=(
                "HIGH"
                if any(c.severity.value == "CRITICAL" for c in bundle.draft.catalysts)
                else "MODERATE"
            ),
            main_catalysts=main_catalysts,
            bullish_fundamentals=bullish,
            bearish_fundamentals=bearish,
            event_slippage_risk=(
                "Elevated around the listed CRITICAL/HIGH catalysts; "
                "avoid entering minutes before a release."
            ),
            thesis_quality_1_10=max(1, min(10, round(bundle.draft.conviction / 10))),
            final_reason=reason,
            score=bundle.evaluation.score,
        )

    def _finalize_decision(
        self, winner: _CandidateBundle, data_cutoff_utc: datetime, data_cutoff_local: str
    ) -> FundamentalDecision:
        draft = winner.draft
        definition = winner.evaluation.definition
        trade_plan: TradePlan | None = None
        direction = draft.direction
        reasons = list(draft.reasons)

        if winner.price is None:
            direction = Direction.NO_TRADE
            reasons.append(f"price feed unavailable: {winner.price_error}")
        else:
            resolved = self.symbol_resolver.resolve(definition.asset)
            has_critical = any(c.severity.value == "CRITICAL" for c in draft.catalysts)
            math_result = build_trade_math(
                direction=draft.direction,
                asset_class=definition.asset_class,
                mid_price=winner.price.mid,
                spread=winner.price.spread,
                spec=resolved.spec,
                account_equity=self.settings.account_equity,
                risk_percent=self.settings.risk_percent,
                has_critical_catalyst_in_horizon=has_critical,
            )
            if not math_result.feasible:
                direction = Direction.NO_TRADE
                reasons.append(f"trade math infeasible: {math_result.reason}")
            else:
                trade_plan = TradePlan(
                    asset=definition.asset,
                    symbol=resolved.broker_symbol,
                    direction=draft.direction,
                    conviction_1_10=max(1, round(draft.conviction / 10)),
                    horizon="3-5 trading days (approx. Mon-Fri of the analysis week)",
                    order_type="Market or limit at estimated entry (manual, in MT5)",
                    fundamental_trigger=draft.entry_condition,
                    estimated_entry=math_result.entry,
                    stop_loss=math_result.stop_loss,
                    distance_to_sl=math_result.distance_to_sl,
                    take_profit=math_result.take_profit,
                    distance_to_tp=math_result.distance_to_tp,
                    risk_reward=math_result.risk_reward,
                    time_stop=draft.time_stop,
                    cancellation_condition=(
                        "Cancel if not triggered by the entry condition before the time stop."
                    ),
                    fundamental_invalidation=draft.fundamental_invalidation,
                    early_exit_condition=(
                        "Exit early if a subsequent release materially reverses the fundamental "
                        "thesis, regardless of current P&L."
                    ),
                    main_catalysts=[f"{c.indicator} ({c.country})" for c in draft.catalysts[:3]],
                    main_risks=draft.risks,
                )

        if direction is Direction.NO_TRADE and trade_plan is not None:
            trade_plan = None  # safety net for the FundamentalDecision validator

        return FundamentalDecision(
            symbol=definition.asset,
            asset_class=definition.asset_class,
            direction=direction,
            conviction=draft.conviction if direction is not Direction.NO_TRADE else 0,
            horizon="3-5 trading days" if direction is not Direction.NO_TRADE else "N/A",
            thesis=draft.thesis
            if direction is not Direction.NO_TRADE
            else f"NO_TRADE on {definition.asset}: " + "; ".join(reasons),
            top_drivers=draft.top_drivers,
            catalysts=draft.catalysts,
            entry_condition=draft.entry_condition if direction is not Direction.NO_TRADE else "N/A",
            fundamental_invalidation=draft.fundamental_invalidation
            if direction is not Direction.NO_TRADE
            else "N/A",
            risks=draft.risks,
            time_stop=draft.time_stop if direction is not Direction.NO_TRADE else "N/A",
            data_freshness=draft.data_freshness,
            sources=draft.sources,
            data_cutoff_utc=data_cutoff_utc,
            data_cutoff_local=data_cutoff_local,
            trade_plan=trade_plan,
            reasons=reasons,
        )

    def _no_trade_decision(
        self, bundles: list[_CandidateBundle], data_cutoff_utc: datetime, data_cutoff_local: str
    ) -> FundamentalDecision:
        all_reasons = [r for b in bundles for r in b.draft.reasons]
        worst_freshness = Freshness.FRESH
        order = [Freshness.FRESH, Freshness.AGING, Freshness.STALE, Freshness.UNKNOWN]
        for b in bundles:
            if order.index(b.draft.data_freshness) > order.index(worst_freshness):
                worst_freshness = b.draft.data_freshness
        sources = sorted({s for b in bundles for s in b.draft.sources})
        return FundamentalDecision(
            symbol="NONE",
            asset_class=AssetClass.FX,
            direction=Direction.NO_TRADE,
            conviction=0,
            horizon="N/A",
            thesis=(
                "NO_TRADE: none of the 3 finalist candidates presented a defensible fundamental "
                "asymmetry this week. " + " | ".join(all_reasons)
            ),
            top_drivers=[],
            catalysts=[c for b in bundles for c in b.draft.catalysts][:5],
            entry_condition="N/A",
            fundamental_invalidation="N/A",
            risks=["No position proposed; risk is limited to opportunity cost."],
            time_stop="N/A",
            data_freshness=worst_freshness,
            sources=sources,
            data_cutoff_utc=data_cutoff_utc,
            data_cutoff_local=data_cutoff_local,
            trade_plan=None,
            reasons=all_reasons,
        )

    def _journal_entry(self, comparison: WeeklyComparison) -> None:
        d = comparison.decision
        tp = d.trade_plan
        entry = JournalEntry(
            generated_at=comparison.generated_at,
            data_cutoff=comparison.data_cutoff_utc,
            asset=d.symbol,
            symbol=tp.symbol if tp else d.symbol,
            direction=d.direction,
            conviction=d.conviction,
            entry_condition=d.entry_condition,
            recommended_entry=tp.estimated_entry if tp else None,
            stop_loss=tp.stop_loss if tp else None,
            take_profit=tp.take_profit if tp else None,
            risk_reward=tp.risk_reward if tp else None,
            time_stop=d.time_stop,
            fundamental_thesis=d.thesis,
            drivers=[dr.label for dr in d.top_drivers],
            catalysts=[c.indicator for c in d.catalysts],
            invalidation=d.fundamental_invalidation,
            sources=d.sources,
        )
        self.journal.add(entry)
