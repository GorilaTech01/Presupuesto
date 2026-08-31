"""Settings & System Status screen (spec sections 16-17).

Entirely read-only in this phase: no widget here can change a setting or
flip `AUTO_EXECUTION` on. Secret values (API keys/tokens) are never shown
-- only whether one is configured, per `SystemStatusController`."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.desktop.controllers import SystemStatus

MISSING = "—"


def _row(grid: QGridLayout, row: int, label: str, value: str) -> None:
    label_widget = QLabel(label)
    label_widget.setObjectName("fieldLabel")
    value_widget = QLabel(value)
    value_widget.setObjectName("fieldValue")
    grid.addWidget(label_widget, row, 0)
    grid.addWidget(value_widget, row, 1)


class SettingsStatusView(QWidget):
    refresh_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel("Settings & System Status")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        header.addStretch(1)
        self.refresh_button = QPushButton("Refresh UI Data")
        self.refresh_button.clicked.connect(self.refresh_requested)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        self.status_card = QFrame()
        self.status_card.setObjectName("card")
        self.status_grid = QGridLayout(self.status_card)
        layout.addWidget(self.status_card)

        self.settings_card = QFrame()
        self.settings_card.setObjectName("card")
        self.settings_grid = QGridLayout(self.settings_card)
        layout.addWidget(self.settings_card)

        layout.addStretch(1)

        disclaimer = QLabel(
            "This application provides decision-support analysis. It does not "
            "guarantee returns and does not execute trades automatically."
        )
        disclaimer.setObjectName("disclaimer")
        disclaimer.setWordWrap(True)
        layout.addWidget(disclaimer)

    def render_status(self, status: SystemStatus) -> None:
        self._clear_grid(self.status_grid)
        mt5_terminal = (
            "not applicable (MT5 disabled)"
            if status.mt5_terminal_available is None
            else ("AVAILABLE" if status.mt5_terminal_available else "UNAVAILABLE")
        )
        rows = [
            ("Application Version", status.version),
            (
                "Fundamental Engine",
                "OK"
                if status.fundamental_engine_ok
                else f"ERROR: {status.fundamental_engine_detail}",
            ),
            ("Price Provider", status.price_provider_mode.upper()),
            ("MT5 Enabled", str(status.mt5_enabled)),
            ("MT5 Terminal", mt5_terminal),
            ("Auto Execution", "DISABLED" if not status.auto_execution else "ENABLED (!!)"),
            ("Paper Trading", str(status.paper_trading)),
            ("Timezone", status.timezone),
        ]
        for i, (label, value) in enumerate(rows):
            _row(self.status_grid, i, label, value)

        offset = len(rows) + 1
        _row(self.status_grid, offset - 1, "Data Sources", "")
        for i, source in enumerate(status.data_sources):
            _row(
                self.status_grid,
                offset + i,
                f"  {source.name}",
                "configured" if source.configured else "not configured",
            )

        self._clear_grid(self.settings_grid)
        settings_rows = [
            ("Risk Percent", f"{status.risk_percent:.2%}"),
            (
                "Account Equity",
                MISSING if status.account_equity is None else f"{status.account_equity:,.2f}",
            ),
            ("Max Quote Age (s)", str(status.max_quote_age_seconds)),
        ]
        for i, (label, value) in enumerate(settings_rows):
            _row(self.settings_grid, i, label, value)

    @staticmethod
    def _clear_grid(grid: QGridLayout) -> None:
        while grid.count():
            item = grid.takeAt(0)
            if item is None:
                break
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
