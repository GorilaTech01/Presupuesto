"""Broker/MT5 instrument specification fixtures (section 20).

These are typical Pepperstone Standard-account MT5 specs, used only for
position-sizing and RR math. They are FIXTURES, not a live broker feed --
always verify in MT5 > Market Watch > Show All > Specification before
placing a real order, since brokers change specs and account types differ
(Standard/Razor/Edge).
"""

from __future__ import annotations

from pydantic import BaseModel

VERIFY_SYMBOL_NOTICE = "Verify exact symbol in MT5 > Market Watch > Show All before execution."


class SymbolSpec(BaseModel):
    symbol: str
    contract_size: float
    tick_size: float
    tick_value_usd_per_lot: float
    volume_min: float
    volume_max: float
    volume_step: float
    stops_level_points: int
    typical_spread_points: int
    as_of: str = "2026-08-29 (fixture, verify live in MT5)"


FIXTURES: dict[str, SymbolSpec] = {
    "EURUSD": SymbolSpec(
        symbol="EURUSD",
        contract_size=100_000,
        tick_size=0.00001,
        tick_value_usd_per_lot=1.0,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
        stops_level_points=0,
        typical_spread_points=10,
    ),
    "GBPUSD": SymbolSpec(
        symbol="GBPUSD",
        contract_size=100_000,
        tick_size=0.00001,
        tick_value_usd_per_lot=1.0,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
        stops_level_points=0,
        typical_spread_points=12,
    ),
    "USDJPY": SymbolSpec(
        symbol="USDJPY",
        contract_size=100_000,
        tick_size=0.001,
        tick_value_usd_per_lot=6.8,  # approximate, varies with USDJPY level -- verify live
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
        stops_level_points=0,
        typical_spread_points=10,
    ),
    "AUDUSD": SymbolSpec(
        symbol="AUDUSD",
        contract_size=100_000,
        tick_size=0.00001,
        tick_value_usd_per_lot=1.0,
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
        stops_level_points=0,
        typical_spread_points=12,
    ),
    "USDCHF": SymbolSpec(
        symbol="USDCHF",
        contract_size=100_000,
        tick_size=0.00001,
        tick_value_usd_per_lot=1.1,  # approximate, varies -- verify live
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
        stops_level_points=0,
        typical_spread_points=14,
    ),
    "USDCAD": SymbolSpec(
        symbol="USDCAD",
        contract_size=100_000,
        tick_size=0.00001,
        tick_value_usd_per_lot=0.73,  # approximate, varies -- verify live
        volume_min=0.01,
        volume_max=100.0,
        volume_step=0.01,
        stops_level_points=0,
        typical_spread_points=15,
    ),
    "XAUUSD": SymbolSpec(
        symbol="XAUUSD",
        contract_size=100,
        tick_size=0.01,
        tick_value_usd_per_lot=1.0,
        volume_min=0.01,
        volume_max=50.0,
        volume_step=0.01,
        stops_level_points=0,
        typical_spread_points=25,
    ),
    "BTCUSD": SymbolSpec(
        symbol="BTCUSD",
        contract_size=1,
        tick_size=0.01,
        tick_value_usd_per_lot=1.0,
        volume_min=0.01,
        volume_max=20.0,
        volume_step=0.01,
        stops_level_points=0,
        typical_spread_points=3000,
    ),
    "ETHUSD": SymbolSpec(
        symbol="ETHUSD",
        contract_size=1,
        tick_size=0.01,
        tick_value_usd_per_lot=1.0,
        volume_min=0.01,
        volume_max=200.0,
        volume_step=0.01,
        stops_level_points=0,
        typical_spread_points=250,
    ),
}


def get_spec(symbol: str) -> SymbolSpec:
    if symbol not in FIXTURES:
        raise KeyError(f"no MT5 spec fixture for '{symbol}'; {VERIFY_SYMBOL_NOTICE}")
    return FIXTURES[symbol]
