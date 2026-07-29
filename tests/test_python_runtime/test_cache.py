"""Tests for python_runtime.cache — make_cache_key, ComputeCache LRU."""

import time

from python_runtime.cache import ComputeCache, make_cache_key


class TestMakeCacheKey:
    """Deterministic cache key generation."""

    def test_deterministic(self) -> None:
        k1 = make_cache_key("abc123", "1.0", {"query": "SELECT 1"})
        k2 = make_cache_key("abc123", "1.0", {"query": "SELECT 1"})
        assert k1 == k2
        assert isinstance(k1, str)
        assert k1.startswith("abc123:")  # dataset_hash prefix
        assert len(k1) == 71  # dataset_hash (6) + ':' (1) + SHA-256 hex digest (64)

    def test_different_hash_different_key(self) -> None:
        k1 = make_cache_key("abc", "1.0", {})
        k2 = make_cache_key("xyz", "1.0", {})
        assert k1 != k2

    def test_different_params_different_key(self) -> None:
        k1 = make_cache_key("abc", "1.0", {"a": 1})
        k2 = make_cache_key("abc", "1.0", {"a": 2})
        assert k1 != k2

    def test_different_version_different_key(self) -> None:
        k1 = make_cache_key("abc", "1.0", {})
        k2 = make_cache_key("abc", "2.0", {})
        assert k1 != k2

    def test_params_sorted_deterministically(self) -> None:
        k1 = make_cache_key("abc", "1.0", {"b": 2, "a": 1})
        k2 = make_cache_key("abc", "1.0", {"a": 1, "b": 2})
        assert k1 == k2


class TestComputeCache:
    """In-memory LRU cache with TTL."""

    def test_get_miss(self) -> None:
        cache = ComputeCache()
        assert cache.get("nonexistent") is None

    def test_set_and_get(self) -> None:
        cache = ComputeCache()
        cache.set("key1", b"value1")
        result = cache.get("key1")
        assert result == b"value1"

    def test_get_returns_none_after_expiry(self) -> None:
        cache = ComputeCache(default_ttl_seconds=0)  # zero TTL = expired immediately
        cache.set("key1", b"value1")
        time.sleep(0.001)
        assert cache.get("key1") is None

    def test_custom_ttl(self) -> None:
        cache = ComputeCache(default_ttl_seconds=3600)
        cache.set("key1", b"value1", ttl_seconds=0)  # immediate expiry
        time.sleep(0.001)
        assert cache.get("key1") is None

    def test_lru_eviction(self) -> None:
        cache = ComputeCache(max_entries=3)
        cache.set("a", b"1")
        cache.set("b", b"2")
        cache.set("c", b"3")
        cache.set("d", b"4")  # should evict "a" (oldest)
        assert cache.get("a") is None
        assert cache.get("b") == b"2"
        assert cache.get("c") == b"3"
        assert cache.get("d") == b"4"
        assert cache.size == 3

    def test_lru_bump_on_access(self) -> None:
        """Accessing an item moves it to MRU position."""
        cache = ComputeCache(max_entries=2)
        cache.set("a", b"1")
        cache.set("b", b"2")
        # Access "a" (bump to MRU)
        assert cache.get("a") == b"1"
        # Now "b" is LRU, so adding "c" evicts "b"
        cache.set("c", b"3")
        assert cache.get("b") is None
        assert cache.get("a") == b"1"
        assert cache.get("c") == b"3"

    def test_clear(self) -> None:
        cache = ComputeCache()
        cache.set("a", b"1")
        cache.set("b", b"2")
        cache.clear()
        assert cache.size == 0
        assert cache.get("a") is None

    def test_invalidate_by_hash(self) -> None:
        cache = ComputeCache()
        k1 = make_cache_key("dataset_a", "1.0", {})
        k2 = make_cache_key("dataset_a", "1.0", {"x": 1})
        k3 = make_cache_key("dataset_b", "1.0", {})
        cache.set(k1, b"result1")
        cache.set(k2, b"result2")
        cache.set(k3, b"result3")
        invalidated = cache.invalidate("dataset_a")
        assert invalidated == 2
        assert cache.get(k1) is None
        assert cache.get(k2) is None
        assert cache.get(k3) == b"result3"

    def test_invalidate_returns_zero_for_no_match(self) -> None:
        cache = ComputeCache()
        cache.set(make_cache_key("abc", "1.0", {}), b"data")
        assert cache.invalidate("nonexistent") == 0

    def test_size_property(self) -> None:
        cache = ComputeCache()
        assert cache.size == 0
        cache.set("a", b"1")
        assert cache.size == 1

    def test_binary_data(self) -> None:
        cache = ComputeCache()
        binary = b"\x00\x01\x02\xff\xfe"
        cache.set("bin", binary)
        assert cache.get("bin") == binary

    def test_overwrite_existing_key(self) -> None:
        cache = ComputeCache()
        cache.set("key", b"old")
        cache.set("key", b"new")
        assert cache.get("key") == b"new"
