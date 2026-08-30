"""Read-only MetaTrader 5 quote provider (V1.1.1).

STRICTLY READ-ONLY. This module calls exactly four MetaTrader5 package
functions -- `initialize`, `symbol_info`, `symbol_info_tick`, `shutdown` --
and nothing else. It must never import or call `order_send`, `order_check`,
`positions_get`, `orders_get`, or reference `TRADE_ACTION_DEAL` /
`TRADE_ACTION_PENDING` / any other order-placement constant. No method on
this class creates, modifies, or closes any position or order. See
`tests/unit/test_no_order_execution_path.py`, which greps the whole `app/`
tree for exactly those names and fails the build if any appear outside
this docstring's own prohibition notice.

`AUTO_EXECUTION` stays hardcoded `False` at the settings level
(`app.config.settings`) independent of anything in this file -- this
provider has no way to flip it even if it wanted to.

The `MetaTrader5` package only exists on Windows and is not a project
dependency (it is not installed in this sandbox). Import is therefore
lazy and wrapped so that a machine without it -- or without a running MT5
terminal -- fails closed with `DataSourceUnavailable` rather than raising
an unhandled `ImportError`, exactly like every other source adapter in
this project (see `app.sources.repository`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from app.common.errors import DataSourceUnavailable
from app.domain.enums import Freshness
from app.market.price_provider import CurrentMarketQuote


class _Mt5Module(Protocol):
    """Structural shape of the subset of the MetaTrader5 module this
    provider uses -- lets tests inject a fake module with no real
    MetaTrader5 install anywhere."""

    def initialize(self) -> bool: ...
    def shutdown(self) -> None: ...
    def last_error(self) -> object: ...
    def symbol_info(self, symbol: str) -> Any | None: ...
    def symbol_info_tick(self, symbol: str) -> Any | None: ...


def _try_import_mt5() -> _Mt5Module | None:
    try:
        import MetaTrader5 as mt5_module  # noqa: N813 -- matches the package's own convention
    except ImportError:
        return None
    return mt5_module  # type: ignore[no-any-return]


class MT5ReadOnlyPriceProvider:
    """Reads bid/ask and symbol specs from a locally-running MT5 terminal.

    Never logs in with stored credentials and never connects a real
    account automatically -- `initialize()` only attaches to whatever
    terminal (if any) is already open and logged in on this machine. If
    the `MetaTrader5` package isn't installed, or no terminal is running,
    this fails closed to `DataSourceUnavailable`; it never fabricates a
    quote.
    """

    def __init__(self, *, mt5_module: _Mt5Module | None = None) -> None:
        self._mt5 = mt5_module if mt5_module is not None else _try_import_mt5()

    def get_quote(self, symbol: str) -> CurrentMarketQuote:
        if self._mt5 is None:
            raise DataSourceUnavailable(
                "mt5", "the MetaTrader5 package is not installed on this machine"
            )
        mt5 = self._mt5
        if not mt5.initialize():
            raise DataSourceUnavailable(
                "mt5", f"could not attach to a running MT5 terminal: {mt5.last_error()}"
            )
        try:
            info = mt5.symbol_info(symbol)
            if info is None:
                raise DataSourceUnavailable(
                    "mt5", f"symbol '{symbol}' not found in this terminal's Market Watch"
                )
            tick = mt5.symbol_info_tick(symbol)
            if tick is None or not tick.bid or not tick.ask:
                raise DataSourceUnavailable("mt5", f"no live tick data available for '{symbol}'")
            return CurrentMarketQuote(
                symbol=symbol,
                broker_symbol=symbol,
                bid=float(tick.bid),
                ask=float(tick.ask),
                timestamp=datetime.fromtimestamp(tick.time, tz=UTC),
                source="MT5_READ_ONLY",
                # classified by the caller against MAX_QUOTE_AGE_SECONDS
                freshness=Freshness.UNKNOWN,
                tick_size=getattr(info, "point", None),
                tick_value=getattr(info, "trade_tick_value", None),
                contract_size=getattr(info, "trade_contract_size", None),
                volume_min=getattr(info, "volume_min", None),
                volume_max=getattr(info, "volume_max", None),
                volume_step=getattr(info, "volume_step", None),
                stops_level=getattr(info, "trade_stops_level", None),
            )
        finally:
            mt5.shutdown()
