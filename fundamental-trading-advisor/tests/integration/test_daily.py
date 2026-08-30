"""`python -m app daily` (docs/daily_workflow.md): pure orchestration of
`weekly` + `monitor --all` + one consolidated review. No new scoring,
decision, or monitoring logic is exercised here -- these tests monkeypatch
`app.services.weekly_pipeline.build_decision_draft` (the same seam
`WeeklyPipeline` and `TradeOpportunityMonitorService` already share) to
drive each state deterministically, with no live network call.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from app.cli.main import app
from app.config.settings import Settings
from app.domain.enums import CatalystSeverity, Direction, ExecutionReadiness, Freshness
from app.domain.models import CatalystEvent
from app.fundamental.candidate import CandidateEvaluation
from app.fundamental.decision import DecisionDraft
from app.monitor import service as monitor_service_module
from app.monitor.store import OpportunityStore
from app.services import weekly_pipeline as weekly_pipeline_module

runner = CliRunner()

_NOW = datetime(2026, 9, 1, tzinfo=UTC)


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


def _catalyst(
    *,
    severity: CatalystSeverity = CatalystSeverity.CRITICAL,
    actual: float | None = None,
    consensus: float | None = 150.0,
    indicator: str = "us_nonfarm_payrolls",
) -> CatalystEvent:
    return CatalystEvent(
        symbol_context="US",
        date_utc=_NOW,
        date_local=_NOW,
        country="US",
        indicator=indicator,
        severity=severity,
        actual=actual,
        consensus=consensus,
        favors_thesis_if="prints below consensus",
        weakens_thesis_if="prints above consensus",
    )


def _draft(
    *,
    direction: Direction = Direction.SELL,
    trade_action: ExecutionReadiness = ExecutionReadiness.ENTER_NOW,
    catalysts: list[CatalystEvent] | None = None,
) -> DecisionDraft:
    return DecisionDraft(
        symbol="EURUSD",
        direction=direction,
        trade_action=trade_action,
        conviction=70,
        thesis="test thesis",
        top_drivers=[],
        catalysts=catalysts or [],
        entry_condition="test entry condition",
        fundamental_invalidation="test invalidation",
        risks=[],
        time_stop="Friday close",
        data_freshness=Freshness.FRESH,
        sources=["TESTSRC"],
        conviction_breakdown=None,
        reasons=[],
    )


def _patch_weekly_draft(monkeypatch, forced_draft: DecisionDraft):
    """Forces every candidate in the 3-way comparison to evaluate to
    `forced_draft` -- the seam WeeklyPipeline._evaluate_one AND
    TradeOpportunityMonitorService.refresh_one both call
    (build_decision_draft), monkeypatched at both import sites (exactly as
    test_monitor_service.py does for app.monitor.service alone) so that
    `daily`'s immediate monitor.refresh_all() pass -- which re-fetches
    independently of weekly's own creation call -- sees the SAME forced
    data instead of falling back to the real (unavailable-in-this-sandbox)
    fetch and silently overwriting the just-created state. No second
    decision engine is introduced; this only controls what the one shared
    function returns."""

    def fake_build_decision_draft(
        definition, fetch_result, *, catalyst_service, decision_engine, timezone_name
    ):
        from app.domain.models import FundamentalScore

        evaluation = CandidateEvaluation(
            definition=definition,
            score=FundamentalScore(
                subject=definition.asset, total=0.0, drivers=[], data_cutoff_utc=_NOW, warnings=[]
            ),
            bias=-0.9 if definition.asset == "EURUSD" else 0.0,
        )
        draft = (
            forced_draft
            if definition.asset == "EURUSD"
            else _draft(direction=Direction.NO_TRADE, trade_action=ExecutionReadiness.NONE)
        )
        return draft, evaluation, "US"

    monkeypatch.setattr(weekly_pipeline_module, "build_decision_draft", fake_build_decision_draft)
    monkeypatch.setattr(monitor_service_module, "build_decision_draft", fake_build_decision_draft)


def test_daily_no_trade_when_no_data_available(tmp_path: Path, monkeypatch):
    # with no API keys / no network configured, every indicator fails
    # closed, so the real reason is "insufficient evidence: N required
    # indicators unavailable" -- the generic fallback text only appears
    # when comparison.decision.reasons is empty, which this scenario
    # never hits (see render_daily_review's fallback branch).
    _env(tmp_path, monkeypatch)
    result = runner.invoke(app, ["daily"])
    assert result.exit_code == 0
    assert "DAILY REVIEW" in result.output
    assert "NO_TRADE" in result.output
    assert "Reason:" in result.output
    assert "insufficient evidence" in result.output


def test_daily_shows_wait_with_next_catalyst(tmp_path: Path, monkeypatch):
    _env(tmp_path, monkeypatch)
    pending = _catalyst(actual=None)
    _patch_weekly_draft(
        monkeypatch,
        _draft(
            direction=Direction.SELL, trade_action=ExecutionReadiness.ENTER_NOW, catalysts=[pending]
        ),
    )
    result = runner.invoke(app, ["daily"])
    assert result.exit_code == 0
    assert "Selected asset:" in result.output
    assert "EURUSD" in result.output
    assert "Trade action:" in result.output
    assert "WAIT" in result.output
    assert "Do not enter yet." in result.output
    assert "NEXT CATALYST" in result.output
    assert "us_nonfarm_payrolls" in result.output


def test_daily_shows_ready_to_trade_full_plan(tmp_path: Path, monkeypatch):
    _env(tmp_path, monkeypatch)
    settings = _settings_for(tmp_path)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_dir / "manual_prices.json").write_text(
        json.dumps({"EURUSD": {"bid": 1.1000, "ask": 1.1002, "as_of": "2026-09-01T12:00:00Z"}})
    )
    _patch_weekly_draft(
        monkeypatch, _draft(direction=Direction.SELL, trade_action=ExecutionReadiness.ENTER_NOW)
    )
    result = runner.invoke(app, ["daily"])
    assert result.exit_code == 0
    assert "READY_TO_TRADE" in result.output
    assert "Manual execution only." in result.output
    assert "Entry:" in result.output
    assert "Stop Loss:" in result.output


def test_daily_shows_cancelled_when_catalyst_contradicts(tmp_path: Path, monkeypatch):
    _env(tmp_path, monkeypatch)
    # dovish US surprise (actual below consensus) contradicts a US-favored
    # SELL thesis -- a hawkish one (actual above consensus) would CONFIRM
    # it instead, per FundamentalTriggerEvaluator's semantics.
    contradicting = _catalyst(actual=100.0, consensus=150.0)
    _patch_weekly_draft(
        monkeypatch,
        _draft(
            direction=Direction.SELL,
            trade_action=ExecutionReadiness.ENTER_NOW,
            catalysts=[contradicting],
        ),
    )
    result = runner.invoke(app, ["daily"])
    assert result.exit_code == 0
    assert "CANCELLED" in result.output
    assert "Do not enter this trade." in result.output


def test_daily_lists_other_monitored_opportunities_from_prior_days(tmp_path: Path, monkeypatch):
    from datetime import timedelta

    from app.domain.enums import FundamentalBias, TradeAction, TriggerStatus
    from app.domain.models import MonitoredTradeOpportunity

    _env(tmp_path, monkeypatch)
    settings = _settings_for(tmp_path)
    store = OpportunityStore(settings.data_dir / "monitor" / "opportunities.jsonl")
    prior = MonitoredTradeOpportunity(
        opportunity_id="prior-1",
        recommendation_id="rec-prior-1",
        created_at=_NOW - timedelta(days=2),
        updated_at=_NOW - timedelta(days=2),
        asset="XAUUSD",
        symbol="XAUUSD",
        fundamental_bias=FundamentalBias.BULLISH,
        trade_action=TradeAction.WAIT,
        direction=Direction.BUY,
        conviction=60,
        original_score=0.7,
        current_score=0.7,
        threshold=0.6,
        horizon="3-5 days",
        entry_condition="wait",
        catalysts=[],
        fundamental_invalidation="n/a",
        cancellation_conditions=[],
        time_stop="Friday close",
        valid_until=_NOW + timedelta(days=10),
        data_cutoff=_NOW,
        last_evaluated_at=_NOW,
        next_relevant_event=None,
        trigger_status=TriggerStatus.PENDING,
    )
    store.save(prior)

    result = runner.invoke(app, ["daily"])
    assert result.exit_code == 0
    assert "OTHER MONITORED OPPORTUNITIES" in result.output
    assert "XAUUSD" in result.output


def test_daily_is_safe_to_run_repeatedly_with_no_new_data(tmp_path: Path, monkeypatch):
    """Re-running daily with nothing changed must not crash and must
    converge to the same reported state -- no-op idempotency at the
    monitor.refresh_all() layer (already proven at the unit level in
    test_monitor_service.py; this just confirms the CLI wiring doesn't
    break it)."""
    _env(tmp_path, monkeypatch)
    first = runner.invoke(app, ["daily"])
    second = runner.invoke(app, ["daily"])
    assert first.exit_code == 0
    assert second.exit_code == 0
    assert "NO_TRADE" in first.output
    assert "NO_TRADE" in second.output


def test_daily_json_output_has_expected_structure(tmp_path: Path, monkeypatch):
    _env(tmp_path, monkeypatch)
    out_path = tmp_path / "daily.json"
    result = runner.invoke(app, ["daily", "--json-out", str(out_path)])
    assert result.exit_code == 0
    payload = json.loads(out_path.read_text())
    assert "weekly" in payload
    assert "todays_opportunity" in payload
    assert "other_opportunities" in payload
    assert payload["weekly"]["decision"] == "NO_TRADE"


def test_daily_never_calls_a_second_decision_engine(monkeypatch, tmp_path: Path):
    """Sanity check on the orchestration itself: daily must call the exact
    same build_decision_draft seam weekly/monitor already share -- verified
    here by confirming the monkeypatch on that one function is what drives
    the result (if daily had its own scoring path, this patch would have no
    effect and the assertion below would fail)."""
    _env(tmp_path, monkeypatch)
    _patch_weekly_draft(
        monkeypatch, _draft(direction=Direction.SELL, trade_action=ExecutionReadiness.ENTER_NOW)
    )
    result = runner.invoke(app, ["daily"])
    assert result.exit_code == 0
    assert "EURUSD" in result.output
    assert "BEARISH" in result.output
