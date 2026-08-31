"""Qt table models (V1.2).

Pure presentation mapping over already-typed domain objects
(`MonitoredTradeOpportunity`, `JournalEntry`). No score, conviction, or
state is recomputed here -- every cell is a direct field read, and a
missing value is rendered as an em dash, never invented (spec section 15).
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt

from app.common.time_utils import format_utc
from app.domain.models import MonitoredTradeOpportunity
from app.journal.models import JournalEntry

MISSING = "—"


def _fmt(value: object) -> str:
    if value is None:
        return MISSING
    if isinstance(value, float):
        return f"{value:.5g}"
    return str(value)


def _conviction_1_10(conviction: int) -> str:
    if not conviction:
        return "0/10"
    return f"{max(1, round(conviction / 10))}/10"


class OpportunitiesTableModel(QAbstractTableModel):
    COLUMNS = (
        "ID",
        "Asset",
        "Direction",
        "Bias",
        "Action",
        "Conviction",
        "Score",
        "Created",
        "Updated",
        "Valid Until",
        "Next Catalyst",
    )

    def __init__(self, opportunities: list[MonitoredTradeOpportunity] | None = None) -> None:
        super().__init__()
        self._rows: list[MonitoredTradeOpportunity] = list(opportunities or [])

    def set_opportunities(self, opportunities: list[MonitoredTradeOpportunity]) -> None:
        self.beginResetModel()
        self._rows = list(opportunities)
        self.endResetModel()

    def opportunity_at(self, row: int) -> MonitoredTradeOpportunity | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def rowCount(  # noqa: N802
        self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()
    ) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(  # noqa: N802
        self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()
    ) -> int:
        return 0 if parent.isValid() else len(self.COLUMNS)

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if role != Qt.ItemDataRole.DisplayRole or orientation != Qt.Orientation.Horizontal:
            return None
        return self.COLUMNS[section]

    def data(
        self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        opportunity = self._rows[index.row()]
        column = index.column()
        if column == 0:
            return opportunity.opportunity_id[:8]
        if column == 1:
            return opportunity.asset
        if column == 2:
            return opportunity.direction.value
        if column == 3:
            return opportunity.fundamental_bias.value
        if column == 4:
            return opportunity.trade_action.value
        if column == 5:
            return _conviction_1_10(opportunity.conviction)
        if column == 6:
            return f"{opportunity.current_score:+.2f}"
        if column == 7:
            return format_utc(opportunity.created_at)
        if column == 8:
            return format_utc(opportunity.updated_at)
        if column == 9:
            return format_utc(opportunity.valid_until)
        if column == 10:
            event = opportunity.next_relevant_event
            return f"{event.indicator} ({event.country})" if event is not None else MISSING
        return None


class JournalTableModel(QAbstractTableModel):
    COLUMNS = (
        "Date",
        "Asset",
        "Direction",
        "Status",
        "Conviction",
        "Recommended Entry",
        "Actual Entry",
        "Exit",
        "PnL",
        "R Multiple",
        "Exit Reason",
    )

    def __init__(self, entries: list[JournalEntry] | None = None) -> None:
        super().__init__()
        self._rows: list[JournalEntry] = list(entries or [])

    def set_entries(self, entries: list[JournalEntry]) -> None:
        self.beginResetModel()
        self._rows = list(entries)
        self.endResetModel()

    def entry_at(self, row: int) -> JournalEntry | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def rowCount(  # noqa: N802
        self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()
    ) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(  # noqa: N802
        self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()
    ) -> int:
        return 0 if parent.isValid() else len(self.COLUMNS)

    def headerData(  # noqa: N802
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if role != Qt.ItemDataRole.DisplayRole or orientation != Qt.Orientation.Horizontal:
            return None
        return self.COLUMNS[section]

    def data(
        self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        entry = self._rows[index.row()]
        column = index.column()
        if column == 0:
            return format_utc(entry.generated_at)
        if column == 1:
            return entry.asset
        if column == 2:
            return entry.direction.value
        if column == 3:
            return entry.status.value
        if column == 4:
            return _conviction_1_10(entry.conviction)
        if column == 5:
            return _fmt(entry.recommended_entry)
        if column == 6:
            return _fmt(entry.entry_price_actual_or_simulated)
        if column == 7:
            return _fmt(entry.exit_price)
        if column == 8:
            return _fmt(entry.pnl_points)
        if column == 9:
            return _fmt(entry.r_multiple)
        if column == 10:
            return _fmt(entry.exit_reason)
        return None
