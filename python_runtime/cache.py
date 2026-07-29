"""Content-addressable in-memory cache with LRU eviction.

Provides ComputeCache (in-memory LRU cache) and make_cache_key() for
deterministic cache key generation from dataset hash, pipeline version,
and parameters.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from typing import Any

_CACHE_KEY_PREFIX_SEP = ":"  # separator between dataset_hash and SHA-256


def make_cache_key(
    dataset_hash: str,
    pipeline_version: str,
    params: dict[str, Any],
) -> str:
    """Deterministic cache key from dataset hash + pipeline version + params.

    The returned key is ``{dataset_hash}:{sha256_hex}`` so that
    :meth:`ComputeCache.invalidate` can efficiently match by dataset hash.

    Args:
        dataset_hash: Content hash of the input dataset.
        pipeline_version: Version string of the pipeline logic.
        params: Runtime parameters that affect the result.

    Returns:
        Cache key string (dataset_hash + separator + SHA-256 hex digest).
    """
    raw = json.dumps(
        {
            "dataset_hash": dataset_hash,
            "pipeline_version": pipeline_version,
            "params": dict(sorted(params.items())),
        },
        sort_keys=True,
        default=str,
    )
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return f"{dataset_hash}{_CACHE_KEY_PREFIX_SEP}{digest}"


class ComputeCache:
    """In-memory LRU cache for compute results. Thread-safe via OrderedDict.

    Phase 1 uses single-threaded access. Phase 2 (Redis) will provide
    distributed caching with proper thread safety.

    Attributes:
        _max: Maximum number of entries before LRU eviction.
        _default_ttl: Default time-to-live in seconds for cached entries.
        _data: OrderedDict mapping key -> (value_bytes, expiry_timestamp).
    """

    def __init__(self, max_entries: int = 1000, default_ttl_seconds: int = 3600):
        """Initialize the cache.

        Args:
            max_entries: Maximum entries before LRU eviction.
            default_ttl_seconds: Default TTL in seconds.
        """
        self._max = max_entries
        self._default_ttl = default_ttl_seconds
        self._data: OrderedDict[str, tuple[bytes, float]] = OrderedDict()

    def get(self, key: str) -> bytes | None:
        """Retrieve a value by key.

        Returns None if the key is missing or expired. On access, the key
        is moved to the most-recently-used position (LRU bump).

        Args:
            key: Cache key (SHA-256 hex digest).

        Returns:
            Cached bytes or None.
        """
        if key not in self._data:
            return None
        value, expiry = self._data[key]
        if expiry < time.monotonic():
            del self._data[key]
            return None
        self._data.move_to_end(key)
        return value

    def set(
        self, key: str, value: bytes, ttl_seconds: int | None = None
    ) -> None:
        """Store a value with optional TTL override.

        If the cache is at capacity, the least-recently-used item is evicted.

        Args:
            key: Cache key (SHA-256 hex digest).
            value: Bytes to cache.
            ttl_seconds: Custom TTL; falls back to default_ttl_seconds.
        """
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        expiry = time.monotonic() + ttl
        self._data[key] = (value, expiry)
        self._data.move_to_end(key)
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    def invalidate(self, dataset_hash: str) -> int:
        """Invalidate all entries whose key starts with the given dataset_hash.

        Because :func:`make_cache_key` prefixes every key with
        ``{dataset_hash}:``, this method can efficiently match by prefix.

        Args:
            dataset_hash: Hash string to match against cache key prefixes.

        Returns:
            Number of entries invalidated.
        """
        prefix = f"{dataset_hash}{_CACHE_KEY_PREFIX_SEP}"
        keys_to_delete = [k for k in self._data if k.startswith(prefix)]
        for k in keys_to_delete:
            del self._data[k]
        return len(keys_to_delete)

    def clear(self) -> None:
        """Remove all entries from the cache."""
        self._data.clear()

    @property
    def size(self) -> int:
        """Return the number of entries currently in the cache."""
        return len(self._data)
