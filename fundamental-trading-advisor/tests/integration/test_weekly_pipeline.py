"""End-to-end pipeline test with no API keys / no network configured.

This exercises the whole fail-closed path: repository -> analysis ->
catalysts -> decision -> (missing price) -> NO_TRADE -> journal write,
without ever making a real HTTP request (no key means the FRED/EIA clients
raise before opening a connection; ECB/Eurostat/BLS/CFTC calls would only
fire if a test forgot to isolate them, which respx across the suite would
catch as an unexpected real request).
"""

from __future__ import annotations

from pathlib import Path

from app.config.settings import Settings
from app.domain.enums import Direction
from app.journal.journal import RecommendationJournal
from app.reporting.human_report import render_human_report
from app.reporting.json_report import to_machine_readable
from app.services.weekly_pipeline import WeeklyPipeline


def test_weekly_pipeline_fails_closed_to_no_trade_without_data(tmp_path: Path):
    settings = Settings(
        _env_file=None,
        fred_api_key=None,
        eia_api_key=None,
        data_dir=tmp_path,
        cache_dir=tmp_path / "cache",
        journal_dir=tmp_path / "journal",
    )
    pipeline = WeeklyPipeline(settings)
    try:
        comparison = pipeline.run(["EURUSD", "XAUUSD", "BTCUSD"])
    finally:
        pipeline.close()

    assert len(comparison.candidates) == 3
    assert comparison.decision.direction is Direction.NO_TRADE
    assert comparison.decision.trade_plan is None

    # journal got exactly one entry for this run
    journal = RecommendationJournal(settings.journal_dir / "journal.jsonl")
    entries = journal.load_all()
    assert len(entries) == 1
    assert entries[0].direction is Direction.NO_TRADE


def test_weekly_pipeline_rejects_wrong_candidate_count(tmp_path: Path):
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        cache_dir=tmp_path / "cache",
        journal_dir=tmp_path / "journal",
    )
    pipeline = WeeklyPipeline(settings)
    try:
        try:
            pipeline.run(["EURUSD", "XAUUSD"])
            raise AssertionError("expected ValueError for candidate count != 3")
        except ValueError:
            pass
    finally:
        pipeline.close()


def test_human_and_json_reports_render_without_error(tmp_path: Path):
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        cache_dir=tmp_path / "cache",
        journal_dir=tmp_path / "journal",
    )
    pipeline = WeeklyPipeline(settings)
    try:
        comparison = pipeline.run(["EURUSD", "XAUUSD", "BTCUSD"])
    finally:
        pipeline.close()

    text = render_human_report(comparison, settings.timezone)
    assert "FUNDAMENTAL TRADING ADVISOR" in text
    assert "NO_TRADE" in text

    payload = to_machine_readable(comparison)
    assert payload["decision"] == "NO_TRADE"
    assert len(payload["candidates"]) == 3
