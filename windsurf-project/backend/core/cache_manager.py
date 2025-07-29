"""
Cache manager for robot status and configuration data.
Provides in-memory caching with TTL and invalidation strategies.
"""

import asyncio
import json
import time
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from enum import Enum
import logging
from datetime import datetime, timedelta


class CacheKey(Enum):
    """Predefined cache keys for consistent access"""
    ROBOT_STATUS = "robot_status"
    ROBOT_CONFIG = "robot_config"
    CAROUSEL_POSITIONS = "carousel_positions"
    WAFER_LOCATIONS = "wafer_locations"
    PROTOCOL_TEMPLATES = "protocol_templates"
    SYSTEM_HEALTH = "system_health"
    CIRCUIT_BREAKER_STATUS = "circuit_breaker_status"


@dataclass
class CacheEntry:
    """Cache entry with metadata"""
    value: Any
    created_at: float
    ttl: float
    access_count: int = 0
    last_accessed: float = field(default_factory=time.time)
    tags: List[str] = field(default_factory=list)
    
    @property
    def is_expired(self) -> bool:
        """Check if cache entry has expired"""
        return time.time() - self.created_at > self.ttl
    
    @property
    def age(self) -> float:
        """Get age of cache entry in seconds"""
        return time.time() - self.created_at
    
    def touch(self):
        """Update last accessed time and increment access count"""
        self.last_accessed = time.time()
        self.access_count += 1


class CacheInvalidationStrategy(Enum):
    """Cache invalidation strategies"""
    TTL_ONLY = "ttl_only"  # Only time-based expiration
    LRU = "lru"  # Least Recently Used
    LFU = "lfu"  # Least Frequently Used
    TAG_BASED = "tag_based"  # Tag-based invalidation


class InMemoryCacheManager:
    """
    High-performance in-memory cache manager for robot status and configuration data.
    
    Features:
    - TTL-based expiration
    - Tag-based invalidation
    - Statistics and monitoring
    - Async-safe operations
    - Memory usage tracking
    """

    def __init__(
        self,
        default_ttl: float = 300.0,  # 5 minutes
        max_size: int = 1000,
        cleanup_interval: float = 60.0,  # 1 minute
        invalidation_strategy: CacheInvalidationStrategy = CacheInvalidationStrategy.TTL_ONLY
    ):
        self.default_ttl = default_ttl
        self.max_size = max_size
        self.cleanup_interval = cleanup_interval
        self.invalidation_strategy = invalidation_strategy
        
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None
        self._stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "total_entries": 0,
            "memory_usage": 0
        }
        
        self.logger = logging.getLogger("cache_manager")
        
        # Invalidation callbacks
        self._invalidation_callbacks: Dict[str, List[Callable]] = {}

    async def start(self):
        """Start the cache manager and cleanup task"""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            self.logger.info("Cache manager started")

    async def stop(self):
        """Stop the cache manager and cleanup task"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
        
        await self.clear()
        self.logger.info("Cache manager stopped")

    async def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None if not found/expired
        """
        async with self._lock:
            entry = self._cache.get(key)
            
            if entry is None:
                self._stats["misses"] += 1
                return None
            
            if entry.is_expired:
                await self._remove_entry(key)
                self._stats["misses"] += 1
                return None
            
            entry.touch()
            self._stats["hits"] += 1
            return entry.value

    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[float] = None,
        tags: Optional[List[str]] = None
    ) -> bool:
        """
        Set value in cache.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live in seconds (uses default if None)
            tags: Tags for invalidation
            
        Returns:
            True if set successfully
        """
        if ttl is None:
            ttl = self.default_ttl
        
        if tags is None:
            tags = []

        async with self._lock:
            # Check if we need to evict entries
            if len(self._cache) >= self.max_size:
                await self._evict_entries()

            entry = CacheEntry(
                value=value,
                created_at=time.time(),
                ttl=ttl,
                tags=tags
            )
            
            self._cache[key] = entry
            self._stats["total_entries"] = len(self._cache)
            
            self.logger.debug(f"Cached entry: {key} (TTL: {ttl}s, Tags: {tags})")
            return True

    async def delete(self, key: str) -> bool:
        """
        Delete entry from cache.
        
        Args:
            key: Cache key
            
        Returns:
            True if deleted, False if not found
        """
        async with self._lock:
            if key in self._cache:
                await self._remove_entry(key)
                return True
            return False

    async def invalidate_by_tag(self, tag: str) -> int:
        """
        Invalidate all entries with specific tag.
        
        Args:
            tag: Tag to invalidate
            
        Returns:
            Number of entries invalidated
        """
        async with self._lock:
            keys_to_remove = []
            
            for key, entry in self._cache.items():
                if tag in entry.tags:
                    keys_to_remove.append(key)
            
            for key in keys_to_remove:
                await self._remove_entry(key)
            
            self.logger.info(f"Invalidated {len(keys_to_remove)} entries with tag: {tag}")
            return len(keys_to_remove)

    async def invalidate_pattern(self, pattern: str) -> int:
        """
        Invalidate all entries matching key pattern.
        
        Args:
            pattern: Key pattern (supports * wildcard)
            
        Returns:
            Number of entries invalidated
        """
        import fnmatch
        
        async with self._lock:
            keys_to_remove = []
            
            for key in self._cache.keys():
                if fnmatch.fnmatch(key, pattern):
                    keys_to_remove.append(key)
            
            for key in keys_to_remove:
                await self._remove_entry(key)
            
            self.logger.info(f"Invalidated {len(keys_to_remove)} entries matching pattern: {pattern}")
            return len(keys_to_remove)

    async def get_or_set(
        self,
        key: str,
        factory: Callable,
        ttl: Optional[float] = None,
        tags: Optional[List[str]] = None
    ) -> Any:
        """
        Get value from cache, or set it using factory function if not found.
        
        Args:
            key: Cache key
            factory: Function to generate value if not cached
            ttl: Time to live in seconds
            tags: Tags for invalidation
            
        Returns:
            Cached or newly generated value
        """
        value = await self.get(key)
        
        if value is not None:
            return value
        
        # Generate new value
        if asyncio.iscoroutinefunction(factory):
            value = await factory()
        else:
            value = factory()
        
        await self.set(key, value, ttl, tags)
        return value

    async def clear(self) -> int:
        """
        Clear all cache entries.
        
        Returns:
            Number of entries cleared
        """
        async with self._lock:
            count = len(self._cache)
            self._cache.clear()
            self._stats["total_entries"] = 0
            self._stats["evictions"] += count
            
            self.logger.info(f"Cleared {count} cache entries")
            return count

    async def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        async with self._lock:
            hit_rate = 0.0
            total_requests = self._stats["hits"] + self._stats["misses"]
            if total_requests > 0:
                hit_rate = self._stats["hits"] / total_requests

            return {
                **self._stats,
                "hit_rate": hit_rate,
                "current_size": len(self._cache),
                "max_size": self.max_size,
                "oldest_entry_age": await self._get_oldest_entry_age(),
                "cleanup_interval": self.cleanup_interval
            }

    async def register_invalidation_callback(self, pattern: str, callback: Callable):
        """
        Register callback for cache invalidation events.
        
        Args:
            pattern: Key pattern to watch
            callback: Function to call on invalidation
        """
        if pattern not in self._invalidation_callbacks:
            self._invalidation_callbacks[pattern] = []
        
        self._invalidation_callbacks[pattern].append(callback)

    async def _remove_entry(self, key: str):
        """Remove entry and trigger callbacks"""
        if key in self._cache:
            del self._cache[key]
            self._stats["total_entries"] = len(self._cache)
            
            # Trigger invalidation callbacks
            await self._trigger_invalidation_callbacks(key)

    async def _trigger_invalidation_callbacks(self, key: str):
        """Trigger invalidation callbacks for key"""
        import fnmatch
        
        for pattern, callbacks in self._invalidation_callbacks.items():
            if fnmatch.fnmatch(key, pattern):
                for callback in callbacks:
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(key)
                        else:
                            callback(key)
                    except Exception as e:
                        self.logger.error(f"Error in invalidation callback for {key}: {e}")

    async def _evict_entries(self):
        """Evict entries based on invalidation strategy"""
        if self.invalidation_strategy == CacheInvalidationStrategy.LRU:
            await self._evict_lru()
        elif self.invalidation_strategy == CacheInvalidationStrategy.LFU:
            await self._evict_lfu()
        else:
            await self._evict_oldest()

    async def _evict_lru(self):
        """Evict least recently used entry"""
        if not self._cache:
            return
        
        lru_key = min(self._cache.keys(), key=lambda k: self._cache[k].last_accessed)
        await self._remove_entry(lru_key)
        self._stats["evictions"] += 1

    async def _evict_lfu(self):
        """Evict least frequently used entry"""
        if not self._cache:
            return
        
        lfu_key = min(self._cache.keys(), key=lambda k: self._cache[k].access_count)
        await self._remove_entry(lfu_key)
        self._stats["evictions"] += 1

    async def _evict_oldest(self):
        """Evict oldest entry"""
        if not self._cache:
            return
        
        oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k].created_at)
        await self._remove_entry(oldest_key)
        self._stats["evictions"] += 1

    async def _cleanup_loop(self):
        """Background cleanup task"""
        while True:
            try:
                await asyncio.sleep(self.cleanup_interval)
                await self._cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in cleanup loop: {e}")

    async def _cleanup_expired(self):
        """Remove expired entries"""
        async with self._lock:
            expired_keys = []
            
            for key, entry in self._cache.items():
                if entry.is_expired:
                    expired_keys.append(key)
            
            for key in expired_keys:
                await self._remove_entry(key)
            
            if expired_keys:
                self.logger.debug(f"Cleaned up {len(expired_keys)} expired entries")

    async def _get_oldest_entry_age(self) -> float:
        """Get age of oldest entry in seconds"""
        if not self._cache:
            return 0.0
        
        oldest_time = min(entry.created_at for entry in self._cache.values())
        return time.time() - oldest_time


class RobotStatusCache:
    """
    Specialized cache for robot status data with smart invalidation.
    """

    def __init__(self, cache_manager: InMemoryCacheManager):
        self.cache_manager = cache_manager
        self.logger = logging.getLogger("robot_status_cache")

    async def get_robot_status(self, robot_id: str) -> Optional[Dict[str, Any]]:
        """Get cached robot status"""
        key = f"{CacheKey.ROBOT_STATUS.value}:{robot_id}"
        return await self.cache_manager.get(key)

    async def set_robot_status(
        self,
        robot_id: str,
        status: Dict[str, Any],
        ttl: float = 30.0  # Short TTL for dynamic data
    ) -> bool:
        """Cache robot status with tags"""
        key = f"{CacheKey.ROBOT_STATUS.value}:{robot_id}"
        tags = ["robot_status", f"robot:{robot_id}"]
        return await self.cache_manager.set(key, status, ttl, tags)

    async def invalidate_robot_status(self, robot_id: str) -> bool:
        """Invalidate specific robot status"""
        key = f"{CacheKey.ROBOT_STATUS.value}:{robot_id}"
        return await self.cache_manager.delete(key)

    async def invalidate_all_robot_status(self) -> int:
        """Invalidate all robot status entries"""
        return await self.cache_manager.invalidate_by_tag("robot_status")

    async def get_system_health(self) -> Optional[Dict[str, Any]]:
        """Get cached system health"""
        return await self.cache_manager.get(CacheKey.SYSTEM_HEALTH.value)

    async def set_system_health(
        self,
        health_data: Dict[str, Any],
        ttl: float = 60.0
    ) -> bool:
        """Cache system health data"""
        tags = ["system_health", "monitoring"]
        return await self.cache_manager.set(
            CacheKey.SYSTEM_HEALTH.value,
            health_data,
            ttl,
            tags
        )


# Global cache manager instance
_cache_manager: Optional[InMemoryCacheManager] = None
_robot_cache: Optional[RobotStatusCache] = None


async def get_cache_manager() -> InMemoryCacheManager:
    """Get global cache manager instance"""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = InMemoryCacheManager()
        await _cache_manager.start()
    return _cache_manager


async def get_robot_cache() -> RobotStatusCache:
    """Get robot status cache instance"""
    global _robot_cache
    if _robot_cache is None:
        cache_manager = await get_cache_manager()
        _robot_cache = RobotStatusCache(cache_manager)
    return _robot_cache


async def shutdown_cache():
    """Shutdown cache manager"""
    global _cache_manager, _robot_cache
    if _cache_manager:
        await _cache_manager.stop()
        _cache_manager = None
        _robot_cache = None