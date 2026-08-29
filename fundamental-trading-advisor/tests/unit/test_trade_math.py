from __future__ import annotations

from app.broker.mt5_specs import get_spec
from app.domain.enums import AssetClass, Direction
from app.risk.trade_math import build_trade_math


def test_no_trade_direction_is_infeasible():
    spec = get_spec("EURUSD")
    result = build_trade_math(
        direction=Direction.NO_TRADE,
        asset_class=AssetClass.FX,
        mid_price=1.10,
        spread=0.0001,
        spec=spec,
        account_equity=10_000,
        risk_percent=0.005,
        has_critical_catalyst_in_horizon=False,
    )
    assert result.feasible is False


def test_buy_plan_has_rr_at_or_above_minimum():
    spec = get_spec("EURUSD")
    result = build_trade_math(
        direction=Direction.BUY,
        asset_class=AssetClass.FX,
        mid_price=1.10,
        spread=0.0001,
        spec=spec,
        account_equity=10_000,
        risk_percent=0.005,
        has_critical_catalyst_in_horizon=False,
    )
    assert result.feasible is True
    assert result.risk_reward >= 1.5
    assert result.stop_loss < result.entry < result.take_profit


def test_sell_plan_orders_prices_correctly():
    spec = get_spec("EURUSD")
    result = build_trade_math(
        direction=Direction.SELL,
        asset_class=AssetClass.FX,
        mid_price=1.10,
        spread=0.0001,
        spec=spec,
        account_equity=10_000,
        risk_percent=0.005,
        has_critical_catalyst_in_horizon=False,
    )
    assert result.take_profit < result.entry < result.stop_loss


def test_wide_spread_relative_to_stop_is_infeasible():
    spec = get_spec("EURUSD")
    result = build_trade_math(
        direction=Direction.BUY,
        asset_class=AssetClass.FX,
        mid_price=1.10,
        spread=0.01,  # absurdly wide spread vs. a ~0.0066 stop distance
        spec=spec,
        account_equity=10_000,
        risk_percent=0.005,
        has_critical_catalyst_in_horizon=False,
    )
    assert result.feasible is False
    assert "spread" in result.reason


def test_position_sizing_respects_risk_percent():
    spec = get_spec("EURUSD")
    result = build_trade_math(
        direction=Direction.BUY,
        asset_class=AssetClass.FX,
        mid_price=1.10,
        spread=0.0001,
        spec=spec,
        account_equity=10_000,
        risk_percent=0.005,
        has_critical_catalyst_in_horizon=False,
    )
    assert result.risk_money == 50.0
    assert result.position_size_lots is not None
    assert spec.volume_min <= result.position_size_lots <= spec.volume_max


def test_no_account_equity_skips_position_sizing():
    spec = get_spec("EURUSD")
    result = build_trade_math(
        direction=Direction.BUY,
        asset_class=AssetClass.FX,
        mid_price=1.10,
        spread=0.0001,
        spec=spec,
        account_equity=None,
        risk_percent=0.005,
        has_critical_catalyst_in_horizon=False,
    )
    assert result.position_size_lots is None
    assert result.risk_money is None


def test_event_risk_widens_stop_distance():
    spec = get_spec("EURUSD")
    normal = build_trade_math(
        direction=Direction.BUY,
        asset_class=AssetClass.FX,
        mid_price=1.10,
        spread=0.0001,
        spec=spec,
        account_equity=10_000,
        risk_percent=0.005,
        has_critical_catalyst_in_horizon=False,
    )
    widened = build_trade_math(
        direction=Direction.BUY,
        asset_class=AssetClass.FX,
        mid_price=1.10,
        spread=0.0001,
        spec=spec,
        account_equity=10_000,
        risk_percent=0.005,
        has_critical_catalyst_in_horizon=True,
    )
    assert widened.distance_to_sl > normal.distance_to_sl
