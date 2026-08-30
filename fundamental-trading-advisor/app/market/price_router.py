"""Provider-priority routing + freshness enforcement for current-price
quotes (V1.1.1, `PRICE_PROVIDER` setting).

`AutoPriceProvider` never fabricates a price and never silently returns a
stale one: it tries each configured source in priority order, and only
returns a quote whose age is within `MAX_QUOTE_AGE_SECONDS`. If every
candidate is unreachable, it raises `DataSourceUnavailable`
(`PRICE_UNAVAILABLE`); if at least one candidate answered but every answer
was too old, it raises `StaleDataError` (`PRICE_STALE`) instead, so callers
can tell the two failure modes apart.
"""

from __future__ import annotations

from datetime import timedelta

from app.common.errors import DataSourceUnavailable, StaleDataError
from app.common.time_utils import is_stale
from app.config.settings import Settings
from app.domain.enums import Freshness
from app.market.mt5_provider import MT5ReadOnlyPriceProvider
from app.market.price_provider import CurrentMarketQuote, ManualPriceFileProvider, PriceProvider

_VALID_MODES = {"auto", "mt5", "manual"}


class AutoPriceProvider:
    """Tries `mt5` then `manual` (mode `auto`), or exactly one of them
    (mode `mt5`/`manual`), per `settings.price_provider`. Never invents a
    quote when nothing usable is available.
    """

    def __init__(
        self,
        *,
        mode: str,
        max_quote_age_seconds: int,
        mt5_provider: PriceProvider | None,
        manual_provider: PriceProvider,
    ) -> None:
        if mode not in _VALID_MODES:
            raise ValueError(
                f"unknown price provider mode '{mode}', expected one of {_VALID_MODES}"
            )
        self.mode = mode
        self.max_quote_age_seconds = max_quote_age_seconds
        self.mt5_provider = mt5_provider
        self.manual_provider = manual_provider

    def _candidates(self) -> list[PriceProvider]:
        if self.mode == "mt5":
            return [self.mt5_provider] if self.mt5_provider is not None else []
        if self.mode == "manual":
            return [self.manual_provider]
        # auto: prefer a live read-only terminal, fall back to the manual file
        candidates: list[PriceProvider] = []
        if self.mt5_provider is not None:
            candidates.append(self.mt5_provider)
        candidates.append(self.manual_provider)
        return candidates

    def get_quote(self, symbol: str) -> CurrentMarketQuote:
        stale_quote: CurrentMarketQuote | None = None
        last_error: str | None = None
        for provider in self._candidates():
            try:
                quote = provider.get_quote(symbol)
            except DataSourceUnavailable as exc:
                last_error = str(exc)
                continue
            if is_stale(quote.timestamp, timedelta(seconds=self.max_quote_age_seconds)):
                stale_quote = quote.model_copy(update={"freshness": Freshness.STALE})
                continue
            return quote.model_copy(update={"freshness": Freshness.FRESH})

        if stale_quote is not None:
            raise StaleDataError(
                symbol,
                f"latest available quote for '{symbol}' is older than "
                f"{self.max_quote_age_seconds}s (source={stale_quote.source})",
            )
        suffix = f"; last error: {last_error}" if last_error else ""
        raise DataSourceUnavailable(
            "price_provider",
            f"PRICE_UNAVAILABLE: no configured price source (mode={self.mode}) "
            f"returned a quote for '{symbol}'{suffix}",
        )


def build_price_provider(settings: Settings) -> AutoPriceProvider:
    """The one place `PRICE_PROVIDER`/`MAX_QUOTE_AGE_SECONDS` are wired into
    an actual provider -- `weekly` and `monitor` both call this instead of
    constructing `ManualPriceFileProvider`/`MT5ReadOnlyPriceProvider`
    directly, so both always agree on provider priority and freshness.

    `MT5_ENABLED` (default `false`) gates the MT5 candidate entirely, same
    as `app.broker.pepperstone.PepperstoneGateway.get_symbol_info` already
    did before this provider existed: with the default settings, nothing
    new happens automatically -- `PRICE_PROVIDER=auto` behaves exactly like
    `manual` until the user explicitly opts in with `MT5_ENABLED=true`.
    """
    mt5_provider = MT5ReadOnlyPriceProvider() if settings.mt5_enabled else None
    return AutoPriceProvider(
        mode=settings.price_provider,
        max_quote_age_seconds=settings.max_quote_age_seconds,
        mt5_provider=mt5_provider,
        manual_provider=ManualPriceFileProvider(settings.data_dir / "manual_prices.json"),
    )
