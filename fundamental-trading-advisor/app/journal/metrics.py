"""Paper-trading performance metrics (section 23), computed from whatever
journal entries already have an outcome recorded (status is a terminal
state and r_multiple/pnl_percent are populated). Producing those outcomes
in the first place is the job of a separate, decoupled paper-trade
evaluator that replays real market data -- out of scope for this version
(see README limitations); this module only aggregates whatever outcomes
already exist in the journal.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.enums import Direction, JournalStatus
from app.journal.models import JournalEntry

TERMINAL_STATUSES = {
    JournalStatus.STOPPED,
    JournalStatus.TAKE_PROFIT,
    JournalStatus.FUNDAMENTAL_EXIT,
    JournalStatus.TIME_EXIT,
}


@dataclass
class PerformanceReport:
    total_recommendations: int = 0
    no_trade_count: int = 0
    closed_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float | None = None
    average_r: float | None = None
    profit_factor: float | None = None
    expectancy_r: float | None = None
    cumulative_r: float = 0.0
    by_direction: dict[str, int] = field(default_factory=dict)
    by_asset: dict[str, int] = field(default_factory=dict)
    by_conviction_bucket: dict[str, int] = field(default_factory=dict)


def _conviction_bucket(conviction: int) -> str:
    if conviction >= 80:
        return "high (80-100)"
    if conviction >= 60:
        return "medium (60-79)"
    return "low (<60)"


def compute_performance(entries: list[JournalEntry]) -> PerformanceReport:
    report = PerformanceReport(total_recommendations=len(entries))
    closed_r_values: list[float] = []
    gains = 0.0
    losses_sum = 0.0

    for entry in entries:
        if entry.direction is Direction.NO_TRADE:
            report.no_trade_count += 1
            continue
        report.by_direction[entry.direction.value] = (
            report.by_direction.get(entry.direction.value, 0) + 1
        )
        report.by_asset[entry.asset] = report.by_asset.get(entry.asset, 0) + 1
        report.by_conviction_bucket[_conviction_bucket(entry.conviction)] = (
            report.by_conviction_bucket.get(_conviction_bucket(entry.conviction), 0) + 1
        )
        if entry.status in TERMINAL_STATUSES and entry.r_multiple is not None:
            report.closed_trades += 1
            closed_r_values.append(entry.r_multiple)
            if entry.r_multiple > 0:
                report.wins += 1
                gains += entry.r_multiple
            elif entry.r_multiple < 0:
                report.losses += 1
                losses_sum += abs(entry.r_multiple)

    if closed_r_values:
        report.cumulative_r = round(sum(closed_r_values), 3)
        report.average_r = round(sum(closed_r_values) / len(closed_r_values), 3)
        report.expectancy_r = report.average_r
        if report.wins + report.losses > 0:
            report.win_rate = round(report.wins / (report.wins + report.losses), 3)
        if losses_sum > 0:
            report.profit_factor = round(gains / losses_sum, 3)

    return report
