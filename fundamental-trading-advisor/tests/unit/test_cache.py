from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from app.common.cache import DiskCache


def test_cache_miss_returns_none(tmp_path: Path):
    cache = DiskCache(tmp_path)
    assert cache.get("ns", "key", timedelta(hours=1)) is None


def test_cache_set_then_get_hits(tmp_path: Path):
    cache = DiskCache(tmp_path)
    cache.set("ns", "key", {"a": 1})
    assert cache.get("ns", "key", timedelta(hours=1)) == {"a": 1}


def test_cache_expires_after_ttl(tmp_path: Path, monkeypatch):
    cache = DiskCache(tmp_path)
    cache.set("ns", "key", {"a": 1})
    assert cache.get("ns", "key", timedelta(seconds=-1)) is None


def test_cache_namespaces_do_not_collide(tmp_path: Path):
    cache = DiskCache(tmp_path)
    cache.set("ns1", "key", "one")
    cache.set("ns2", "key", "two")
    assert cache.get("ns1", "key", timedelta(hours=1)) == "one"
    assert cache.get("ns2", "key", timedelta(hours=1)) == "two"
