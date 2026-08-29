from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.broker.mt5_specs import VERIFY_SYMBOL_NOTICE, get_spec
from app.broker.pepperstone import AutoExecutionDisabled, PepperstoneGateway
from app.broker.symbol_resolver import BrokerSymbolResolver
from app.common.errors import SymbolNotVerifiable
from app.config.settings import Settings


def test_resolver_returns_verify_notice():
    resolved = BrokerSymbolResolver().resolve("EURUSD")
    assert resolved.notice == VERIFY_SYMBOL_NOTICE
    assert resolved.broker_symbol == "EURUSD"


def test_resolver_raises_for_unverifiable_symbol(monkeypatch):
    from app.market import universe

    fake = universe.AssetDefinition(
        asset="FAKEUSD",
        asset_class=universe.AssetClass.FX,
        base_ccy="FAKE",
        quote_ccy="USD",
        relevant_countries=["ZZ"],
        broker_symbol_candidates=["FAKEUSD"],
    )
    monkeypatch.setitem(universe.UNIVERSE, "FAKEUSD", fake)
    with pytest.raises(SymbolNotVerifiable):
        BrokerSymbolResolver().resolve("FAKEUSD")


def test_get_spec_unknown_symbol_raises():
    with pytest.raises(KeyError):
        get_spec("NOTASYMBOL")


def test_pepperstone_gateway_never_sends_orders():
    settings = Settings(_env_file=None, fred_api_key=None)
    gateway = PepperstoneGateway(settings)
    with pytest.raises(AutoExecutionDisabled):
        gateway.send_order()


def test_pepperstone_gateway_symbol_info_not_implemented_without_mt5():
    settings = Settings(_env_file=None, mt5_enabled=False)
    gateway = PepperstoneGateway(settings)
    with pytest.raises(NotImplementedError):
        gateway.get_symbol_info("EURUSD")


def test_settings_reject_auto_execution_true():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, auto_execution=True)


def test_settings_reject_risk_percent_above_ceiling():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, risk_percent=0.05)
