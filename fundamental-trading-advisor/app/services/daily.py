"""Shared `daily` orchestration logic.

Pure orchestration of `WeeklyPipeline.run()` +
`TradeOpportunityMonitorService.refresh_all()` -- no new scoring, decision,
or monitoring logic. This is the single implementation the CLI
(`python -m app daily`) and the desktop app's "Run Daily Analysis" button
both call; neither re-implements it, so there is exactly one place this
flow is defined.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config.settings import Settings
from app.domain.models import MonitoredTradeOpportunity, WeeklyComparison
from app.services.weekly_pipeline import WeeklyPipeline


@dataclass
class DailyRunResult:
    comparison: WeeklyComparison
    todays_opportunity: MonitoredTradeOpportunity | None
    other_opportunities: list[MonitoredTradeOpportunity]


def run_daily_analysis(settings: Settings, candidates: list[str] | None = None) -> DailyRunResult:
    """Runs the weekly comparison, then refreshes every monitored
    opportunity. Returns today's linked opportunity (if any) separately
    from the rest so a caller can render "today's decision" distinctly
    from "everything else being tracked."
    """
    pipeline = WeeklyPipeline(settings)
    try:
        comparison = pipeline.run(candidates)
        results = pipeline.monitor_service.refresh_all()
    finally:
        pipeline.close()

    # Look today's opportunity up from the store directly, not just from
    # `results`: refresh_all() correctly skips CANCELLED opportunities
    # (terminal state, never re-evaluated again), so a same-day creation
    # that was immediately cancelled by a contradicting catalyst would
    # otherwise never be found here even though it IS today's outcome.
    all_opportunities = pipeline.monitor_service.store.load_all()
    todays_opportunity = next(
        (o for o in all_opportunities if o.recommendation_id == pipeline.last_recommendation_id),
        None,
    )
    others = [
        opportunity
        for opportunity, _state_changed in results
        if todays_opportunity is None
        or opportunity.opportunity_id != todays_opportunity.opportunity_id
    ]
    return DailyRunResult(
        comparison=comparison, todays_opportunity=todays_opportunity, other_opportunities=others
    )
