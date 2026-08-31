"""Pepperstone/MT5 execution boundary -- READ/ANALYZE/RECOMMEND/LOG only.

Section 21 of the spec requires an explicit architectural block on
auto-execution, not just a config flag. `send_order` therefore always
raises, regardless of settings, and there is no code path anywhere else in
this project that calls a broker "place order" API. The user executes
manually in MT5 after reviewing the recommendation.
"""

from __future__ import annotations

from app.config.settings import Settings


class AutoExecutionDisabled(RuntimeError):
    pass


class PepperstoneGateway:
    """Intentionally execution-incapable in this version.

    `get_symbol_info` is a placeholder seam for a *future* read-only MT5
    terminal connection (bid/ask/spread/contract specs) gated behind
    `MT5_ENABLED`. It must stay read-only: no order-placement method may be
    added to this class without changing this file's module docstring and
    the project's safety review.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send_order(self, *args: object, **kwargs: object) -> None:
        raise AutoExecutionDisabled(
            "This version of the Fundamental Trading Advisor does not send orders. "
            "AUTO_EXECUTION is hardcoded off. Execute manually in MetaTrader 5 after "
            "reviewing the recommendation."
        )

    def get_symbol_info(self, symbol: str) -> None:
        if not self.settings.mt5_enabled:
            raise NotImplementedError(
                f"MT5_ENABLED=false: no live connection configured. Verify '{symbol}' "
                "manually in MT5 > Market Watch > Show All before trading."
            )
        raise NotImplementedError(
            "Live MT5 read integration is not implemented in this version. "
            "This is a placeholder seam for a future read-only connection "
            "(bid/ask/spread/contract_size/tick_size/tick_value/volume_min/"
            "volume_max/volume_step/stops_level)."
        )
