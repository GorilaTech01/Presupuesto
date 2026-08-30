"""Minimal on-disk JSON cache with per-entry TTL.

Macro data updates monthly at most, so we cache aggressively to avoid
hammering free/official APIs. Every cache entry records its own retrieval
timestamp so freshness can always be audited later.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from app.common.time_utils import age, utcnow


@dataclass
class CacheEntry:
    retrieved_at: str
    payload: Any


class DiskCache:
    """A tiny namespaced JSON file cache. Not process-safe by design (single CLI run)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, namespace: str, key: str) -> Path:
        safe_key = key.replace("/", "_").replace(":", "_")
        ns_dir = self.root / namespace
        ns_dir.mkdir(parents=True, exist_ok=True)
        return ns_dir / f"{safe_key}.json"

    def get(self, namespace: str, key: str, ttl: timedelta) -> Any | None:
        path = self._path(namespace, key)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None
        from datetime import datetime

        retrieved_at = datetime.fromisoformat(raw["retrieved_at"])
        if age(retrieved_at) > ttl:
            return None
        return raw["payload"]

    def set(self, namespace: str, key: str, payload: Any) -> None:
        path = self._path(namespace, key)
        entry = {"retrieved_at": utcnow().isoformat(), "payload": payload}
        path.write_text(json.dumps(entry, default=str))

    def retrieved_at(self, namespace: str, key: str) -> str | None:
        path = self._path(namespace, key)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None
        return str(raw.get("retrieved_at"))

    def clear_all(self) -> None:
        """Wipes every cached entry across every namespace.

        Used by `--full-refresh` (monitor CLI, spec section 10) to force a
        real re-fetch instead of relying on each source's normal TTL.
        Incremental re-evaluation should never call this -- it relies on
        each indicator's own TTL to naturally pick up newly-published data
        around its release cadence without hammering official APIs.
        """
        import shutil

        if self.root.exists():
            shutil.rmtree(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
