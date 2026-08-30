"""Opportunities screen (spec sections 13-14): a read-only table of every
monitored opportunity plus a tabbed detail panel for the selected row. No
score/conviction/threshold/catalyst is editable from here."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QTableView,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.common.time_utils import format_utc
from app.domain.models import MonitoredTradeOpportunity

from ..models import OpportunitiesTableModel

MISSING = "—"


class OpportunitiesView(QWidget):
    refresh_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._model = OpportunitiesTableModel()
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel("Opportunities")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        header.addStretch(1)
        self.refresh_button = QPushButton("Refresh UI Data")
        self.refresh_button.clicked.connect(self.refresh_requested)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        splitter = QSplitter()
        self.table = QTableView()
        self.table.setModel(self._model)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        splitter.addWidget(self.table)

        self.detail_tabs = QTabWidget()
        self.overview_text = QTextEdit(readOnly=True)
        self.catalysts_text = QTextEdit(readOnly=True)
        self.history_text = QTextEdit(readOnly=True)
        self.sources_text = QTextEdit(readOnly=True)
        self.detail_tabs.addTab(self.overview_text, "Overview")
        self.detail_tabs.addTab(self.catalysts_text, "Catalysts")
        self.detail_tabs.addTab(self.history_text, "History")
        self.detail_tabs.addTab(self.sources_text, "Sources")
        splitter.addWidget(self.detail_tabs)
        splitter.setSizes([500, 400])
        layout.addWidget(splitter, stretch=1)

        self.table.selectionModel().selectionChanged.connect(self._on_selection_changed)

    def set_opportunities(self, opportunities: list[MonitoredTradeOpportunity]) -> None:
        self._model.set_opportunities(opportunities)
        self._clear_detail()

    def _on_selection_changed(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            self._clear_detail()
            return
        opportunity = self._model.opportunity_at(rows[0].row())
        if opportunity is None:
            self._clear_detail()
            return
        self._render_detail(opportunity)

    def _clear_detail(self) -> None:
        for widget in (
            self.overview_text,
            self.catalysts_text,
            self.history_text,
            self.sources_text,
        ):
            widget.setPlainText("")

    def _render_detail(self, opportunity: MonitoredTradeOpportunity) -> None:
        cancellation_lines = [f"  - {c}" for c in opportunity.cancellation_conditions] or [
            "  (none)"
        ]
        overview = [
            f"Opportunity ID: {opportunity.opportunity_id}",
            f"Asset: {opportunity.asset}",
            f"Fundamental Bias: {opportunity.fundamental_bias.value}",
            f"Trade Action: {opportunity.trade_action.value}",
            f"Trigger Status: {opportunity.trigger_status.value}",
            "",
            f"Fundamental Invalidation: {opportunity.fundamental_invalidation}",
            "",
            "Cancellation Conditions:",
            *cancellation_lines,
            "",
            f"Data Cutoff: {format_utc(opportunity.data_cutoff)}",
        ]
        if opportunity.cancellation_reason:
            overview.insert(5, f"Cancellation Reason: {opportunity.cancellation_reason}")
        if opportunity.readiness_blocker:
            overview.insert(5, f"Readiness Blocker: {opportunity.readiness_blocker}")
        self.overview_text.setPlainText("\n".join(overview))

        catalysts = [
            f"{c.indicator} ({c.country}) — {c.severity.value} — {format_utc(c.date_utc)}"
            for c in opportunity.catalysts
        ] or ["(no catalysts recorded)"]
        self.catalysts_text.setPlainText("\n".join(catalysts))

        history = [
            f"{format_utc(h.at)}  {h.trade_action.value:14s}  score={h.score:+.2f}  {h.reason}"
            for h in opportunity.decision_history
        ] or ["(no history recorded)"]
        self.history_text.setPlainText("\n".join(history))

        sources = list(opportunity.source_snapshot) or ["(no source snapshot recorded)"]
        self.sources_text.setPlainText("\n".join(sources))
