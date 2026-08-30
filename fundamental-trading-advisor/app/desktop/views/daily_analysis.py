"""Daily Analysis screen: the full weekly comparison behind today's
Dashboard summary -- the 3-candidate table plus the selected thesis. Pure
presentation over `WeeklyComparison`; no candidate is re-scored here."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.common.time_utils import format_utc
from app.domain.models import WeeklyComparison

MISSING = "—"


class DailyAnalysisView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        title = QLabel("Daily Analysis")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        self.meta_label = QLabel("No analysis run yet.")
        layout.addWidget(self.meta_label)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Asset", "Score", "Thesis Quality", "Event Volatility", "Liquidity", "Final Reason"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)

        self.thesis_label = QLabel("Selected Thesis")
        self.thesis_label.setObjectName("fieldLabel")
        layout.addWidget(self.thesis_label)
        self.thesis_text = QTextEdit()
        self.thesis_text.setReadOnly(True)
        layout.addWidget(self.thesis_text, stretch=1)

    def render_comparison(self, comparison: WeeklyComparison) -> None:
        selected = comparison.selected_symbol or MISSING
        self.meta_label.setText(
            f"Generated: {format_utc(comparison.generated_at)}   "
            f"Data cutoff: {format_utc(comparison.data_cutoff_utc)}   "
            f"Selected: {selected}"
        )
        self.table.setRowCount(len(comparison.candidates))
        for row, candidate in enumerate(comparison.candidates):
            values = [
                candidate.asset,
                f"{candidate.score.total:+.2f}",
                str(candidate.thesis_quality_1_10),
                candidate.expected_event_volatility,
                candidate.liquidity_note,
                candidate.final_reason,
            ]
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(value))

        decision = comparison.decision
        thesis_lines = [decision.thesis, ""]
        if decision.top_drivers:
            thesis_lines.append("Top drivers:")
            thesis_lines.extend(
                f"  - {d.category.value}: {d.label} ({d.contribution:+.2f}) — {d.rationale}"
                for d in decision.top_drivers
            )
        if comparison.incomplete_reason:
            thesis_lines.append("")
            thesis_lines.append(f"Analysis incomplete: {comparison.incomplete_reason}")
        self.thesis_text.setPlainText("\n".join(thesis_lines))
