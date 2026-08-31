"""Human-readable + machine-readable monitor output (V1.1 spec, sections
12-13). Built directly from `MonitoredTradeOpportunity` so the human and
JSON forms can never drift apart -- same pattern as the weekly reports.
"""

from __future__ import annotations

from typing import Any

from app.common.time_utils import format_local, format_utc
from app.domain.enums import TradeAction
from app.domain.models import MonitoredTradeOpportunity

BAR = "═" * 40


def render_no_change(opportunity: MonitoredTradeOpportunity, timezone_name: str) -> str:
    lines = [
        "FUNDAMENTAL TRADE MONITOR",
        "",
        opportunity.symbol,
        f"Bias: {opportunity.fundamental_bias.value}",
        f"Action: {opportunity.trade_action.value}",
        f"Conviction: {max(1, round(opportunity.conviction / 10))}/10",
        "",
        "No material change.",
        "",
    ]
    if opportunity.next_relevant_event is not None:
        nxt = opportunity.next_relevant_event
        lines += [
            "Next catalyst:",
            f"{nxt.indicator} ({nxt.country})",
            f"{format_local(nxt.date_utc, timezone_name)}",
            "",
        ]
    else:
        lines += ["Next catalyst:", "None flagged.", ""]
    lines += [
        "Status:",
        "Waiting for catalyst."
        if opportunity.trade_action is TradeAction.WAIT
        else opportunity.trade_action.value,
    ]
    if opportunity.fundamental_setup_ready:
        lines += [
            "",
            "Fundamental setup: READY.",
            f"Blocked only on: {opportunity.readiness_blocker or 'operational input pending'}.",
        ]
    return "\n".join(lines)


def render_ready_to_trade(opportunity: MonitoredTradeOpportunity, timezone_name: str) -> str:
    tp = opportunity.trade_plan
    lines = [
        BAR,
        "FUNDAMENTAL TRADE ALERT",
        BAR,
        "",
        "STATUS:",
        "READY_TO_TRADE",
        "",
        "Asset:",
        opportunity.asset,
        "",
        "Direction:",
        opportunity.direction.value,
        "",
        "Conviction:",
        f"{max(1, round(opportunity.conviction / 10))}/10",
        "",
        "Fundamental Trigger:",
        opportunity.trigger_status.value,
        "",
        "Why now:",
    ]
    for i, entry in enumerate(opportunity.decision_history[-1:], start=1):
        lines.append(f"  {i}. {entry.reason}")
    lines.append("")
    if tp is not None:
        lines += [
            "Entry:",
            str(tp.estimated_entry),
            "",
            "Stop Loss:",
            str(tp.stop_loss),
            "",
            "Take Profit:",
            str(tp.take_profit),
            "",
            "R:R:",
            str(tp.risk_reward),
            "",
        ]
    lines += [
        "Fundamental invalidation:",
        opportunity.fundamental_invalidation,
        "",
        "Valid until:",
        format_local(opportunity.valid_until, timezone_name),
        "",
    ]
    if opportunity.next_relevant_event is not None:
        nxt = opportunity.next_relevant_event
        lines += ["Next catalyst:", f"{nxt.indicator} ({nxt.country})", ""]
    else:
        lines += ["Next catalyst:", "None flagged.", ""]
    lines += [
        "Manual execution only.",
        "",
        "Verify exact symbol in:",
        "MT5 > Market Watch > Show All",
        BAR,
    ]
    return "\n".join(lines)


def render_cancelled(opportunity: MonitoredTradeOpportunity) -> str:
    lines = [
        BAR,
        "FUNDAMENTAL TRADE ALERT",
        BAR,
        "",
        "STATUS:",
        "CANCELLED",
        "",
        "Asset:",
        opportunity.asset,
        "",
        "Previous Bias:",
        opportunity.fundamental_bias.value,
        "",
        "Reason:",
        opportunity.cancellation_reason or "unspecified",
        "",
        "Do not enter this trade.",
        BAR,
    ]
    return "\n".join(lines)


def render_monitor_report(
    opportunity: MonitoredTradeOpportunity, timezone_name: str, *, state_changed: bool
) -> str:
    if opportunity.trade_action is TradeAction.READY_TO_TRADE:
        return render_ready_to_trade(opportunity, timezone_name)
    if opportunity.trade_action is TradeAction.CANCELLED:
        return render_cancelled(opportunity)
    return render_no_change(opportunity, timezone_name)


def to_machine_readable(
    opportunity: MonitoredTradeOpportunity, *, state_changed: bool
) -> dict[str, Any]:
    tp = opportunity.trade_plan
    trigger_reasons = (
        opportunity.decision_history[-1].reason.split("; ") if opportunity.decision_history else []
    )
    return {
        "opportunity_id": opportunity.opportunity_id,
        "recommendation_id": opportunity.recommendation_id,
        "symbol": opportunity.symbol,
        "fundamental_bias": opportunity.fundamental_bias.value,
        "trade_action": opportunity.trade_action.value,
        "direction": opportunity.direction.value,
        "conviction": opportunity.conviction,
        "conviction_1_10": max(1, round(opportunity.conviction / 10))
        if opportunity.conviction
        else 0,
        "score": opportunity.current_score,
        "threshold": opportunity.threshold,
        "trigger_status": opportunity.trigger_status.value,
        "trigger_reasons": trigger_reasons,
        "readiness_reason": opportunity.readiness_reason,
        "cancellation_reason": opportunity.cancellation_reason,
        "fundamental_setup_ready": opportunity.fundamental_setup_ready,
        "readiness_blocker": opportunity.readiness_blocker,
        "invalidation": opportunity.fundamental_invalidation,
        "entry": tp.estimated_entry if tp else None,
        "stop_loss": tp.stop_loss if tp else None,
        "take_profit": tp.take_profit if tp else None,
        "risk_reward": tp.risk_reward if tp else None,
        "data_cutoff": format_utc(opportunity.data_cutoff),
        "last_evaluated_at": format_utc(opportunity.last_evaluated_at),
        "valid_until": format_utc(opportunity.valid_until),
        "next_catalyst": (
            {
                "indicator": opportunity.next_relevant_event.indicator,
                "country": opportunity.next_relevant_event.country,
                "date_utc": format_utc(opportunity.next_relevant_event.date_utc),
                "severity": opportunity.next_relevant_event.severity.value,
            }
            if opportunity.next_relevant_event is not None
            else None
        ),
        "state_changed": state_changed,
    }
