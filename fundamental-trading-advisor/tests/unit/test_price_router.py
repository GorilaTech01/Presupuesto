"""AutoPriceProvider provider-priority + freshness routing (V1.1.1)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.common.errors import DataSourceUnavailable, StaleDataError
from app.config.settings import Settings
from app.domain.enums import Freshness
from app.market.mt5_provider import MT5ReadOnlyPriceProvider
from app.market.price_provider import CurrentMarketQuote
from app.market.price_router import AutoPriceProvider, build_price_provider


def _quote(*, source: str, age_seconds: float = 0.0) -> CurrentMarketQuote:
    return CurrentMarketQuote(
        symbol="EURUSD",
        broker_symbol="EURUSD",
        bid=1.1000,
        ask=1.1002,
        timestamp=datetime.now(UTC) - timedelta(seconds=age_seconds),
        source=source,
    )


class _FixedProvider:
    def __init__(self, quote: CurrentMarketQuote | None = None, error: str | None = None) -> None:
        self._quote = quote
        self._error = error

    def get_quote(self, symbol: str) -> CurrentMarketQuote:
        if self._error is not None:
            raise DataSourceUnavailable("fixed", self._error)
        assert self._quote is not None
        return self._quote


def test_auto_mode_prefers_mt5_when_both_available():
    router = AutoPriceProvider(
        mode="auto",
        max_quote_age_seconds=60,
        mt5_provider=_FixedProvider(_quote(source="MT5_READ_ONLY")),
        manual_provider=_FixedProvider(_quote(source="MANUAL_FILE")),
    )
    quote = router.get_quote("EURUSD")
    assert quote.source == "MT5_READ_ONLY"
    assert quote.freshness is Freshness.FRESH


def test_auto_mode_falls_back_to_manual_when_mt5_unavailable():
    router = AutoPriceProvider(
        mode="auto",
        max_quote_age_seconds=60,
        mt5_provider=_FixedProvider(error="not installed"),
        manual_provider=_FixedProvider(_quote(source="MANUAL_FILE")),
    )
    quote = router.get_quote("EURUSD")
    assert quote.source == "MANUAL_FILE"


def test_auto_mode_raises_price_unavailable_when_nothing_works():
    router = AutoPriceProvider(
        mode="auto",
        max_quote_age_seconds=60,
        mt5_provider=_FixedProvider(error="not installed"),
        manual_provider=_FixedProvider(error="no file"),
    )
    with pytest.raises(DataSourceUnavailable, match="PRICE_UNAVAILABLE"):
        router.get_quote("EURUSD")


def test_explicit_mt5_mode_never_tries_manual():
    manual = _FixedProvider(_quote(source="MANUAL_FILE"))
    router = AutoPriceProvider(
        mode="mt5",
        max_quote_age_seconds=60,
        mt5_provider=_FixedProvider(error="not installed"),
        manual_provider=manual,
    )
    with pytest.raises(DataSourceUnavailable):
        router.get_quote("EURUSD")


def test_explicit_manual_mode_never_tries_mt5():
    mt5_provider = _FixedProvider(_quote(source="MT5_READ_ONLY"))
    router = AutoPriceProvider(
        mode="manual",
        max_quote_age_seconds=60,
        mt5_provider=mt5_provider,
        manual_provider=_FixedProvider(_quote(source="MANUAL_FILE")),
    )
    quote = router.get_quote("EURUSD")
    assert quote.source == "MANUAL_FILE"


def test_mt5_mode_with_no_mt5_provider_configured_raises():
    router = AutoPriceProvider(
        mode="mt5",
        max_quote_age_seconds=60,
        mt5_provider=None,
        manual_provider=_FixedProvider(_quote(source="MANUAL_FILE")),
    )
    with pytest.raises(DataSourceUnavailable):
        router.get_quote("EURUSD")


def test_stale_quote_raises_stale_data_error_not_a_silent_fallback():
    router = AutoPriceProvider(
        mode="manual",
        max_quote_age_seconds=60,
        mt5_provider=None,
        manual_provider=_FixedProvider(_quote(source="MANUAL_FILE", age_seconds=120)),
    )
    with pytest.raises(StaleDataError):
        router.get_quote("EURUSD")


def test_auto_mode_prefers_fresh_manual_over_stale_mt5():
    router = AutoPriceProvider(
        mode="auto",
        max_quote_age_seconds=60,
        mt5_provider=_FixedProvider(_quote(source="MT5_READ_ONLY", age_seconds=999)),
        manual_provider=_FixedProvider(_quote(source="MANUAL_FILE", age_seconds=0)),
    )
    quote = router.get_quote("EURUSD")
    assert quote.source == "MANUAL_FILE"
    assert quote.freshness is Freshness.FRESH


def test_auto_mode_raises_stale_when_only_stale_quotes_exist():
    router = AutoPriceProvider(
        mode="auto",
        max_quote_age_seconds=60,
        mt5_provider=_FixedProvider(_quote(source="MT5_READ_ONLY", age_seconds=999)),
        manual_provider=_FixedProvider(_quote(source="MANUAL_FILE", age_seconds=999)),
    )
    with pytest.raises(StaleDataError):
        router.get_quote("EURUSD")


def test_quote_exactly_at_the_freshness_boundary_is_fresh():
    router = AutoPriceProvider(
        mode="manual",
        max_quote_age_seconds=60,
        mt5_provider=None,
        manual_provider=_FixedProvider(_quote(source="MANUAL_FILE", age_seconds=59)),
    )
    quote = router.get_quote("EURUSD")
    assert quote.freshness is Freshness.FRESH


def test_unknown_mode_rejected_at_construction():
    with pytest.raises(ValueError):
        AutoPriceProvider(
            mode="bogus",
            max_quote_age_seconds=60,
            mt5_provider=None,
            manual_provider=_FixedProvider(_quote(source="MANUAL_FILE")),
        )


def test_build_price_provider_never_attaches_mt5_by_default(tmp_path):
    """MT5_ENABLED defaults to false -- the safe-by-default posture means
    PRICE_PROVIDER=auto must not attempt a live terminal until the user
    explicitly opts in, same as PepperstoneGateway.get_symbol_info always
    required MT5_ENABLED before this provider existed."""
    settings = Settings(_env_file=None, data_dir=tmp_path, mt5_enabled=False)
    provider = build_price_provider(settings)
    assert provider.mt5_provider is None


def test_build_price_provider_attaches_mt5_when_explicitly_enabled(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path, mt5_enabled=True)
    provider = build_price_provider(settings)
    assert isinstance(provider.mt5_provider, MT5ReadOnlyPriceProvider)
