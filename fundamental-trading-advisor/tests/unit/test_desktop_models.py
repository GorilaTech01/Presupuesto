"""Qt table models (V1.2): pure presentation mapping over already-typed
domain objects. Every cell must be a direct field read -- these tests
pin that a missing value renders as an em dash rather than being
invented, and that no cell recomputes a score/conviction/status."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import QApplication

from app.desktop.models import MISSING, JournalTableModel, OpportunitiesTableModel
from app.domain.enums import Direction, FundamentalBias, JournalStatus, TradeAction, TriggerStatus
from app.domain.models import MonitoredTradeOpportunity
from app.journal.models import JournalEntry

_NOW = datetime(2026, 9, 1, tzinfo=UTC)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _opportunity() -> MonitoredTradeOpportunity:
    return MonitoredTradeOpportunity(
        opportunity_id="opp-12345678",
        recommendation_id="rec-1",
        created_at=_NOW,
        updated_at=_NOW,
        asset="EURUSD",
        symbol="EURUSD",
        fundamental_bias=FundamentalBias.BEARISH,
        trade_action=TradeAction.WAIT,
        direction=Direction.SELL,
        conviction=65,
        original_score=-0.7,
        current_score=-0.7,
        threshold=0.6,
        horizon="Friday close",
        entry_condition="wait for confirmation",
        catalysts=[],
        fundamental_invalidation="n/a",
        cancellation_conditions=[],
        time_stop="Friday close",
        valid_until=_NOW + timedelta(days=3),
        data_cutoff=_NOW,
        last_evaluated_at=_NOW,
        next_relevant_event=None,
        trigger_status=TriggerStatus.PENDING,
    )


def _journal_entry(**overrides: object) -> JournalEntry:
    fields: dict[str, object] = {
        "recommendation_id": "rec-1",
        "generated_at": _NOW,
        "data_cutoff": _NOW,
        "asset": "EURUSD",
        "symbol": "EURUSD",
        "direction": Direction.SELL,
        "conviction": 65,
        "entry_condition": "test",
        "recommended_entry": None,
        "stop_loss": None,
        "take_profit": None,
        "risk_reward": None,
        "time_stop": "Friday close",
        "fundamental_thesis": "test",
        "drivers": [],
        "catalysts": [],
        "invalidation": "n/a",
        "sources": [],
    }
    fields.update(overrides)
    return JournalEntry(**fields)  # type: ignore[arg-type]


def test_opportunities_table_model_row_and_column_counts() -> None:
    _app()
    model = OpportunitiesTableModel([_opportunity()])
    assert model.rowCount() == 1
    assert model.columnCount() == len(OpportunitiesTableModel.COLUMNS)


def test_opportunities_table_model_maps_fields_without_recomputing() -> None:
    _app()
    opportunity = _opportunity()
    model = OpportunitiesTableModel([opportunity])
    index = lambda col: model.index(0, col)  # noqa: E731
    assert model.data(index(0)) == "opp-1234"  # short id, direct slice
    assert model.data(index(1)) == "EURUSD"
    assert model.data(index(2)) == "SELL"
    assert model.data(index(3)) == "BEARISH"
    assert model.data(index(4)) == "WAIT"
    assert model.data(index(6)) == "-0.70"
    assert model.data(index(10)) == MISSING  # no next_relevant_event -> never invented


def test_opportunities_table_model_opportunity_at_returns_underlying_object() -> None:
    _app()
    opportunity = _opportunity()
    model = OpportunitiesTableModel([opportunity])
    assert model.opportunity_at(0) is opportunity
    assert model.opportunity_at(5) is None


def test_opportunities_table_model_out_of_bounds_index_is_invalid() -> None:
    _app()
    model = OpportunitiesTableModel([])
    assert model.data(QModelIndex()) is None


def test_journal_table_model_missing_fields_render_as_em_dash() -> None:
    _app()
    model = JournalTableModel([_journal_entry()])
    index = lambda col: model.index(0, col)  # noqa: E731
    assert model.data(index(5)) == MISSING  # recommended_entry
    assert model.data(index(6)) == MISSING  # actual entry
    assert model.data(index(7)) == MISSING  # exit price
    assert model.data(index(10)) == MISSING  # exit reason


def test_journal_table_model_maps_populated_fields() -> None:
    _app()
    entry = _journal_entry(
        entry_price_actual_or_simulated=1.1005,
        status=JournalStatus.ACTIVE_SIMULATION,
    )
    model = JournalTableModel([entry])
    index = lambda col: model.index(0, col)  # noqa: E731
    assert model.data(index(3)) == "ACTIVE_SIMULATION"
    assert model.data(index(6)) == "1.1005"


def test_journal_table_model_header_data() -> None:
    _app()
    model = JournalTableModel([])
    assert model.headerData(0, Qt.Orientation.Horizontal) == "Date"
    assert model.headerData(0, Qt.Orientation.Vertical) is None


def test_set_opportunities_resets_model_rows() -> None:
    _app()
    model = OpportunitiesTableModel([_opportunity()])
    model.set_opportunities([])
    assert model.rowCount() == 0
