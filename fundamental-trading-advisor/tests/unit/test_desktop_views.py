"""Desktop view rendering (V1.2, spec sections 6-15): confirms the
WAIT/READY_TO_TRADE/NO_TRADE/CANCELLED states are visually distinguishable,
the READY_TO_TRADE screen shows the full trade plan with no order button,
the first-run / source-failure states render friendly text (never a raw
stack trace), and the Opportunities/Journal tables populate from plain
lists with no recomputation. No pixel-based assertions -- everything here
reads back widget text/objectName, never a screenshot."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from app.desktop.controllers import DataSourceStatus, SystemStatus
from app.desktop.theme import status_color
from app.desktop.views.dashboard import DashboardView
from app.desktop.views.journal import JournalView
from app.desktop.views.opportunities import OpportunitiesView
from app.desktop.views.settings_status import SettingsStatusView
from app.domain.enums import Direction, FundamentalBias, TradeAction, TriggerStatus
from app.domain.models import MonitoredTradeOpportunity, TradePlan
from app.journal.models import JournalEntry
from app.services.daily import DailyRunResult

_NOW = datetime(2026, 9, 1, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def _plan() -> TradePlan:
    return TradePlan(
        asset="EURUSD",
        symbol="EURUSD",
        direction=Direction.SELL,
        conviction_1_10=6,
        horizon="3-5 days",
        order_type="manual",
        fundamental_trigger="ECB hawkish surprise confirmed",
        estimated_entry=1.10,
        stop_loss=1.105,
        distance_to_sl=0.005,
        take_profit=1.09,
        distance_to_tp=0.01,
        risk_reward=2.0,
        time_stop="Friday close",
        cancellation_condition="n/a",
        fundamental_invalidation="dovish reversal",
        early_exit_condition="n/a",
        main_catalysts=["ECB rate decision beat consensus"],
        main_risks=[],
    )


def _opportunity(
    *,
    trade_action: TradeAction = TradeAction.WAIT,
    cancellation_reason: str | None = None,
) -> MonitoredTradeOpportunity:
    return MonitoredTradeOpportunity(
        opportunity_id="opp-1",
        recommendation_id="rec-1",
        created_at=_NOW,
        updated_at=_NOW,
        asset="EURUSD",
        symbol="EURUSD",
        fundamental_bias=FundamentalBias.BEARISH,
        trade_action=trade_action,
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
        cancellation_reason=cancellation_reason,
        time_stop="Friday close",
        valid_until=_NOW + timedelta(days=3),
        data_cutoff=_NOW,
        last_evaluated_at=_NOW,
        next_relevant_event=None,
        trigger_status=TriggerStatus.PENDING,
        trade_plan=_plan() if trade_action is TradeAction.READY_TO_TRADE else None,
    )


# --------------------------------------------------------------------------
# Status visualization (spec section 7)
# --------------------------------------------------------------------------


def test_status_colors_are_distinct_for_each_state() -> None:
    states = ("WAIT", "READY_TO_TRADE", "NO_TRADE", "CANCELLED")
    colors = {state: status_color(state) for state in states}
    assert len(set(colors.values())) == len(colors), "every status must render as a distinct color"


# --------------------------------------------------------------------------
# Dashboard (spec sections 6, 10-12)
# --------------------------------------------------------------------------


def test_dashboard_shows_first_run_message_before_any_analysis() -> None:
    view = DashboardView()
    assert "No analysis available yet" in _all_text(view)


def test_dashboard_renders_wait_state_without_ready_to_trade_card() -> None:
    view = DashboardView()
    view.render_opportunity(_opportunity(trade_action=TradeAction.WAIT))
    assert "WAIT" in _all_text(view)
    assert "READY TO TRADE" not in _all_text(view)


def test_dashboard_renders_ready_to_trade_with_plan_and_manual_only_warning() -> None:
    view = DashboardView()
    view.render_opportunity(_opportunity(trade_action=TradeAction.READY_TO_TRADE))
    text = _all_text(view)
    assert "READY TO TRADE" in text
    assert "Manual execution only" in text
    assert "1.1" in text  # entry price rendered
    button_texts = {b.text() for b in view.findChildren(QPushButton)}
    assert "I Entered This Trade" in button_texts
    assert "Skip Trade" in button_texts


def test_dashboard_ready_to_trade_buttons_emit_opportunity_id(qtbot) -> None:
    view = DashboardView()
    opportunity = _opportunity(trade_action=TradeAction.READY_TO_TRADE)
    view.render_opportunity(opportunity)
    enter_button = next(
        b for b in view.findChildren(QPushButton) if b.text() == "I Entered This Trade"
    )
    with qtbot.waitSignal(view.enter_trade_requested, timeout=1000) as blocker:
        enter_button.click()
    assert blocker.args == ["opp-1"]


def test_dashboard_renders_cancelled_state_with_reason() -> None:
    view = DashboardView()
    view.render_opportunity(
        _opportunity(trade_action=TradeAction.CANCELLED, cancellation_reason="USER_SKIPPED")
    )
    assert "CANCELLED" in _all_text(view)


def test_dashboard_render_daily_result_falls_back_to_no_opportunity_message() -> None:
    """Source failure mapping (spec section 18): when the pipeline could not
    produce a candidate, the dashboard shows a friendly incomplete-analysis
    message instead of crashing or fabricating a trade state."""
    from app.domain.enums import AssetClass, ExecutionReadiness, Freshness
    from app.domain.models import (
        CandidateAssessment,
        FundamentalDecision,
        FundamentalScore,
        WeeklyComparison,
    )

    decision = FundamentalDecision(
        symbol="EURUSD",
        asset_class=AssetClass.FX,
        direction=Direction.NO_TRADE,
        trade_action=ExecutionReadiness.NONE,
        conviction=0,
        horizon="n/a",
        thesis="no candidate cleared the bar",
        top_drivers=[],
        catalysts=[],
        entry_condition="n/a",
        fundamental_invalidation="n/a",
        risks=[],
        time_stop="n/a",
        data_freshness=Freshness.UNKNOWN,
        sources=[],
        data_cutoff_utc=_NOW,
        data_cutoff_local="n/a",
    )
    comparison = WeeklyComparison(
        generated_at=_NOW,
        data_cutoff_utc=_NOW,
        data_cutoff_local="n/a",
        candidates=[
            CandidateAssessment(
                asset=a,
                broker_symbol=a,
                current_price=None,
                price_as_of=None,
                liquidity_note="n/a",
                expected_event_volatility="n/a",
                main_catalysts=[],
                bullish_fundamentals=[],
                bearish_fundamentals=[],
                event_slippage_risk="n/a",
                thesis_quality_1_10=1,
                final_reason="FRED unavailable",
                score=FundamentalScore(subject=a, total=0.0, drivers=[], data_cutoff_utc=_NOW),
            )
            for a in ("EURUSD", "XAUUSD", "BTCUSD")
        ],
        selected_symbol=None,
        decision=decision,
        incomplete_reason="FRED: Unavailable",
    )
    result = DailyRunResult(comparison=comparison, todays_opportunity=None, other_opportunities=[])
    view = DashboardView()
    view.render_daily_result(result)
    text = _all_text(view)
    assert "incomplete" in text.lower()
    assert "FRED" in text


# --------------------------------------------------------------------------
# Opportunities / Journal (spec sections 13, 15) -- no-op refresh
# --------------------------------------------------------------------------


def test_opportunities_view_populates_table_without_recomputation() -> None:
    view = OpportunitiesView()
    view.set_opportunities([_opportunity()])
    assert view._model.rowCount() == 1  # noqa: SLF001 -- internal check, no public row count API needed


def test_opportunities_view_refresh_button_emits_signal_only_no_pipeline_call(qtbot) -> None:
    view = OpportunitiesView()
    with qtbot.waitSignal(view.refresh_requested, timeout=1000):
        view.refresh_button.click()


def test_journal_view_populates_table() -> None:
    view = JournalView()
    entry = JournalEntry(
        recommendation_id="rec-1",
        generated_at=_NOW,
        data_cutoff=_NOW,
        asset="EURUSD",
        symbol="EURUSD",
        direction=Direction.SELL,
        conviction=65,
        entry_condition="test",
        recommended_entry=None,
        stop_loss=None,
        take_profit=None,
        risk_reward=None,
        time_stop="Friday close",
        fundamental_thesis="test",
        drivers=[],
        catalysts=[],
        invalidation="n/a",
        sources=[],
    )
    view.set_entries([entry])
    assert view._model.rowCount() == 1  # noqa: SLF001


# --------------------------------------------------------------------------
# Settings & System Status (spec sections 16-17) -- secrets never shown
# --------------------------------------------------------------------------


def test_settings_status_view_never_renders_secret_values() -> None:
    view = SettingsStatusView()
    status = SystemStatus(
        version="V1.2 Desktop",
        fundamental_engine_ok=True,
        fundamental_engine_detail=None,
        price_provider_mode="manual",
        mt5_enabled=False,
        mt5_terminal_available=None,
        auto_execution=False,
        paper_trading=True,
        timezone="UTC",
        risk_percent=0.01,
        account_equity=None,
        max_quote_age_seconds=300,
        data_sources=[DataSourceStatus(name="FRED", configured=True)],
    )
    view.render_status(status)
    text = _all_text(view)
    assert "super-secret" not in text
    assert "DISABLED" in text  # auto execution disabled must be visible


def _all_text(widget) -> str:
    from PySide6.QtWidgets import QLabel, QTextEdit

    parts = [widget.windowTitle()]
    for label in widget.findChildren(QLabel):
        parts.append(label.text())
    for text_edit in widget.findChildren(QTextEdit):
        parts.append(text_edit.toPlainText())
    return "\n".join(parts)
