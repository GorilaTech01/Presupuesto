from __future__ import annotations

from pathlib import Path

from app.common.errors import DataSourceUnavailable
from app.config.settings import Settings
from app.sources.repository import FundamentalDataRepository


def test_fetch_many_records_errors_without_raising(tmp_path: Path):
    settings = Settings(
        _env_file=None, fred_api_key=None, data_dir=tmp_path, cache_dir=tmp_path / "cache"
    )
    repo = FundamentalDataRepository(settings)
    try:
        result = repo.fetch_many(["us_fed_funds_target_upper", "us_cpi_yoy"])
        assert result.facts == {}
        assert "us_fed_funds_target_upper" in result.errors
        assert "us_cpi_yoy" in result.errors
    finally:
        repo.close()


def test_fetch_one_unknown_indicator_raises(tmp_path: Path):
    settings = Settings(_env_file=None, data_dir=tmp_path, cache_dir=tmp_path / "cache")
    repo = FundamentalDataRepository(settings)
    try:
        try:
            repo.fetch_one("totally_unknown_indicator")
            raise AssertionError("expected DataSourceUnavailable")
        except DataSourceUnavailable:
            pass
    finally:
        repo.close()


def test_missing_helper_on_fetch_result(tmp_path: Path):
    settings = Settings(_env_file=None, data_dir=tmp_path, cache_dir=tmp_path / "cache")
    repo = FundamentalDataRepository(settings)
    try:
        result = repo.fetch_many(["us_fed_funds_target_upper"])
        assert result.missing(["us_fed_funds_target_upper"]) == ["us_fed_funds_target_upper"]
    finally:
        repo.close()
