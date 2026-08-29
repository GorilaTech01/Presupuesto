"""Human-readable report (section 26). No programming knowledge required to
read this output.
"""

from __future__ import annotations

from app.common.time_utils import format_local, format_utc
from app.domain.models import WeeklyComparison

BAR = "\u2550" * 40


def render_human_report(comparison: WeeklyComparison, timezone_name: str) -> str:
    d = comparison.decision
    lines: list[str] = []
    lines.append(BAR)
    lines.append("FUNDAMENTAL TRADING ADVISOR")
    lines.append(BAR)
    lines.append("")
    lines.append(f"DATE: {comparison.generated_at.date().isoformat()}")
    lines.append(
        f"DATA CUTOFF: {format_utc(comparison.data_cutoff_utc)} UTC "
        f"/ {comparison.data_cutoff_local} ({timezone_name})"
    )
    lines.append("")

    lines.append("CANDIDATES CONSIDERED (exactly 3):")
    for c in comparison.candidates:
        price_str = (
            f"{c.current_price:.5f}"
            if c.current_price is not None
            else "N/A (no live quote configured)"
        )
        lines.append(
            f"  - {c.asset} ({c.broker_symbol}): price={price_str}, "
            f"thesis quality {c.thesis_quality_1_10}/10"
        )
        lines.append(f"    reason: {c.final_reason}")
    lines.append("")

    if comparison.incomplete_reason:
        lines.append(f"STATUS: ANALYSIS_INCOMPLETE -- {comparison.incomplete_reason}")
        lines.append(BAR)
        return "\n".join(lines)

    lines.append(f"SELECTED ASSET:\n{comparison.selected_symbol}")
    lines.append("")
    lines.append(f"DECISION (fundamental bias):\n{d.direction.value}")
    lines.append("")
    lines.append(f"TRADE ACTION:\n{d.trade_action.value}")
    if d.trade_action.value == "WAIT_FOR_TRIGGER":
        lines.append(
            "  (bias only -- NOT an executable order yet; wait for the entry condition below)"
        )
    lines.append("")
    lines.append(f"CONVICTION:\n{d.conviction_1_10}/10")
    if d.conviction_breakdown is not None:
        b = d.conviction_breakdown
        lines.append(
            f"  raw_score={b.raw_score} normalized_score={b.normalized_score} "
            f"data_completeness=({b.data_completeness}) source_quality=({b.source_quality}) "
            f"contradiction_penalty=-{b.contradiction_penalty} "
            f"event_risk_penalty=-{b.event_risk_penalty} "
            f"missing_data_penalty=-{b.missing_data_penalty} "
            f"source_quality_penalty=-{b.source_quality_penalty} "
            f"expectations_penalty=-{b.expectations_penalty} "
            f"-> final_conviction={b.final_conviction}/100"
        )
    lines.append("")
    lines.append(f"HORIZON:\n{d.horizon}")
    lines.append("")
    lines.append("WHY:")
    for i, driver in enumerate(d.top_drivers, start=1):
        lines.append(f"  {i}. [{driver.category.value}] {driver.rationale}")
    lines.append("")

    if d.catalysts:
        main = d.catalysts[0]
        lines.append(
            "MAIN CATALYST:\n"
            f"  {main.indicator} ({main.country}) on {format_local(main.date_utc, timezone_name)} "
            f"[{main.severity.value}]"
        )
    else:
        lines.append("MAIN CATALYST:\n  None identified in the next 7 days.")
    lines.append("")

    lines.append(f"ENTRY CONDITION:\n{d.entry_condition}")
    lines.append("")

    if d.trade_plan is not None:
        tp = d.trade_plan
        lines.append(f"ENTRY:\n{tp.estimated_entry}")
        lines.append("")
        lines.append(f"STOP LOSS:\n{tp.stop_loss} (distance {tp.distance_to_sl})")
        lines.append("")
        lines.append(f"TAKE PROFIT:\n{tp.take_profit} (distance {tp.distance_to_tp})")
        lines.append("")
        lines.append(f"R:R:\n{tp.risk_reward}")
        lines.append("")
    else:
        lines.append("ENTRY / STOP LOSS / TAKE PROFIT:\n  N/A -- NO_TRADE")
        lines.append("")

    lines.append(f"INVALIDATION:\n{d.fundamental_invalidation}")
    lines.append("")
    lines.append(f"DO NOT ENTER IF:\n{'; '.join(d.risks)}")
    lines.append("")
    lines.append(f"TIME STOP:\n{d.time_stop}")
    lines.append("")

    if len(d.catalysts) > 1:
        nxt = d.catalysts[1]
        lines.append(
            "NEXT EVENT TO WATCH:\n"
            f"  {nxt.indicator} ({nxt.country}) on {format_local(nxt.date_utc, timezone_name)}"
        )
    else:
        lines.append("NEXT EVENT TO WATCH:\n  None flagged in the next 7 days.")
    lines.append("")

    lines.append("SOURCES:\n  " + "; ".join(d.sources))
    lines.append("")
    lines.append(BAR)
    return "\n".join(lines)
