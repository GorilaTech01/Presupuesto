"""TradeOpportunityMonitorService (V1.1 monitoring spec, section 4).

Owns the lifecycle of `MonitoredTradeOpportunity` records: creating them
(called by `WeeklyPipeline`), re-evaluating them (`python -m app monitor`),
persisting the result, and emitting domain events on material change. It
reuses the exact same normalization -> scoring -> catalyst -> decision
sequence as `weekly` (via `app.fundamental.candidate.build_decision_draft`)
and the exact same state-mapping rules as opportunity creation (via
`app.monitor.opportunity_engine.evaluate_opportunity`) -- there is no
second decision engine here.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime, timedelta

from app.broker.symbol_resolver import BrokerSymbolResolver, ResolvedSymbol
from app.catalysts.service import CatalystService
from app.common.errors import DataSourceUnavailable, StaleDataError, SymbolNotVerifiable
from app.common.event_bus import DomainEvent, EventBus
from app.common.lookahead import assert_no_lookahead
from app.config.settings import Settings
from app.domain.enums import Direction, FundamentalBias, JournalStatus, TradeAction, TriggerStatus
from app.domain.models import (
    CatalystEvent,
    MonitoredTradeOpportunity,
    OpportunityHistoryEntry,
    TradePlan,
)
from app.fundamental.candidate import build_decision_draft, indicators_for_asset
from app.fundamental.decision import MIN_BIAS_FOR_TRADE, DecisionDraft, FundamentalDecisionEngine
from app.journal.journal import RecommendationJournal
from app.market.price_provider import CurrentMarketQuote
from app.market.price_router import build_price_provider
from app.market.universe import AssetDefinition, get_asset
from app.monitor import events as monitor_events
from app.monitor.identity import OpportunityFingerprint, find_reusable_opportunity
from app.monitor.opportunity_engine import (
    READINESS_BLOCKER_PRICE_STALE,
    READINESS_BLOCKER_PRICE_UNAVAILABLE,
    OpportunityEvaluation,
    evaluate_opportunity,
)
from app.monitor.store import OpportunityEventLog, OpportunityStore
from app.risk.trade_math import TradeMathResult, build_trade_math
from app.sources.repository import FundamentalDataRepository

# A conviction move of at least this many points is "material" enough to
# raise ConvictionChangedMaterially on its own (spec section 14, optional
# alert trigger). Not a trading threshold -- an alerting one.
CONVICTION_MATERIAL_DELTA = 10


def end_of_trading_week(now: datetime) -> datetime:
    """The upcoming (or same-day, if already Friday) Friday 23:59:59 UTC.
    Matches the "close/reassess by Friday" time-stop used across this
    project. If `now` falls on a weekend, rolls to the *next* Friday.
    """
    days_until_friday = (4 - now.weekday()) % 7
    target_date = now + timedelta(days=days_until_friday)
    return target_date.replace(hour=23, minute=59, second=59, microsecond=0)


def _next_relevant_event(catalysts: list[CatalystEvent]) -> CatalystEvent | None:
    pending = [c for c in catalysts if c.actual is None]
    if not pending:
        return None
    return min(pending, key=lambda c: c.date_utc)


def _history_entry(
    now: datetime, evaluation: OpportunityEvaluation, score: float
) -> OpportunityHistoryEntry:
    return OpportunityHistoryEntry(
        at=now,
        fundamental_bias=evaluation.fundamental_bias,
        trade_action=evaluation.trade_action,
        trigger_status=evaluation.trigger_status,
        conviction=evaluation.conviction,
        score=score,
        reason="; ".join(evaluation.reasons) if evaluation.reasons else "no material change",
    )


def _materially_changed(
    opportunity: MonitoredTradeOpportunity, evaluation: OpportunityEvaluation
) -> bool:
    return (
        opportunity.trade_action != evaluation.trade_action
        or opportunity.fundamental_bias != evaluation.fundamental_bias
        or opportunity.trigger_status != evaluation.trigger_status
        or abs(opportunity.conviction - evaluation.conviction) >= CONVICTION_MATERIAL_DELTA
    )


def _apply_evaluation_update(
    opportunity: MonitoredTradeOpportunity,
    evaluation: OpportunityEvaluation,
    *,
    now: datetime,
    score: float,
    data_cutoff: datetime,
    catalysts: list[CatalystEvent],
    source_snapshot: list[str],
    direction: Direction,
    state_changed: bool,
) -> MonitoredTradeOpportunity:
    """The one place a `MonitoredTradeOpportunity`'s live re-evaluation
    fields are updated -- used identically by `refresh_one` (re-evaluating
    an existing opportunity) and `create_opportunity`'s reuse path
    (continuing an existing opportunity instead of creating a duplicate for
    the same active thesis). Identity/config fields (opportunity_id,
    recommendation_id, created_at, asset, symbol, horizon, valid_until,
    entry_condition, fundamental_invalidation, ...) are never touched here.
    """
    return opportunity.model_copy(
        update={
            "updated_at": now if state_changed else opportunity.updated_at,
            "fundamental_bias": evaluation.fundamental_bias,
            "trade_action": evaluation.trade_action,
            "direction": direction,
            "conviction": evaluation.conviction,
            "conviction_breakdown": evaluation.conviction_breakdown,
            "current_score": score,
            "data_cutoff": data_cutoff,
            "last_evaluated_at": now,
            "next_relevant_event": _next_relevant_event(catalysts),
            "trigger_status": evaluation.trigger_status,
            "readiness_reason": evaluation.readiness_reason,
            "cancellation_reason": evaluation.cancellation_reason,
            "fundamental_setup_ready": evaluation.fundamental_setup_ready,
            "readiness_blocker": evaluation.readiness_blocker,
            "catalysts": catalysts,
            "source_snapshot": source_snapshot,
            "decision_history": [
                *opportunity.decision_history,
                _history_entry(now, evaluation, score),
            ],
            "trade_plan": evaluation.trade_plan,
        }
    )


class TradeOpportunityMonitorService:
    def __init__(self, settings: Settings, event_bus: EventBus | None = None) -> None:
        self.settings = settings
        self.repository = FundamentalDataRepository(settings)
        self.catalyst_service = CatalystService(
            self.repository.fred if settings.fred_api_key else None
        )
        self.decision_engine = FundamentalDecisionEngine()
        self.symbol_resolver = BrokerSymbolResolver()
        self.price_provider = build_price_provider(settings)
        self.store = OpportunityStore(settings.data_dir / "monitor" / "opportunities.jsonl")
        self.event_log = OpportunityEventLog(
            settings.data_dir / "monitor" / "opportunity_events.jsonl"
        )
        self.journal = RecommendationJournal(settings.journal_dir / "journal.jsonl")
        self.event_bus = event_bus or EventBus()

    def close(self) -> None:
        self.repository.close()

    # -- creation (called by WeeklyPipeline) ---------------------------------

    def create_opportunity(
        self,
        *,
        definition: AssetDefinition,
        draft: DecisionDraft,
        evaluation_score: float,
        favored_country: str,
        price: CurrentMarketQuote | None,
        recommendation_id: str,
        data_cutoff: datetime,
        price_blocker: str | None = None,
    ) -> MonitoredTradeOpportunity | None:
        """Returns None when the candidate isn't worth monitoring at all
        (NO_TRADE and below the monitoring-interest threshold). `price` is
        supplied by the caller (e.g. `WeeklyPipeline`, which resolves its
        own quote); `price_blocker` is an optional, caller-diagnosed reason
        `price` is `None` (`READINESS_BLOCKER_PRICE_UNAVAILABLE`/`_STALE`) --
        omit it and a generic PRICE_UNAVAILABLE is assumed if needed.

        Continues an existing opportunity instead of creating a duplicate
        when one is still active for the same (asset, direction, horizon)
        fingerprint (see `app.monitor.identity`) -- e.g. running `weekly`/
        `daily` again while Monday's EURUSD bearish thesis is still WAIT or
        READY_TO_TRADE updates that same opportunity_id rather than starting
        a second, parallel one for the same idea.
        """
        now = datetime.now(UTC)
        fingerprint = OpportunityFingerprint(
            asset=definition.asset, direction=draft.direction, horizon=draft.time_stop
        )
        existing = find_reusable_opportunity(self.store.load_all(), fingerprint)
        valid_until = existing.valid_until if existing is not None else end_of_trading_week(now)

        symbol_resolved = None
        with contextlib.suppress(SymbolNotVerifiable):
            symbol_resolved = self.symbol_resolver.resolve(definition.asset)

        trade_math_result = self._build_trade_math(definition, draft, price, symbol_resolved)

        evaluation = evaluate_opportunity(
            draft=draft,
            score=evaluation_score,
            favored_country=favored_country,
            now=now,
            valid_until=valid_until,
            min_bias_for_trade=MIN_BIAS_FOR_TRADE,
            trade_math_result=trade_math_result,
            symbol_resolved=symbol_resolved is not None,
            trade_plan_builder=lambda d, m: self._build_trade_plan(
                definition, symbol_resolved, d, m
            ),
            price_blocker=price_blocker,
        )

        if evaluation.trade_action is TradeAction.NO_TRADE:
            # Deliberately does not touch `existing` even if one was found:
            # the next `refresh_all()` pass (never skips a non-CANCELLED
            # opportunity) will apply this same downgrade on its own, so
            # there is nothing this call needs to persist here.
            return None

        if existing is not None:
            previous_bias = existing.fundamental_bias
            previous_action = existing.trade_action
            previous_conviction = existing.conviction
            state_changed = _materially_changed(existing, evaluation)
            updated = _apply_evaluation_update(
                existing,
                evaluation,
                now=now,
                score=evaluation_score,
                data_cutoff=data_cutoff,
                catalysts=draft.catalysts,
                source_snapshot=draft.sources,
                direction=draft.direction,
                state_changed=state_changed,
            )
            self.store.save(updated)
            self._emit_transition_events(
                updated, previous_bias, previous_action, previous_conviction, state_changed
            )
            self._sync_journal(updated, previous_action)
            return updated

        opportunity = MonitoredTradeOpportunity(
            opportunity_id=str(uuid.uuid4()),
            recommendation_id=recommendation_id,
            created_at=now,
            updated_at=now,
            asset=definition.asset,
            symbol=symbol_resolved.broker_symbol if symbol_resolved else definition.asset,
            fundamental_bias=evaluation.fundamental_bias,
            trade_action=evaluation.trade_action,
            direction=draft.direction,
            conviction=evaluation.conviction,
            conviction_breakdown=evaluation.conviction_breakdown,
            original_score=evaluation_score,
            current_score=evaluation_score,
            threshold=MIN_BIAS_FOR_TRADE,
            horizon=draft.time_stop,
            entry_condition=draft.entry_condition,
            catalysts=draft.catalysts,
            fundamental_invalidation=draft.fundamental_invalidation,
            cancellation_conditions=[draft.fundamental_invalidation, "OPPORTUNITY_EXPIRED"],
            time_stop=draft.time_stop,
            valid_until=valid_until,
            data_cutoff=data_cutoff,
            last_evaluated_at=now,
            next_relevant_event=_next_relevant_event(draft.catalysts),
            trigger_status=evaluation.trigger_status,
            readiness_reason=evaluation.readiness_reason,
            cancellation_reason=evaluation.cancellation_reason,
            fundamental_setup_ready=evaluation.fundamental_setup_ready,
            readiness_blocker=evaluation.readiness_blocker,
            source_snapshot=draft.sources,
            decision_history=[_history_entry(now, evaluation, evaluation_score)],
            trade_plan=evaluation.trade_plan,
        )
        self.store.save(opportunity)
        event = monitor_events.trade_opportunity_created(opportunity)
        self.event_log.append(event)
        self.event_bus.publish(event)
        return opportunity

    def _build_trade_math(
        self,
        definition: AssetDefinition,
        draft: DecisionDraft,
        price: CurrentMarketQuote | None,
        resolved: ResolvedSymbol | None,
    ) -> TradeMathResult | None:
        if price is None or resolved is None:
            return None
        has_critical = any(c.severity.value == "CRITICAL" for c in draft.catalysts)
        return build_trade_math(
            direction=draft.direction,
            asset_class=definition.asset_class,
            mid_price=price.mid,
            spread=price.spread,
            spec=resolved.spec,
            account_equity=self.settings.account_equity,
            risk_percent=self.settings.risk_percent,
            has_critical_catalyst_in_horizon=has_critical,
        )

    def _build_trade_plan(
        self,
        definition: AssetDefinition,
        resolved: ResolvedSymbol | None,
        draft: DecisionDraft,
        math_result: TradeMathResult,
    ) -> TradePlan | None:
        if resolved is None or not math_result.feasible:
            return None
        order_type = (
            "CONDITIONAL / PENDING -- do NOT enter until the trigger below confirms; "
            "this is a planning reference, not an executable order."
            if draft.trade_action.value == "WAIT_FOR_TRIGGER"
            else "Market or limit at estimated entry (manual, in MT5)"
        )
        return TradePlan(
            asset=definition.asset,
            symbol=resolved.broker_symbol,
            direction=draft.direction,
            conviction_1_10=max(1, round(draft.conviction / 10)),
            horizon="3-5 trading days (approx. Mon-Fri of the analysis week)",
            order_type=order_type,
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

    # -- re-evaluation --------------------------------------------------------

    def refresh_one(
        self, opportunity: MonitoredTradeOpportunity, *, full_refresh: bool = False
    ) -> tuple[MonitoredTradeOpportunity, bool]:
        """Returns (updated_opportunity, state_changed)."""
        now = datetime.now(UTC)
        definition = get_asset(opportunity.asset)
        needed = indicators_for_asset(definition)

        if full_refresh:
            self.repository.cache.clear_all()

        fetch_result = self.repository.fetch_many(needed)

        try:
            assert_no_lookahead(list(fetch_result.facts.values()), now)
        except ValueError as exc:
            return self._reject_for_lookahead(opportunity, now, str(exc)), True

        draft, candidate_evaluation, favored_country = build_decision_draft(
            definition,
            fetch_result,
            catalyst_service=self.catalyst_service,
            decision_engine=self.decision_engine,
            timezone_name=self.settings.timezone,
        )
        score = candidate_evaluation.bias

        symbol_resolved = None
        with contextlib.suppress(SymbolNotVerifiable):
            symbol_resolved = self.symbol_resolver.resolve(definition.asset)

        price = None
        price_blocker: str | None = None
        if symbol_resolved is not None:
            try:
                price = self.price_provider.get_quote(symbol_resolved.broker_symbol)
            except StaleDataError:
                price_blocker = READINESS_BLOCKER_PRICE_STALE
            except DataSourceUnavailable:
                price_blocker = READINESS_BLOCKER_PRICE_UNAVAILABLE

        trade_math_result = self._build_trade_math(definition, draft, price, symbol_resolved)

        evaluation = evaluate_opportunity(
            draft=draft,
            score=score,
            favored_country=favored_country,
            now=now,
            valid_until=opportunity.valid_until,
            min_bias_for_trade=MIN_BIAS_FOR_TRADE,
            trade_math_result=trade_math_result,
            symbol_resolved=symbol_resolved is not None,
            trade_plan_builder=lambda d, m: self._build_trade_plan(
                definition, symbol_resolved, d, m
            ),
            price_blocker=price_blocker,
        )

        previous_bias = opportunity.fundamental_bias
        previous_action = opportunity.trade_action
        previous_conviction = opportunity.conviction
        state_changed = _materially_changed(opportunity, evaluation)

        new_data_cutoff = max(
            (f.retrieval_timestamp for f in fetch_result.facts.values()),
            default=opportunity.data_cutoff,
        )
        updated = _apply_evaluation_update(
            opportunity,
            evaluation,
            now=now,
            score=score,
            data_cutoff=new_data_cutoff,
            catalysts=draft.catalysts,
            source_snapshot=draft.sources,
            direction=draft.direction,
            state_changed=state_changed,
        )
        self.store.save(updated)
        self._emit_transition_events(
            updated, previous_bias, previous_action, previous_conviction, state_changed
        )
        self._sync_journal(updated, previous_action)
        return updated, state_changed

    def refresh_all(
        self, *, full_refresh: bool = False
    ) -> list[tuple[MonitoredTradeOpportunity, bool]]:
        results = []
        for opportunity in self.store.load_all():
            if opportunity.trade_action is TradeAction.CANCELLED:
                continue  # terminal state -- never re-evaluated again
            results.append(self.refresh_one(opportunity, full_refresh=full_refresh))
        return results

    # -- manual cancellation (`journal skip`) --------------------------------

    def cancel_opportunity(
        self, opportunity: MonitoredTradeOpportunity, *, reason: str
    ) -> MonitoredTradeOpportunity:
        """Manually cancels an opportunity (e.g. `journal skip`) so it is
        both (a) never re-evaluated again by `refresh_all` and (b) never
        matched as "still active" by a later `create_opportunity` reuse
        lookup (see `app.monitor.identity`) -- CANCELLED is the one
        terminal state both paths already respect. Idempotent: cancelling
        an already-cancelled opportunity is a no-op that returns it
        unchanged, so calling this twice never double-appends history or
        double-publishes an event.
        """
        if opportunity.trade_action is TradeAction.CANCELLED:
            return opportunity
        now = datetime.now(UTC)
        updated = opportunity.model_copy(
            update={
                "updated_at": now,
                "trade_action": TradeAction.CANCELLED,
                "cancellation_reason": reason,
                "trade_plan": None,
                "last_evaluated_at": now,
                "decision_history": [
                    *opportunity.decision_history,
                    OpportunityHistoryEntry(
                        at=now,
                        fundamental_bias=opportunity.fundamental_bias,
                        trade_action=TradeAction.CANCELLED,
                        trigger_status=opportunity.trigger_status,
                        conviction=opportunity.conviction,
                        score=opportunity.current_score,
                        reason=reason,
                    ),
                ],
            }
        )
        self.store.save(updated)
        self._publish(monitor_events.trade_opportunity_cancelled(updated))
        self._sync_journal(updated, opportunity.trade_action)
        return updated

    def _reject_for_lookahead(
        self, opportunity: MonitoredTradeOpportunity, now: datetime, detail: str
    ) -> MonitoredTradeOpportunity:
        """Fail-closed: a lookahead violation means the fetched facts are
        untrustworthy, so nothing is re-decided -- the opportunity's state
        is left exactly as it was, only the audit trail records the
        rejected attempt.
        """
        updated = opportunity.model_copy(
            update={
                "last_evaluated_at": now,
                "decision_history": [
                    *opportunity.decision_history,
                    OpportunityHistoryEntry(
                        at=now,
                        fundamental_bias=opportunity.fundamental_bias,
                        trade_action=opportunity.trade_action,
                        trigger_status=opportunity.trigger_status,
                        conviction=opportunity.conviction,
                        score=opportunity.current_score,
                        reason=f"LOOKAHEAD_VIOLATION_DETECTED, re-evaluation rejected: {detail}",
                    ),
                ],
            }
        )
        self.store.save(updated)
        return updated

    def _emit_transition_events(
        self,
        opportunity: MonitoredTradeOpportunity,
        previous_bias: FundamentalBias,
        previous_action: TradeAction,
        previous_conviction: int,
        state_changed: bool,
    ) -> None:
        if not state_changed:
            return
        self._publish(monitor_events.trade_opportunity_updated(opportunity))
        if (
            opportunity.trade_action is TradeAction.READY_TO_TRADE
            and previous_action is not TradeAction.READY_TO_TRADE
        ):
            self._publish(monitor_events.trade_opportunity_ready(opportunity))
        if (
            opportunity.trade_action is TradeAction.CANCELLED
            and previous_action is not TradeAction.CANCELLED
        ):
            if opportunity.trigger_status is TriggerStatus.EXPIRED:
                self._publish(monitor_events.trade_opportunity_expired(opportunity))
            else:
                self._publish(monitor_events.trade_opportunity_cancelled(opportunity))
        if opportunity.fundamental_bias != previous_bias:
            self._publish(monitor_events.fundamental_bias_changed(opportunity, previous_bias.value))
        if abs(opportunity.conviction - previous_conviction) >= CONVICTION_MATERIAL_DELTA:
            self._publish(
                monitor_events.conviction_changed_materially(opportunity, previous_conviction)
            )

    def _publish(self, event: DomainEvent) -> None:
        self.event_log.append(event)
        self.event_bus.publish(event)

    def _sync_journal(
        self, opportunity: MonitoredTradeOpportunity, previous_action: TradeAction
    ) -> None:
        if (
            opportunity.trade_action is TradeAction.READY_TO_TRADE
            and previous_action is not TradeAction.READY_TO_TRADE
        ):
            with contextlib.suppress(KeyError):
                self.journal.update(
                    opportunity.recommendation_id, ready_to_trade_at=opportunity.updated_at
                )
        if (
            opportunity.trade_action is TradeAction.CANCELLED
            and previous_action is not TradeAction.CANCELLED
        ):
            status = (
                JournalStatus.NOT_TRIGGERED
                if opportunity.trigger_status is TriggerStatus.EXPIRED
                else JournalStatus.CANCELLED
            )
            with contextlib.suppress(KeyError):
                self.journal.update(
                    opportunity.recommendation_id,
                    status=status,
                    exit_reason=opportunity.cancellation_reason or status.value,
                )
