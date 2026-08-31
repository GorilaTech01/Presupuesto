"""Timezone-aware time helpers.

All internal timestamps are stored as timezone-aware UTC datetimes. Local
display uses the configured IANA timezone (default America/Costa_Rica).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo


def utcnow() -> datetime:
    return datetime.now(UTC)


def to_local(dt: datetime, tz_name: str) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(ZoneInfo(tz_name))


def format_utc(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_local(dt: datetime, tz_name: str) -> str:
    local = to_local(dt, tz_name)
    return local.strftime("%Y-%m-%d %H:%M %Z")


def age(dt: datetime, now: datetime | None = None) -> timedelta:
    now = now or utcnow()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return now - dt


def is_stale(dt: datetime, max_age: timedelta, now: datetime | None = None) -> bool:
    return age(dt, now) > max_age
