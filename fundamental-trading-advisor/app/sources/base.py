"""Shared HTTP + caching plumbing for official data source adapters.

Every concrete adapter (FRED, ECB, Eurostat, BLS, EIA, CFTC, ...) builds on
top of this. The contract is deliberately narrow: fetch bytes/json for a URL,
cache them with a source-appropriate TTL, and raise DataSourceUnavailable on
any failure. Adapters must never fabricate a value when this raises.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import httpx

from app.common.cache import DiskCache
from app.common.errors import DataSourceUnavailable
from app.common.logging import get_logger, log_event

logger = get_logger("sources.base")

DEFAULT_TIMEOUT = httpx.Timeout(15.0, connect=10.0)


@dataclass
class SourceClientConfig:
    name: str
    default_ttl: timedelta = timedelta(hours=12)


class OfficialSourceClient:
    """Base class for a single official/free data source."""

    def __init__(
        self, config: SourceClientConfig, cache: DiskCache, client: httpx.Client | None = None
    ) -> None:
        self.config = config
        self.cache = cache
        self._client = client or httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=True)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> OfficialSourceClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def get_json(
        self,
        url: str,
        *,
        cache_key: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        ttl: timedelta | None = None,
    ) -> Any:
        ttl = ttl or self.config.default_ttl
        cached = self.cache.get(self.config.name, cache_key, ttl)
        if cached is not None:
            log_event(logger, "cache_hit", source=self.config.name, key=cache_key)
            return cached
        try:
            response = self._client.get(url, params=params, headers=headers)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            log_event(
                logger, "fetch_failed", source=self.config.name, key=cache_key, error=str(exc)
            )
            raise DataSourceUnavailable(
                self.config.name, f"HTTP error fetching {cache_key}: {exc}"
            ) from exc
        except ValueError as exc:
            raise DataSourceUnavailable(
                self.config.name, f"non-JSON response for {cache_key}: {exc}"
            ) from exc
        self.cache.set(self.config.name, cache_key, payload)
        log_event(logger, "fetch_ok", source=self.config.name, key=cache_key)
        return payload
