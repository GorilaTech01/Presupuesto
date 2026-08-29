from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from app.cli.main import app

runner = CliRunner()


def test_cli_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "weekly" in result.output


def test_cli_weekly_runs_and_prints_no_trade(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FRED_API_KEY", "")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "data" / "cache"))
    monkeypatch.setenv("JOURNAL_DIR", str(tmp_path / "data" / "journal"))
    result = runner.invoke(app, ["weekly"])
    assert result.exit_code == 0
    assert "FUNDAMENTAL TRADING ADVISOR" in result.output


def test_cli_journal_lists_empty_journal(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("JOURNAL_DIR", str(tmp_path / "journal"))
    result = runner.invoke(app, ["journal"])
    assert result.exit_code == 0
