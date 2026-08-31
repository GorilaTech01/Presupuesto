"""MT5ReadOnlyPriceProvider (V1.1.1). No real MetaTrader5 install exists in
this sandbox (or in CI) -- every test injects a fake module via
`mt5_module=`, matching the `_Mt5Module` protocol, so this suite never
depends on Windows or a real terminal. The provider is strictly read-only:
these tests also confirm it never calls anything beyond `initialize`,
`symbol_info`, `symbol_info_tick`, `shutdown`, `last_error`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from app.common.errors import DataSourceUnavailable
from app.market.mt5_provider import MT5ReadOnlyPriceProvider, _try_import_mt5


@dataclass
class _FakeSymbolInfo:
    point: float = 0.00001
    trade_tick_value: float = 1.0
    trade_contract_size: float = 100_000.0
    volume_min: float = 0.01
    volume_max: float = 100.0
    volume_step: float = 0.01
    trade_stops_level: int = 0


@dataclass
class _FakeTick:
    bid: float
    ask: float
    time: int


class _FakeMt5:
    """A minimal fake of the subset of the MetaTrader5 module this
    provider uses -- never implements order_send/order_check/positions_get,
    proving the provider cannot call them even if it wanted to."""

    def __init__(
        self,
        *,
        initialize_ok: bool = True,
        symbol_info: _FakeSymbolInfo | None = _FakeSymbolInfo(),
        tick: _FakeTick | None = None,
    ) -> None:
        self._initialize_ok = initialize_ok
        self._symbol_info = symbol_info
        self._tick = tick if tick is not None else _FakeTick(1.1000, 1.1002, 1735689600)
        self.shutdown_called = False
        self.initialize_calls = 0

    def initialize(self) -> bool:
        self.initialize_calls += 1
        return self._initialize_ok

    def shutdown(self) -> None:
        self.shutdown_called = True

    def last_error(self) -> object:
        return "IPC_TIMEOUT" if not self._initialize_ok else None

    def symbol_info(self, symbol: str) -> _FakeSymbolInfo | None:
        return self._symbol_info

    def symbol_info_tick(self, symbol: str) -> _FakeTick | None:
        return self._tick


def test_mt5_provider_fails_gracefully_when_package_not_installed():
    provider = MT5ReadOnlyPriceProvider(mt5_module=None)
    with pytest.raises(DataSourceUnavailable):
        provider.get_quote("EURUSD")


def test_real_import_helper_returns_none_when_metatrader5_not_installed():
    # MetaTrader5 genuinely isn't installed in this environment -- this
    # exercises the real ImportError path, not just the injected-None case.
    assert _try_import_mt5() is None


def test_mt5_provider_fails_gracefully_when_terminal_unavailable():
    fake = _FakeMt5(initialize_ok=False)
    provider = MT5ReadOnlyPriceProvider(mt5_module=fake)
    with pytest.raises(DataSourceUnavailable, match="terminal"):
        provider.get_quote("EURUSD")


def test_mt5_provider_returns_valid_quote_with_broker_specs():
    fake = _FakeMt5()
    provider = MT5ReadOnlyPriceProvider(mt5_module=fake)
    quote = provider.get_quote("EURUSD")
    assert quote.bid == 1.1000
    assert quote.ask == 1.1002
    assert quote.source == "MT5_READ_ONLY"
    assert quote.tick_size == 0.00001
    assert quote.contract_size == 100_000.0
    assert quote.volume_min == 0.01
    assert isinstance(quote.timestamp, datetime)
    assert quote.timestamp.tzinfo == UTC


def test_mt5_provider_shuts_down_after_every_call():
    fake = _FakeMt5()
    provider = MT5ReadOnlyPriceProvider(mt5_module=fake)
    provider.get_quote("EURUSD")
    assert fake.shutdown_called is True


def test_mt5_provider_shuts_down_even_on_symbol_not_found():
    fake = _FakeMt5(symbol_info=None)
    provider = MT5ReadOnlyPriceProvider(mt5_module=fake)
    with pytest.raises(DataSourceUnavailable):
        provider.get_quote("NOTASYMBOL")
    assert fake.shutdown_called is True


def test_mt5_provider_symbol_not_found_raises():
    fake = _FakeMt5(symbol_info=None)
    provider = MT5ReadOnlyPriceProvider(mt5_module=fake)
    with pytest.raises(DataSourceUnavailable, match="not found"):
        provider.get_quote("NOTASYMBOL")


def test_mt5_provider_no_tick_data_raises():
    fake = _FakeMt5()
    fake._tick = None  # type: ignore[assignment]
    provider = MT5ReadOnlyPriceProvider(mt5_module=fake)
    with pytest.raises(DataSourceUnavailable, match="tick"):
        provider.get_quote("EURUSD")


def test_mt5_provider_zero_bid_ask_treated_as_no_tick_data():
    fake = _FakeMt5(tick=_FakeTick(0.0, 0.0, 1735689600))
    provider = MT5ReadOnlyPriceProvider(mt5_module=fake)
    with pytest.raises(DataSourceUnavailable):
        provider.get_quote("EURUSD")


def test_mt5_provider_never_calls_order_functions():
    """The fake module doesn't define order_send/order_check/positions_get
    at all -- if the provider ever tried to call one, this would raise
    AttributeError instead of returning a quote, so a clean quote here is
    itself proof no such call was made."""
    fake = _FakeMt5()
    assert not hasattr(fake, "order_send")
    assert not hasattr(fake, "order_check")
    assert not hasattr(fake, "positions_get")
    provider = MT5ReadOnlyPriceProvider(mt5_module=fake)
    quote = provider.get_quote("EURUSD")
    assert quote is not None
