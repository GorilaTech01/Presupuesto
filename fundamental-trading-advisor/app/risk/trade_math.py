"""Non-technical SL/TP construction and RR/position sizing math (sections
18-19). No indicator derived from price history (no ATR, no support/
resistance, no Fibonacci) feeds any number here. Distances come from:

  - a preconfigured percentage-of-price band per instrument class
    (STOP_PCT_BY_CLASS), widened when a CRITICAL catalyst falls inside the
    horizon (event risk), and
  - a target risk/reward multiple applied to that stop distance to derive
    the take-profit distance.

If the resulting plan fails a minimum RR or a broker feasibility check
(spread, stops level), the caller must treat that as NO_TRADE rather than
loosening the constraint.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.broker.mt5_specs import SymbolSpec
from app.domain.enums import AssetClass, Direction

MIN_RISK_REWARD = 1.5
DEFAULT_TARGET_RISK_REWARD = 2.0

STOP_PCT_BY_CLASS: dict[AssetClass, float] = {
    AssetClass.FX: 0.006,
    AssetClass.METAL: 0.012,
    AssetClass.INDEX: 0.015,
    AssetClass.CRYPTO: 0.045,
}

EVENT_RISK_WIDENING_MULTIPLIER = 1.3  # applied when a CRITICAL catalyst falls within the horizon


@dataclass
class TradeMathResult:
    feasible: bool
    reason: str | None
    entry: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    distance_to_sl: float | None = None
    distance_to_tp: float | None = None
    risk_reward: float | None = None
    position_size_lots: float | None = None
    risk_money: float | None = None


def build_trade_math(
    *,
    direction: Direction,
    asset_class: AssetClass,
    mid_price: float,
    spread: float,
    spec: SymbolSpec,
    account_equity: float | None,
    risk_percent: float,
    has_critical_catalyst_in_horizon: bool,
    target_risk_reward: float = DEFAULT_TARGET_RISK_REWARD,
) -> TradeMathResult:
    if direction is Direction.NO_TRADE:
        return TradeMathResult(feasible=False, reason="direction is NO_TRADE")

    stop_pct = STOP_PCT_BY_CLASS[asset_class]
    if has_critical_catalyst_in_horizon:
        stop_pct *= EVENT_RISK_WIDENING_MULTIPLIER
    stop_distance = mid_price * stop_pct

    min_stop_distance = spec.stops_level_points * spec.tick_size
    if stop_distance < min_stop_distance:
        stop_distance = min_stop_distance

    if spread > 0 and stop_distance < spread * 5:
        return TradeMathResult(
            feasible=False,
            reason=(
                f"spread ({spread:.5f}) is too wide relative to the computed stop distance "
                f"({stop_distance:.5f}); execution risk too high for a defensible RR"
            ),
        )

    take_profit_distance = stop_distance * target_risk_reward
    risk_reward = take_profit_distance / stop_distance if stop_distance else 0.0
    if risk_reward < MIN_RISK_REWARD:
        return TradeMathResult(
            feasible=False, reason=f"risk/reward {risk_reward:.2f} below minimum {MIN_RISK_REWARD}"
        )

    if direction is Direction.BUY:
        entry = mid_price + spread / 2  # approximate ask
        stop_loss = entry - stop_distance
        take_profit = entry + take_profit_distance
    else:
        entry = mid_price - spread / 2  # approximate bid
        stop_loss = entry + stop_distance
        take_profit = entry - take_profit_distance

    position_size_lots = None
    risk_money = None
    if account_equity is not None:
        risk_money = account_equity * risk_percent
        stop_distance_ticks = stop_distance / spec.tick_size
        risk_per_lot = stop_distance_ticks * spec.tick_value_usd_per_lot
        if risk_per_lot > 0:
            raw_lots = risk_money / risk_per_lot
            position_size_lots = _round_to_step(
                raw_lots, spec.volume_step, spec.volume_min, spec.volume_max
            )

    return TradeMathResult(
        feasible=True,
        reason=None,
        entry=round(entry, 6),
        stop_loss=round(stop_loss, 6),
        take_profit=round(take_profit, 6),
        distance_to_sl=round(stop_distance, 6),
        distance_to_tp=round(take_profit_distance, 6),
        risk_reward=round(risk_reward, 3),
        position_size_lots=position_size_lots,
        risk_money=round(risk_money, 2) if risk_money is not None else None,
    )


def _round_to_step(raw: float, step: float, minimum: float, maximum: float) -> float:
    stepped = round(raw / step) * step
    stepped = max(minimum, min(maximum, stepped))
    return round(stepped, 2)
