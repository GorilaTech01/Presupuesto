"""Consolidated daily-review rendering for `python -m app daily` (V1.1.2:
close-out for manual daily use, docs/daily_workflow.md).

This module renders text only -- it recomputes nothing. The "MARKET
DECISION" always describes either the `MonitoredTradeOpportunity` this
run's weekly recommendation is linked to (via `recommendation_id`, when one
exists) or, if none was created, the raw `WeeklyComparison.decision`
(always NO_TRADE in that case -- see `WeeklyPipeline._create_monitored_
opportunity`). READY_TO_TRADE and CANCELLED reuse the exact
`app.reporting.monitor_report` renderers verbatim so there is exactly one
place that formats those two states.
"""

from __future__ import annotations

from app.common.time_utils import format_local, format_utc
from app.domain.enums import TradeAction
from app.domain.models import CatalystEvent, MonitoredTradeOpportunity, WeeklyComparison
from app.reporting.monitor_report import render_cancelled, render_ready_to_trade

BAR = "═" * 40


def _catalyst_block(catalyst: CatalystEvent | None, timezone_name: str) -> list[str]:
    if catalyst is None:
        return ["NEXT CATALYST", "", "None flagged.", ""]
    consensus = catalyst.consensus if catalyst.consensus is not None else "CONSENSUS_UNAVAILABLE"
    previous = catalyst.previous if catalyst.previous is not None else "unavailable"
    return [
        "NEXT CATALYST",
        "",
        "Event:",
        f"{catalyst.indicator} ({catalyst.country})",
        "",
        "Date/time (local):",
        format_local(catalyst.date_utc, timezone_name),
        "",
        "Consensus:",
        str(consensus),
        "",
        "Previous:",
        str(previous),
        "",
        "What confirms thesis:",
        catalyst.favors_thesis_if or "not specified",
        "",
        "What contradicts/invalidates thesis:",
        (catalyst.weakens_thesis_if or catalyst.invalidates_thesis_if or "not specified"),
        "",
    ]


def render_daily_review(
    comparison: WeeklyComparison,
    todays_opportunity: MonitoredTradeOpportunity | None,
    timezone_name: str,
) -> str:
    if (
        todays_opportunity is not None
        and todays_opportunity.trade_action is TradeAction.READY_TO_TRADE
    ):
        header = ["FUNDAMENTAL TRADING ADVISOR", "DAILY REVIEW", ""]
        return "\n".join(header) + "\n" + render_ready_to_trade(todays_opportunity, timezone_name)

    if todays_opportunity is not None and todays_opportunity.trade_action is TradeAction.CANCELLED:
        header = ["FUNDAMENTAL TRADING ADVISOR", "DAILY REVIEW", ""]
        return "\n".join(header) + "\n" + render_cancelled(todays_opportunity)

    lines = [
        "FUNDAMENTAL TRADING ADVISOR",
        "DAILY REVIEW",
        "",
        "Date:",
        format_utc(comparison.generated_at),
        "",
        "Data cutoff:",
        comparison.data_cutoff_local,
        "",
        "MARKET DECISION",
        "",
    ]

    if todays_opportunity is not None:
        asset = todays_opportunity.asset
        bias = todays_opportunity.fundamental_bias.value
        action = todays_opportunity.trade_action.value
        conviction_1_10 = max(1, round(todays_opportunity.conviction / 10))
        reason = todays_opportunity.readiness_reason or (
            todays_opportunity.decision_history[-1].reason
            if todays_opportunity.decision_history
            else "Waiting for fundamental confirmation."
        )
        next_event = todays_opportunity.next_relevant_event
    else:
        asset = comparison.selected_symbol or "NONE"
        bias = "NEUTRAL"
        action = "NO_TRADE"
        conviction_1_10 = 0
        reason = (
            comparison.decision.reasons[0]
            if comparison.decision.reasons
            else "No candidate currently meets the minimum fundamental threshold."
        )
        next_event = None

    lines += [
        "Selected asset:",
        asset,
        "",
        "Fundamental bias:",
        bias,
        "",
        "Trade action:",
        action,
        "",
        "Conviction:",
        f"{conviction_1_10}/10",
        "",
        "Reason:",
        reason,
        "",
    ]
    lines += _catalyst_block(next_event, timezone_name)
    lines += ["CURRENT ACTION", "", action]
    if action == "WAIT":
        lines += ["", "Do not enter yet."]
    return "\n".join(lines)


def render_other_opportunities(
    opportunities: list[MonitoredTradeOpportunity], timezone_name: str
) -> str:
    """One compact line per opportunity NOT covered by today's MARKET
    DECISION -- e.g. a prior day's still-open idea for a different asset.
    """
    if not opportunities:
        return ""
    lines = ["", BAR, "OTHER MONITORED OPPORTUNITIES", BAR]
    for o in opportunities:
        conviction_1_10 = max(1, round(o.conviction / 10)) if o.conviction else 0
        lines.append(
            f"{o.asset}: {o.fundamental_bias.value} / {o.trade_action.value} "
            f"({conviction_1_10}/10)"
            + (f" -- blocked on {o.readiness_blocker}" if o.readiness_blocker else "")
        )
    return "\n".join(lines)
