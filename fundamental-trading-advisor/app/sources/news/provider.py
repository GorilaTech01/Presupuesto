"""Optional news/event research layer (section 8 of the spec).

This is deliberately isolated behind a small Protocol so the rest of the
pipeline never depends on it being available. It must NEVER be used to
substitute for an official data point -- only to add qualitative context
(e.g. "ECB board member X said Y on date Z") that a human analyst would
also want to see alongside the structured facts.

The default implementation is a no-op (disabled) so the system runs fully
without any news integration. A real implementation should only pull from
institutional sources (Reuters, Bloomberg, FT, official central bank
press pages) -- never social media, forums, or influencer content (see
project rule #7).
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel

from app.domain.enums import DataSourceTier


class NewsItem(BaseModel):
    headline: str
    summary: str
    source: str
    source_url: str
    published_at: datetime
    tier: DataSourceTier = DataSourceTier.NEWS_RESEARCH


class NewsResearchProvider(Protocol):
    def search(self, query: str, *, max_results: int = 5) -> list[NewsItem]: ...

    @property
    def enabled(self) -> bool: ...


class NullNewsResearchProvider:
    """Default, always-disabled provider. Returns no results, never fails."""

    @property
    def enabled(self) -> bool:
        return False

    def search(self, query: str, *, max_results: int = 5) -> list[NewsItem]:
        return []
