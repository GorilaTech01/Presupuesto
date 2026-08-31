"""Current-price lookup -- used ONLY for entry/SL/TP/risk math, position
sizing, and spread/broker-restriction checks (section 3, and V1.1.1). Never
for deciding direction, bias, conviction, or catalyst confirmation -- see
`docs/monitoring.md` for the explicit no-directional-price-signal guarantee
and the tests that enforce it.

`CurrentMarketQuote` is the one typed result every `PriceProvider`
implementation returns, whether it came from a live read-only MT5 terminal
(`app.market.mt5_provider`) or the manual fallback file below. The optional
broker-spec fields (`tick_size`, `tick_value`, `contract_size`,
`volume_*`, `stops_level`) are informational -- risk/position-sizing math
still uses the fixture-based `SymbolSpec` from `app.broker.mt5_specs` via
`BrokerSymbolResolver`, so a missing live spec never blocks sizing.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from app.common.errors import DataSourceUnavailable
from app.domain.enums import Freshness


class CurrentMarketQuote(BaseModel):
    symbol: str
    broker_symbol: str
    bid: float
    ask: float
    timestamp: datetime
    source: str
    freshness: Freshness = Freshness.UNKNOWN
    tick_size: float | None = None
    tick_value: float | None = None
    contract_size: float | None = None
    volume_min: float | None = None
    volume_max: float | None = None
    volume_step: float | None = None
    stops_level: int | None = None

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2

    @property
    def spread(self) -> float:
        return self.ask - self.bid


class PriceProvider(Protocol):
    def get_quote(self, symbol: str) -> CurrentMarketQuote: ...


class ManualPriceFileProvider:
    """Reads current quotes from a small JSON file the user maintains by
    hand (e.g. copied from MT5). Always available as an explicit fallback,
    regardless of `PRICE_PROVIDER` mode -- never removed.

    Expected format:
        {"EURUSD": {"bid": 1.1000, "ask": 1.1002, "as_of": "2026-08-29T12:00:00Z"}, ...}
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def get_quote(self, symbol: str) -> CurrentMarketQuote:
        if not self.path.exists():
            raise DataSourceUnavailable(
                "manual_price_file",
                f"{self.path} does not exist. Create it with current MT5 bid/ask "
                f"for '{symbol}' (see README) before running trade-plan sizing.",
            )
        data = json.loads(self.path.read_text())
        entry = data.get(symbol)
        if entry is None:
            raise DataSourceUnavailable(
                "manual_price_file", f"no quote for '{symbol}' in {self.path}"
            )
        return CurrentMarketQuote(
            symbol=symbol,
            broker_symbol=symbol,
            bid=float(entry["bid"]),
            ask=float(entry["ask"]),
            timestamp=datetime.fromisoformat(entry["as_of"]).astimezone(UTC),
            source="MANUAL_FILE",
        )
