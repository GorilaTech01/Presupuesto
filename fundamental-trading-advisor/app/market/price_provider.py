"""Current-price lookup -- used ONLY for entry/SL/TP/risk math, spread and
broker-restriction checks (section 3). Never for deciding direction.

No live MT5 connection exists in this version (see app.broker.pepperstone),
so the default provider reads from a small manually-maintained JSON file.
The CLI always prints a reminder that the price must be re-verified live in
MT5 before execution.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from app.common.errors import DataSourceUnavailable


class PriceQuote(BaseModel):
    symbol: str
    bid: float
    ask: float
    as_of: datetime

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2

    @property
    def spread(self) -> float:
        return self.ask - self.bid


class PriceProvider(Protocol):
    def get_quote(self, symbol: str) -> PriceQuote: ...


class ManualPriceFileProvider:
    """Reads current quotes from a small JSON file the user maintains by
    hand (e.g. copied from MT5) until a live connection exists.

    Expected format:
        {"EURUSD": {"bid": 1.1000, "ask": 1.1002, "as_of": "2026-08-29T12:00:00Z"}, ...}
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def get_quote(self, symbol: str) -> PriceQuote:
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
        return PriceQuote(
            symbol=symbol,
            bid=float(entry["bid"]),
            ask=float(entry["ask"]),
            as_of=datetime.fromisoformat(entry["as_of"]).astimezone(UTC),
        )
