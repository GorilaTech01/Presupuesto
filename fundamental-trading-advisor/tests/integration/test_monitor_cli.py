"""CLI smoke tests for the V1.1 monitoring commands (`monitor`,
`journal enter`, `journal skip`) -- single-pass invocation, no daemon, no
live network call.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from app.cli.main import app
from app.config.settings import Settings
from app.domain.enums import Direction, FundamentalBias, TradeAction, TriggerStatus
from app.domain.models import MonitoredTradeOpportunity
from app.monitor.store import OpportunityStore

runner = CliRunner()


def _env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FRED_API_KEY", "")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "data" / "cache"))
    monkeypatch.setenv("JOURNAL_DIR", str(tmp_path / "data" / "journal"))


def _settings_for(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "data" / "cache",
        journal_dir=tmp_path / "data" / "journal",
    )


def _seed_opportunity(settings: Settings, *, ready: bool) -> MonitoredTradeOpportunity:
    from datetime import timedelta

    from app.domain.models import TradePlan

    now = datetime.now(UTC)
    plan = (
        TradePlan(
            asset="EURUSD",
            symbol="EURUSD",
            direction=Direction.SELL,
            conviction_1_10=7,
            horizon="3-5 days",
            order_type="manual",
            fundamental_trigger="test",
            estimated_entry=1.10,
            stop_loss=1.105,
            distance_to_sl=0.005,
            take_profit=1.09,
            distance_to_tp=0.01,
            risk_reward=2.0,
            time_stop="Friday close",
            cancellation_condition="n/a",
            fundamental_invalidation="n/a",
            early_exit_condition="n/a",
            main_catalysts=[],
            main_risks=[],
        )
        if ready
        else None
    )
    opportunity = MonitoredTradeOpportunity(
        opportunity_id="opp-cli-1",
        recommendation_id="rec-cli-1",
        created_at=now,
        updated_at=now,
        asset="EURUSD",
        symbol="EURUSD",
        fundamental_bias=FundamentalBias.BEARISH,
        trade_action=TradeAction.READY_TO_TRADE if ready else TradeAction.WAIT,
        direction=Direction.SELL,
        conviction=70,
        original_score=-0.9,
        current_score=-0.9,
        threshold=0.6,
        horizon="3-5 days",
        entry_condition="test",
        catalysts=[],
        fundamental_invalidation="n/a",
        cancellation_conditions=[],
        time_stop="Friday close",
        valid_until=now + timedelta(days=3),
        data_cutoff=now,
        last_evaluated_at=now,
        next_relevant_event=None,
        trigger_status=TriggerStatus.CONFIRMED,
        trade_plan=plan,
    )
    store = OpportunityStore(settings.data_dir / "monitor" / "opportunities.jsonl")
    store.save(opportunity)
    return opportunity


def test_monitor_command_reports_no_active_opportunities(tmp_path: Path, monkeypatch):
    _env(tmp_path, monkeypatch)
    result = runner.invoke(app, ["monitor"])
    assert result.exit_code == 0
    assert "No active monitored opportunities" in result.output


def test_monitor_command_unknown_opportunity_id_errors(tmp_path: Path, monkeypatch):
    _env(tmp_path, monkeypatch)
    result = runner.invoke(app, ["monitor", "--opportunity-id", "does-not-exist"])
    assert result.exit_code == 1
    assert "No monitored opportunity" in result.output


def test_monitor_command_json_out_writes_file(tmp_path: Path, monkeypatch):
    # `monitor` always performs a REAL re-evaluation, not just a re-print of
    # stored state -- with no API keys / no network configured (this sandbox),
    # every indicator fails closed, so a previously READY_TO_TRADE opportunity
    # correctly collapses back to NO_TRADE rather than keeping a stale call.
    _env(tmp_path, monkeypatch)
    settings = _settings_for(tmp_path)
    _seed_opportunity(settings, ready=True)
    out_path = tmp_path / "out.json"
    result = runner.invoke(
        app, ["monitor", "--opportunity-id", "opp-cli-1", "--json-out", str(out_path)]
    )
    assert result.exit_code == 0
    payload = json.loads(out_path.read_text())
    assert payload[0]["opportunity_id"] == "opp-cli-1"
    assert payload[0]["trade_action"] == "NO_TRADE"


def test_journal_enter_unknown_opportunity_errors(tmp_path: Path, monkeypatch):
    _env(tmp_path, monkeypatch)
    result = runner.invoke(
        app, ["journal", "enter", "--opportunity-id", "does-not-exist", "--price", "1.1"]
    )
    assert result.exit_code == 1
    assert "No monitored opportunity" in result.output


def test_journal_skip_unknown_opportunity_errors(tmp_path: Path, monkeypatch):
    _env(tmp_path, monkeypatch)
    result = runner.invoke(app, ["journal", "skip", "--opportunity-id", "does-not-exist"])
    assert result.exit_code == 1
    assert "No monitored opportunity" in result.output


def test_journal_enter_records_manual_entry_never_sends_an_order(tmp_path: Path, monkeypatch):
    _env(tmp_path, monkeypatch)
    settings = _settings_for(tmp_path)
    _seed_opportunity(settings, ready=True)

    from app.journal.journal import RecommendationJournal
    from app.journal.models import JournalEntry

    journal = RecommendationJournal(settings.journal_dir / "journal.jsonl")
    journal.add(
        JournalEntry(
            recommendation_id="rec-cli-1",
            generated_at=datetime.now(UTC),
            data_cutoff=datetime.now(UTC),
            asset="EURUSD",
            symbol="EURUSD",
            direction=Direction.SELL,
            conviction=70,
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
    )

    result = runner.invoke(
        app, ["journal", "enter", "--opportunity-id", "opp-cli-1", "--price", "1.1005"]
    )
    assert result.exit_code == 0
    assert "No order was sent" in result.output

    updated = journal.find("rec-cli-1")
    assert updated is not None
    assert updated.entry_price_actual_or_simulated == 1.1005


def test_quote_command_reports_price_unavailable_with_no_provider_configured(
    tmp_path: Path, monkeypatch
):
    """No manual_prices.json and no MetaTrader5 install in this sandbox --
    the CLI must fail closed with PRICE_UNAVAILABLE, never a guessed price."""
    _env(tmp_path, monkeypatch)
    result = runner.invoke(app, ["quote", "EURUSD"])
    assert result.exit_code == 1
    assert "PRICE_UNAVAILABLE" in result.output


def test_quote_command_prints_bid_ask_from_manual_file(tmp_path: Path, monkeypatch):
    _env(tmp_path, monkeypatch)
    settings = _settings_for(tmp_path)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "manual_prices.json").write_text(
        json.dumps({"EURUSD": {"bid": 1.1000, "ask": 1.1002, "as_of": "2026-09-01T12:00:00Z"}})
    )
    result = runner.invoke(app, ["quote", "EURUSD"])
    assert result.exit_code == 0
    assert "Bid: 1.1" in result.output
    assert "Source: MANUAL_FILE" in result.output
    assert "Fresh: YES" in result.output
