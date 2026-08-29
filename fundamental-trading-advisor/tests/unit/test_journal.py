from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.domain.enums import Direction, JournalStatus
from app.journal.benchmark import export_benchmark_csv, export_benchmark_jsonl
from app.journal.journal import RecommendationJournal
from app.journal.metrics import compute_performance
from app.journal.models import SYSTEM_NAME, JournalEntry


def _entry(**overrides) -> JournalEntry:
    base = dict(
        generated_at=datetime.now(UTC),
        data_cutoff=datetime.now(UTC),
        asset="EURUSD",
        symbol="EURUSD",
        direction=Direction.BUY,
        conviction=80,
        entry_condition="x",
        recommended_entry=1.10,
        stop_loss=1.09,
        take_profit=1.12,
        risk_reward=2.0,
        time_stop="Friday",
        fundamental_thesis="thesis",
        drivers=["driver1"],
        catalysts=["NFP"],
        invalidation="inv",
        sources=["FRED"],
    )
    base.update(overrides)
    return JournalEntry(**base)


def test_journal_add_and_load_roundtrip(tmp_path: Path):
    journal = RecommendationJournal(tmp_path / "journal.jsonl")
    entry = _entry()
    journal.add(entry)
    loaded = journal.load_all()
    assert len(loaded) == 1
    assert loaded[0].recommendation_id == entry.recommendation_id
    assert loaded[0].direction is Direction.BUY


def test_journal_update_changes_status(tmp_path: Path):
    journal = RecommendationJournal(tmp_path / "journal.jsonl")
    entry = _entry()
    journal.add(entry)
    updated = journal.update(entry.recommendation_id, status=JournalStatus.STOPPED, r_multiple=-1.0)
    assert updated.status is JournalStatus.STOPPED
    assert journal.find(entry.recommendation_id).r_multiple == -1.0


def test_journal_empty_returns_empty_list(tmp_path: Path):
    journal = RecommendationJournal(tmp_path / "journal.jsonl")
    assert journal.load_all() == []


def test_benchmark_csv_export_uses_system_name(tmp_path: Path):
    journal = RecommendationJournal(tmp_path / "journal.jsonl")
    entry = _entry()
    journal.add(entry)
    out = tmp_path / "benchmark.csv"
    export_benchmark_csv(journal.load_all(), out)
    content = out.read_text()
    assert SYSTEM_NAME in content
    assert "EURUSD" in content


def test_benchmark_jsonl_export(tmp_path: Path):
    journal = RecommendationJournal(tmp_path / "journal.jsonl")
    journal.add(_entry())
    out = tmp_path / "benchmark.jsonl"
    export_benchmark_jsonl(journal.load_all(), out)
    lines = out.read_text().splitlines()
    assert len(lines) == 1
    assert SYSTEM_NAME in lines[0]


def test_compute_performance_counts_no_trade_separately():
    entries = [
        _entry(
            direction=Direction.NO_TRADE,
            conviction=0,
            recommended_entry=None,
            stop_loss=None,
            take_profit=None,
            risk_reward=None,
        )
    ]
    report = compute_performance(entries)
    assert report.no_trade_count == 1
    assert report.closed_trades == 0


def test_compute_performance_win_rate_and_profit_factor():
    win = _entry(status=JournalStatus.TAKE_PROFIT, r_multiple=2.0)
    loss = _entry(status=JournalStatus.STOPPED, r_multiple=-1.0)
    report = compute_performance([win, loss])
    assert report.closed_trades == 2
    assert report.wins == 1
    assert report.losses == 1
    assert report.win_rate == 0.5
    assert report.profit_factor == 2.0
