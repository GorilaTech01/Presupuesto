"""Machine-readable output (section 27). Built directly from the typed
`FundamentalDecision`/`WeeklyComparison` models -- never hand-assembled from
scratch, so it can never drift from what the human report says.
"""

from __future__ import annotations

from typing import Any

from app.common.time_utils import format_utc
from app.domain.models import WeeklyComparison


def to_machine_readable(comparison: WeeklyComparison) -> dict[str, Any]:
    d = comparison.decision
    tp = d.trade_plan
    return {
        "generated_at": format_utc(comparison.generated_at),
        "data_cutoff": format_utc(comparison.data_cutoff_utc),
        "data_cutoff_local": comparison.data_cutoff_local,
        "candidates": [c.asset for c in comparison.candidates],
        "selected_symbol": comparison.selected_symbol,
        "incomplete_reason": comparison.incomplete_reason,
        "decision": d.direction.value,
        "symbol": d.symbol,
        "conviction": d.conviction,
        "conviction_1_10": d.conviction_1_10,
        "fundamental_trigger": d.entry_condition,
        "entry": tp.estimated_entry if tp else None,
        "stop_loss": tp.stop_loss if tp else None,
        "take_profit": tp.take_profit if tp else None,
        "risk_reward": tp.risk_reward if tp else None,
        "horizon": d.horizon,
        "invalidation": d.fundamental_invalidation,
        "catalysts": [
            {
                "indicator": c.indicator,
                "country": c.country,
                "severity": c.severity.value,
                "date_utc": format_utc(c.date_utc),
                "consensus": c.consensus,
                "previous": c.previous,
                "actual": c.actual,
                "favors_thesis_if": c.favors_thesis_if,
                "weakens_thesis_if": c.weakens_thesis_if,
                "invalidates_thesis_if": c.invalidates_thesis_if,
            }
            for c in d.catalysts
        ],
        "drivers": [
            {
                "category": drv.category.value,
                "label": drv.label,
                "contribution": drv.contribution,
                "rationale": drv.rationale,
            }
            for drv in d.top_drivers
        ],
        "sources": d.sources,
        "data_freshness": d.data_freshness.value,
        "time_stop": d.time_stop,
        "risks": d.risks,
    }
