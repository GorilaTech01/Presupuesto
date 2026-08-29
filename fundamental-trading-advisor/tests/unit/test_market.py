from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.common.errors import DataSourceUnavailable
from app.market.price_provider import ManualPriceFileProvider
from app.market.universe import get_asset


def test_get_asset_known_symbol():
    definition = get_asset("EURUSD")
    assert definition.base_ccy == "EUR"
    assert definition.quote_ccy == "USD"


def test_get_asset_unknown_symbol_raises():
    with pytest.raises(KeyError):
        get_asset("NOTREAL")


def test_manual_price_provider_missing_file_raises(tmp_path: Path):
    provider = ManualPriceFileProvider(tmp_path / "missing.json")
    with pytest.raises(DataSourceUnavailable):
        provider.get_quote("EURUSD")


def test_manual_price_provider_reads_quote(tmp_path: Path):
    path = tmp_path / "prices.json"
    path.write_text(
        json.dumps({"EURUSD": {"bid": 1.1000, "ask": 1.1002, "as_of": "2026-08-29T12:00:00+00:00"}})
    )
    provider = ManualPriceFileProvider(path)
    quote = provider.get_quote("EURUSD")
    assert quote.mid == pytest.approx(1.1001)
    assert quote.spread == pytest.approx(0.0002)
    assert quote.as_of.tzinfo is not None


def test_manual_price_provider_missing_symbol_raises(tmp_path: Path):
    path = tmp_path / "prices.json"
    path.write_text(
        json.dumps({"EURUSD": {"bid": 1.1, "ask": 1.1002, "as_of": "2026-08-29T12:00:00+00:00"}})
    )
    provider = ManualPriceFileProvider(path)
    with pytest.raises(DataSourceUnavailable):
        provider.get_quote("XAUUSD")
