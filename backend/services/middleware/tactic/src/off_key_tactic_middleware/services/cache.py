"""
TO BE REPLACED WITH MEMCACHED!!!
Simple in-memory caching service for TACTIC middleware.

This provides a basic caching layer to reduce database load for frequently
accessed data like charger lists and user information.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Optional, Dict
from dataclasses import dataclass, field

from off_key_core.config.logs import logger


@dataclass
class CacheEntry:
    """Individual cache entry with data and expiration."""

    data: Any
    expires_at: datetime
    access_count: int = 0
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def is_expired(self) -> bool:
        """Check if the cache entry has expired."""
        return datetime.now() > self.expires_at

    def touch(self):
        """Update access count when entry is retrieved."""
        self.access_count += 1


class SimpleCache:
    """
    Simple in-memory cache with TTL support.

    This is a basic implementation suitable for demonstration.
    For production, consider using Redis or Memcached.
    """

    def __init__(self, default_ttl_seconds: int = 300):  # 5 minutes default
        self.default_ttl = default_ttl_seconds
        self._store: Dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()
        self._stats = {
            "hits": 0,
            "misses": 0,
            "sets": 0,
            "deletes": 0,
            "evictions": 0,
        }

        # Start cleanup task
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())

    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache, returning None if expired or not found."""
        async with self._lock:
            entry = self._store.get(key)

            if entry is None:
                self._stats["misses"] += 1
                logger.debug(f"Cache miss: {key}")
                return None

            if entry.is_expired:
                # Remove expired entry
                del self._store[key]
                self._stats["misses"] += 1
                self._stats["evictions"] += 1
                logger.debug(f"Cache miss (expired): {key}")
                return None

            # Cache hit
            entry.touch()
            self._stats["hits"] += 1
            logger.debug(f"Cache hit: {key}")
            return entry.data

    async def set(
        self, key: str, value: Any, ttl_seconds: Optional[int] = None
    ) -> None:
        """Set value in cache with optional TTL override."""
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        expires_at = datetime.now() + timedelta(seconds=ttl)

        async with self._lock:
            self._store[key] = CacheEntry(data=value, expires_at=expires_at)
            self._stats["sets"] += 1
            logger.debug(f"Cache set: {key} (TTL: {ttl}s)")

    async def delete(self, key: str) -> bool:
        """Delete key from cache, returning True if it existed."""
        async with self._lock:
            if key in self._store:
                del self._store[key]
                self._stats["deletes"] += 1
                logger.debug(f"Cache delete: {key}")
                return True
            return False

    async def clear(self) -> None:
        """Clear all cache entries."""
        async with self._lock:
            count = len(self._store)
            self._store.clear()
            logger.info(f"Cache cleared: {count} entries removed")

    async def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        async with self._lock:
            total_requests = self._stats["hits"] + self._stats["misses"]
            hit_rate = (
                self._stats["hits"] / total_requests if total_requests > 0 else 0.0
            )

            return {
                **self._stats,
                "total_entries": len(self._store),
                "total_requests": total_requests,
                "hit_rate": round(hit_rate, 3),
            }

    async def _periodic_cleanup(self):
        """Background task to clean up expired entries."""
        while True:
            try:
                await asyncio.sleep(60)  # Run every minute
                await self._cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cache cleanup error: {e}")

    async def _cleanup_expired(self):
        """Remove expired entries from cache."""
        async with self._lock:
            expired_keys = []
            now = datetime.now()

            for key, entry in self._store.items():
                if entry.expires_at <= now:
                    expired_keys.append(key)

            for key in expired_keys:
                del self._store[key]
                self._stats["evictions"] += 1

            if expired_keys:
                logger.debug(
                    f"Cache cleanup: removed {len(expired_keys)} expired entries"
                )

    def shutdown(self):
        """Shutdown the cache and cleanup task."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()


# Cache key generators for consistent naming
class CacheKeys:
    """Cache key generators for consistent naming across the service."""

    @staticmethod
    def chargers_list(skip: int, limit: int, active_only: bool) -> str:
        """Generate cache key for charger list requests."""
        return f"chargers:list:{skip}:{limit}:{active_only}"

    @staticmethod
    def charger_by_id(charger_id: str) -> str:
        """Generate cache key for individual charger."""
        return f"charger:id:{charger_id}"

    @staticmethod
    def active_charger_ids(skip: int, limit: int) -> str:
        """Generate cache key for active charger IDs."""
        return f"chargers:active_ids:{skip}:{limit}"

    @staticmethod
    def telemetry_types(charger_id: str, limit: int) -> str:
        """Generate cache key for telemetry types."""
        return f"telemetry:types:{charger_id}:{limit}"

    @staticmethod
    def user_by_email(email: str) -> str:
        """Generate cache key for user lookup."""
        return f"user:email:{email}"

    @staticmethod
    def user_favorites(user_id: int) -> str:
        """Generate cache key for user favorites."""
        return f"user:favorites:{user_id}"

    @staticmethod
    def charger_anomalies(charger_id: str, limit: int) -> str:
        """Generate cache key for charger anomalies."""
        return f"anomalies:charger:{charger_id}:{limit}"


# Global cache instance
cache = SimpleCache(default_ttl_seconds=300)  # 5 minute default TTL


# Cache decorators for common patterns
def cache_result(key_func, ttl_seconds: Optional[int] = None):
    """
    Decorator to cache function results.

    Args:
        key_func: Function to generate cache key from function args
        ttl_seconds: Optional TTL override
    """

    def decorator(func):
        async def wrapper(*args, **kwargs):
            cache_key = key_func(*args, **kwargs)

            # Try to get from cache first
            cached_result = await cache.get(cache_key)
            if cached_result is not None:
                return cached_result

            # Call function and cache result
            result = await func(*args, **kwargs)
            await cache.set(cache_key, result, ttl_seconds)

            return result

        return wrapper

    return decorator


__all__ = [
    "SimpleCache",
    "CacheEntry",
    "CacheKeys",
    "cache",
    "cache_result",
]
