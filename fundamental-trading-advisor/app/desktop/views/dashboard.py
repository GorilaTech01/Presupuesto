"""Dashboard screen (spec sections 6-12).

Shows the current fundamental status at a glance, the two primary action
buttons ("Run Daily Analysis" / "Re-check Opportunities"), and -- only
when an opportunity is READY_TO_TRADE -- the full trade plan with its two
manual-only follow-up actions ("I Entered This Trade" / "Skip Trade").
This view only renders fields already produced by the engine; it never
computes a score, a status, or a color rule beyond a plain lookup table in
`app.desktop.theme`.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.common.time_utils import format_utc
from app.domain.models import MonitoredTradeOpportunity
from app.services.daily import DailyRunResult

from ..theme import status_color

MISSING = "—"


def _field(label: str, value: str) -> QWidget:
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)
    label_widget = QLabel(label)
    label_widget.setObjectName("fieldLabel")
    value_widget = QLabel(value)
    value_widget.setObjectName("fieldValue")
    value_widget.setWordWrap(True)
    layout.addWidget(label_widget)
    layout.addWidget(value_widget)
    return box


class DashboardView(QWidget):
    run_daily_requested = Signal()
    recheck_requested = Signal()
    enter_trade_requested = Signal(str)  # opportunity_id
    skip_trade_requested = Signal(str)  # opportunity_id

    def __init__(self) -> None:
        super().__init__()
        self._opportunity: MonitoredTradeOpportunity | None = None
        self._build_ui()
        self.show_first_run()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        title = QLabel("Dashboard")
        title.setObjectName("sectionTitle")
        outer.addWidget(title)

        actions = QHBoxLayout()
        self.run_daily_button = QPushButton("Run Daily Analysis")
        self.run_daily_button.setObjectName("primaryButton")
        self.run_daily_button.clicked.connect(self.run_daily_requested)
        self.recheck_button = QPushButton("Re-check Opportunities")
        self.recheck_button.clicked.connect(self.recheck_requested)
        actions.addWidget(self.run_daily_button)
        actions.addWidget(self.recheck_button)
        actions.addStretch(1)
        outer.addLayout(actions)

        self.busy_label = QLabel("")
        self.busy_label.setStyleSheet("color: #d29922;")
        outer.addWidget(self.busy_label)

        self.provider_status_label = QLabel("")
        self.provider_status_label.setObjectName("disclaimer")
        outer.addWidget(self.provider_status_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        self._content_layout = QVBoxLayout(content)
        self._content_layout.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll, stretch=1)

    # -- state rendering -----------------------------------------------

    def show_first_run(self) -> None:
        self._opportunity = None
        self._reset_content()
        message = QLabel("No analysis available yet. Press “Run Daily Analysis” to begin.")
        message.setObjectName("fieldValue")
        self._content_layout.insertWidget(0, message)

    def set_busy(self, busy: bool, message: str = "") -> None:
        self.run_daily_button.setEnabled(not busy)
        self.recheck_button.setEnabled(not busy)
        self.busy_label.setText(message if busy else "")

    def set_provider_status(self, price_provider_mode: str, mt5_enabled: bool) -> None:
        mt5_text = "MT5 read-only: enabled" if mt5_enabled else "MT5 read-only: disabled"
        self.provider_status_label.setText(
            f"Price provider: {price_provider_mode.upper()}   |   {mt5_text}"
        )

    def render_daily_result(self, result: DailyRunResult) -> None:
        opportunity = result.todays_opportunity
        if opportunity is None:
            self._render_no_opportunity(result.comparison.incomplete_reason)
            return
        self.render_opportunity(opportunity)

    @property
    def current_opportunity(self) -> MonitoredTradeOpportunity | None:
        return self._opportunity

    def render_opportunity(self, opportunity: MonitoredTradeOpportunity) -> None:
        self._opportunity = opportunity
        self._reset_content()
        self._content_layout.insertWidget(0, self._build_summary_card(opportunity))
        if opportunity.trade_action.value == "READY_TO_TRADE" and opportunity.trade_plan:
            self._content_layout.insertWidget(1, self._build_ready_to_trade_card(opportunity))

    def _render_no_opportunity(self, incomplete_reason: str | None) -> None:
        self._opportunity = None
        self._reset_content()
        text = "Analysis incomplete: no trade candidate could be evaluated."
        if incomplete_reason:
            text += f"\n\nReason: {incomplete_reason}"
        label = QLabel(text)
        label.setObjectName("fieldValue")
        label.setWordWrap(True)
        self._content_layout.insertWidget(0, label)

    def _reset_content(self) -> None:
        while self._content_layout.count() > 1:
            item = self._content_layout.takeAt(0)
            if item is None:
                break
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _build_summary_card(self, opportunity: MonitoredTradeOpportunity) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        grid = QGridLayout(card)
        grid.setSpacing(16)

        status_badge = QLabel(opportunity.trade_action.value)
        status_badge.setObjectName("statusBadge")
        color = status_color(opportunity.trade_action.value)
        status_badge.setStyleSheet(
            f"background-color: {color}22; color: {color}; border: 1px solid {color}; "
            "border-radius: 4px; padding: 4px 12px; font-weight: 700;"
        )
        status_badge.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        grid.addWidget(status_badge, 0, 0, 1, 2)

        next_catalyst = MISSING
        if opportunity.next_relevant_event is not None:
            event = opportunity.next_relevant_event
            next_catalyst = f"{event.indicator} ({event.country}) — {format_utc(event.date_utc)}"

        fields = [
            ("Asset", opportunity.asset),
            ("Fundamental Bias", opportunity.fundamental_bias.value),
            ("Trade Action", opportunity.trade_action.value),
            (
                "Conviction",
                f"{max(1, round(opportunity.conviction / 10)) if opportunity.conviction else 0}/10",
            ),
            ("Current Score", f"{opportunity.current_score:+.2f}"),
            ("Threshold", f"{opportunity.threshold:.2f}"),
            ("Next Catalyst", next_catalyst),
            (
                "Current Action / Reason",
                opportunity.readiness_reason or opportunity.entry_condition,
            ),
            ("Last Updated", format_utc(opportunity.last_evaluated_at)),
            ("Data Cutoff", format_utc(opportunity.data_cutoff)),
        ]
        for i, (label, value) in enumerate(fields):
            row, col = divmod(i, 2)
            grid.addWidget(_field(label, value), row + 1, col)
        return card

    def _build_ready_to_trade_card(self, opportunity: MonitoredTradeOpportunity) -> QFrame:
        plan = opportunity.trade_plan
        assert plan is not None
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)

        heading = QLabel("READY TO TRADE")
        heading.setObjectName("sectionTitle")
        heading.setStyleSheet(f"color: {status_color('READY_TO_TRADE')};")
        layout.addWidget(heading)

        grid = QGridLayout()
        grid.setSpacing(16)
        fields = [
            ("Direction", plan.direction.value),
            ("Fundamental Trigger", plan.fundamental_trigger),
            ("Entry", MISSING if plan.estimated_entry is None else f"{plan.estimated_entry:g}"),
            ("Stop Loss", MISSING if plan.stop_loss is None else f"{plan.stop_loss:g}"),
            ("Take Profit", MISSING if plan.take_profit is None else f"{plan.take_profit:g}"),
            (
                "Risk : Reward",
                MISSING if plan.risk_reward is None else f"1 : {plan.risk_reward:.2f}",
            ),
            ("Risk Amount", MISSING),
            ("Position Size", MISSING),
            ("Fundamental Invalidation", plan.fundamental_invalidation),
            ("Valid Until", format_utc(opportunity.valid_until)),
        ]
        for i, (label, value) in enumerate(fields):
            row, col = divmod(i, 2)
            grid.addWidget(_field(label, value), row, col)
        layout.addLayout(grid)

        why_now = QLabel(
            "Why now:\n" + "\n".join(f"  {i + 1}. {c}" for i, c in enumerate(plan.main_catalysts))
            if plan.main_catalysts
            else "Why now: (no catalysts recorded)"
        )
        why_now.setWordWrap(True)
        layout.addWidget(why_now)

        warning = QFrame()
        warning.setObjectName("warningBanner")
        warning_layout = QVBoxLayout(warning)
        warning_label = QLabel(
            "Manual execution only. Verify price, spread and exact symbol in "
            "Pepperstone/MT5 before entering."
        )
        warning_label.setWordWrap(True)
        warning_layout.addWidget(warning_label)
        layout.addWidget(warning)

        buttons = QHBoxLayout()
        enter_button = QPushButton("I Entered This Trade")
        enter_button.setObjectName("primaryButton")
        enter_button.clicked.connect(
            lambda: self.enter_trade_requested.emit(opportunity.opportunity_id)
        )
        skip_button = QPushButton("Skip Trade")
        skip_button.setObjectName("dangerButton")
        skip_button.clicked.connect(
            lambda: self.skip_trade_requested.emit(opportunity.opportunity_id)
        )
        buttons.addWidget(enter_button)
        buttons.addWidget(skip_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return card
