"""Journal screen (spec section 15): a read-only render of the trade
journal. Missing fields show an em dash -- this view never invents data."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from app.journal.models import JournalEntry

from ..models import JournalTableModel


class JournalView(QWidget):
    refresh_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._model = JournalTableModel()
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel("Journal")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        header.addStretch(1)
        self.refresh_button = QPushButton("Refresh UI Data")
        self.refresh_button.clicked.connect(self.refresh_requested)
        header.addWidget(self.refresh_button)
        layout.addLayout(header)

        self.table = QTableView()
        self.table.setModel(self._model)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table, stretch=1)

    def set_entries(self, entries: list[JournalEntry]) -> None:
        self._model.set_entries(entries)
