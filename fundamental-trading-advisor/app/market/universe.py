"""Static definition of the tradable asset universe (section 5 of the spec).

This is metadata only (what the asset is, which currencies/country
fundamentals apply to it) -- never price history, never technical levels.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.domain.enums import AssetClass


class AssetDefinition(BaseModel):
    asset: str
    asset_class: AssetClass
    base_ccy: str | None = None  # for FX: the base currency (EUR in EURUSD)
    quote_ccy: str | None = None  # for FX: the quote currency (USD in EURUSD)
    relevant_countries: list[str]
    broker_symbol_candidates: list[str]


UNIVERSE: dict[str, AssetDefinition] = {
    "EURUSD": AssetDefinition(
        asset="EURUSD",
        asset_class=AssetClass.FX,
        base_ccy="EUR",
        quote_ccy="USD",
        relevant_countries=["EZ", "US"],
        broker_symbol_candidates=["EURUSD"],
    ),
    "GBPUSD": AssetDefinition(
        asset="GBPUSD",
        asset_class=AssetClass.FX,
        base_ccy="GBP",
        quote_ccy="USD",
        relevant_countries=["UK", "US"],
        broker_symbol_candidates=["GBPUSD"],
    ),
    "USDJPY": AssetDefinition(
        asset="USDJPY",
        asset_class=AssetClass.FX,
        base_ccy="USD",
        quote_ccy="JPY",
        relevant_countries=["US", "JP"],
        broker_symbol_candidates=["USDJPY"],
    ),
    "AUDUSD": AssetDefinition(
        asset="AUDUSD",
        asset_class=AssetClass.FX,
        base_ccy="AUD",
        quote_ccy="USD",
        relevant_countries=["AU", "US"],
        broker_symbol_candidates=["AUDUSD"],
    ),
    "USDCHF": AssetDefinition(
        asset="USDCHF",
        asset_class=AssetClass.FX,
        base_ccy="USD",
        quote_ccy="CHF",
        relevant_countries=["US", "CH"],
        broker_symbol_candidates=["USDCHF"],
    ),
    "USDCAD": AssetDefinition(
        asset="USDCAD",
        asset_class=AssetClass.FX,
        base_ccy="USD",
        quote_ccy="CAD",
        relevant_countries=["US", "CA"],
        broker_symbol_candidates=["USDCAD"],
    ),
    "XAUUSD": AssetDefinition(
        asset="XAUUSD",
        asset_class=AssetClass.METAL,
        base_ccy=None,
        quote_ccy="USD",
        relevant_countries=["US"],
        broker_symbol_candidates=["XAUUSD", "GOLD"],
    ),
    "BTCUSD": AssetDefinition(
        asset="BTCUSD",
        asset_class=AssetClass.CRYPTO,
        base_ccy=None,
        quote_ccy="USD",
        relevant_countries=["US"],
        broker_symbol_candidates=["BTCUSD", "BTCUSDm"],
    ),
    "ETHUSD": AssetDefinition(
        asset="ETHUSD",
        asset_class=AssetClass.CRYPTO,
        base_ccy=None,
        quote_ccy="USD",
        relevant_countries=["US"],
        broker_symbol_candidates=["ETHUSD", "ETHUSDm"],
    ),
}


def get_asset(asset: str) -> AssetDefinition:
    if asset not in UNIVERSE:
        raise KeyError(f"'{asset}' is not in the configured tradable universe")
    return UNIVERSE[asset]
