"""
Resource lock manager for preventing race conditions in multi-robot operations.
Provides distributed locking for shared resources like carousel, sample positions, etc.
"""

import asyncio
import time
from contextlib import asynccontextmanager
from typing import Dict, Optional, Set, Any
from dataclasses import dataclass, field
from enum import Enum

from .exceptions import ResourceLockTimeout, ValidationError
from utils.logger import get_logger


class LockType(Enum):
    """Types of locks available"""
    EXCLUSIVE = "exclusive"  # Only one holder allowed
    SHARED = "shared"       # Multiple readers, single writer


@dataclass
class LockInfo:
    """Information about an active lock"""
    resource_id: str
    holder_id: str
    lock_type: LockType
    acquired_at: float
    expires_at: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def is_expired(self) -> bool:
        """Check if lock has expired"""
        return self.expires_at is not None and time.time() > self.expires_at
    
    @property
    def age_seconds(self) -> float:
        """Get lock age in seconds"""
        return time.time() - self.acquired_at


class ResourceLockManager:
    """
    Manages distributed locks for shared resources in the robotics system.
    
    Prevents race conditions when multiple robots or operations need
    to access shared resources like carousel positions, sample containers, etc.
    """
    
    def __init__(self, default_timeout: float = 30.0, cleanup_interval: float = 60.0):
        self.default_timeout = default_timeout
        self.cleanup_interval = cleanup_interval
        
        # Resource locks: resource_id -> LockInfo
        self._locks: Dict[str, LockInfo] = {}
        
        # Shared locks: resource_id -> set of holder_ids
        self._shared_locks: Dict[str, Set[str]] = {}
        
        # Waiters: resource_id -> list of (holder_id, future, lock_type)
        self._waiters: Dict[str, list] = {}
        
        # Main lock for thread safety
        self._lock = asyncio.Lock()
        
        # Cleanup task
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False
        
        self.logger = get_logger("resource_lock_manager")
    
    async def start(self):
        """Start the lock manager and cleanup task"""
        if self._running:
            return
        
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_expired_locks())
        self.logger.info("ResourceLockManager started")
    
    async def stop(self):
        """Stop the lock manager and cleanup task"""
        if not self._running:
            return
        
        self._running = False
        
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        # Release all locks
        async with self._lock:
            self._locks.clear()
            self._shared_locks.clear()
            
            # Cancel all waiting futures
            for waiters in self._waiters.values():
                for _, future, _ in waiters:
                    if not future.done():
                        future.cancel()
            self._waiters.clear()
        
        self.logger.info("ResourceLockManager stopped")
    
    @asynccontextmanager
    async def acquire_resource(
        self,
        resource_id: str,
        holder_id: str = None,
        timeout: float = None,
        lock_type: LockType = LockType.EXCLUSIVE,
        lease_duration: float = None,
        metadata: Dict[str, Any] = None
    ):
        """
        Context manager for acquiring resource locks.
        
        Args:
            resource_id: Unique identifier for the resource
            holder_id: Identifier for the lock holder (defaults to task name)
            timeout: Maximum time to wait for lock acquisition
            lock_type: Type of lock to acquire (exclusive or shared)
            lease_duration: How long to hold the lock before auto-release
            metadata: Additional metadata about the lock
            
        Yields:
            LockInfo object containing lock details
            
        Raises:
            ResourceLockTimeout: If lock cannot be acquired within timeout
            ValidationError: If parameters are invalid
        """
        if timeout is None:
            timeout = self.default_timeout
        
        if holder_id is None:
            # Use current task name as holder ID
            try:
                current_task = asyncio.current_task()
                holder_id = f"task-{id(current_task)}" if current_task else "unknown"
            except RuntimeError:
                holder_id = "unknown"
        
        if not resource_id:
            raise ValidationError("Resource ID cannot be empty", field="resource_id")
        
        if timeout <= 0:
            raise ValidationError("Timeout must be positive", field="timeout", value=timeout)
        
        lock_info = None
        try:
            # Acquire the lock
            lock_info = await self._acquire_lock(
                resource_id=resource_id,
                holder_id=holder_id,
                timeout=timeout,
                lock_type=lock_type,
                lease_duration=lease_duration,
                metadata=metadata or {}
            )
            
            self.logger.debug(
                f"Lock acquired: {resource_id} by {holder_id} "
                f"(type: {lock_type.value}, timeout: {timeout}s)"
            )
            
            yield lock_info
            
        finally:
            # Always release the lock
            if lock_info:
                await self._release_lock(resource_id, holder_id, lock_type)
                self.logger.debug(f"Lock released: {resource_id} by {holder_id}")
    
    async def _acquire_lock(
        self,
        resource_id: str,
        holder_id: str,
        timeout: float,
        lock_type: LockType,
        lease_duration: Optional[float],
        metadata: Dict[str, Any]
    ) -> LockInfo:
        """Internal method to acquire a lock"""
        start_time = time.time()
        
        while True:
            async with self._lock:
                # Check if we can acquire the lock immediately
                if await self._can_acquire_lock(resource_id, holder_id, lock_type):
                    return await self._grant_lock(
                        resource_id, holder_id, lock_type, lease_duration, metadata
                    )
                
                # Check timeout
                elapsed = time.time() - start_time
                remaining = timeout - elapsed
                
                if remaining <= 0:
                    raise ResourceLockTimeout(
                        f"Could not acquire lock for '{resource_id}' within {timeout}s",
                        resource_id=resource_id,
                        timeout=timeout,
                        context={
                            "holder_id": holder_id,
                            "lock_type": lock_type.value,
                            "current_lock": self._get_lock_info(resource_id)
                        }
                    )
                
                # Wait for lock to become available
                future = asyncio.Future()
                if resource_id not in self._waiters:
                    self._waiters[resource_id] = []
                self._waiters[resource_id].append((holder_id, future, lock_type))
            
            # Wait outside the lock to avoid blocking other operations
            try:
                await asyncio.wait_for(future, timeout=remaining)
            except asyncio.TimeoutError:
                # Remove from waiters list
                async with self._lock:
                    if resource_id in self._waiters:
                        self._waiters[resource_id] = [
                            (h, f, t) for h, f, t in self._waiters[resource_id]
                            if f != future
                        ]
                        if not self._waiters[resource_id]:
                            del self._waiters[resource_id]
                
                raise ResourceLockTimeout(
                    f"Could not acquire lock for '{resource_id}' within {timeout}s",
                    resource_id=resource_id,
                    timeout=timeout
                )
    
    async def _can_acquire_lock(
        self, resource_id: str, holder_id: str, lock_type: LockType
    ) -> bool:
        """Check if a lock can be acquired"""
        current_lock = self._locks.get(resource_id)
        
        # No existing lock
        if not current_lock:
            return True
        
        # Lock expired
        if current_lock.is_expired:
            await self._cleanup_expired_lock(resource_id)
            return True
        
        # Same holder can always reacquire
        if current_lock.holder_id == holder_id:
            return True
        
        # Shared lock logic
        if lock_type == LockType.SHARED and current_lock.lock_type == LockType.SHARED:
            return True
        
        # Exclusive lock logic - cannot acquire if any lock exists
        return False
    
    async def _grant_lock(
        self,
        resource_id: str,
        holder_id: str,
        lock_type: LockType,
        lease_duration: Optional[float],
        metadata: Dict[str, Any]
    ) -> LockInfo:
        """Grant a lock to the holder"""
        now = time.time()
        expires_at = now + lease_duration if lease_duration else None
        
        lock_info = LockInfo(
            resource_id=resource_id,
            holder_id=holder_id,
            lock_type=lock_type,
            acquired_at=now,
            expires_at=expires_at,
            metadata=metadata
        )
        
        if lock_type == LockType.EXCLUSIVE:
            self._locks[resource_id] = lock_info
        else:  # SHARED
            self._locks[resource_id] = lock_info
            if resource_id not in self._shared_locks:
                self._shared_locks[resource_id] = set()
            self._shared_locks[resource_id].add(holder_id)
        
        return lock_info
    
    async def _release_lock(
        self, resource_id: str, holder_id: str, lock_type: LockType
    ):
        """Release a lock"""
        async with self._lock:
            current_lock = self._locks.get(resource_id)
            if not current_lock or current_lock.holder_id != holder_id:
                return
            
            if lock_type == LockType.SHARED:
                # Remove from shared locks
                if resource_id in self._shared_locks:
                    self._shared_locks[resource_id].discard(holder_id)
                    if not self._shared_locks[resource_id]:
                        del self._shared_locks[resource_id]
                        del self._locks[resource_id]
            else:
                # Remove exclusive lock
                del self._locks[resource_id]
            
            # Notify waiters
            await self._notify_waiters(resource_id)
    
    async def _notify_waiters(self, resource_id: str):
        """Notify waiters that a resource is available"""
        if resource_id not in self._waiters:
            return
        
        # Notify all waiters (they will check if they can acquire)
        waiters = self._waiters[resource_id][:]
        for holder_id, future, lock_type in waiters:
            if not future.done():
                future.set_result(None)
        
        del self._waiters[resource_id]
    
    async def _cleanup_expired_locks(self):
        """Background task to clean up expired locks"""
        while self._running:
            try:
                await asyncio.sleep(self.cleanup_interval)
                await self._cleanup_expired_locks_once()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in lock cleanup: {e}")
    
    async def _cleanup_expired_locks_once(self):
        """Clean up expired locks once"""
        expired_resources = []
        
        async with self._lock:
            for resource_id, lock_info in list(self._locks.items()):
                if lock_info.is_expired:
                    expired_resources.append(resource_id)
                    await self._cleanup_expired_lock(resource_id)
        
        if expired_resources:
            self.logger.info(f"Cleaned up {len(expired_resources)} expired locks")
    
    async def _cleanup_expired_lock(self, resource_id: str):
        """Clean up a specific expired lock"""
        if resource_id in self._locks:
            del self._locks[resource_id]
        if resource_id in self._shared_locks:
            del self._shared_locks[resource_id]
        
        # Notify waiters
        await self._notify_waiters(resource_id)
    
    def _get_lock_info(self, resource_id: str) -> Optional[Dict[str, Any]]:
        """Get lock information for debugging"""
        lock = self._locks.get(resource_id)
        if not lock:
            return None
        
        return {
            "holder_id": lock.holder_id,
            "lock_type": lock.lock_type.value,
            "acquired_at": lock.acquired_at,
            "expires_at": lock.expires_at,
            "age_seconds": lock.age_seconds,
            "is_expired": lock.is_expired,
            "metadata": lock.metadata
        }
    
    async def get_all_locks(self) -> Dict[str, Dict[str, Any]]:
        """Get information about all active locks"""
        async with self._lock:
            return {
                resource_id: self._get_lock_info(resource_id)
                for resource_id in self._locks
            }
    
    async def force_release_lock(self, resource_id: str, holder_id: str = None):
        """Force release a lock (for emergency situations)"""
        async with self._lock:
            current_lock = self._locks.get(resource_id)
            if not current_lock:
                return False
            
            if holder_id and current_lock.holder_id != holder_id:
                return False
            
            # Force release
            del self._locks[resource_id]
            if resource_id in self._shared_locks:
                del self._shared_locks[resource_id]
            
            await self._notify_waiters(resource_id)
            
            self.logger.warning(
                f"Forcibly released lock: {resource_id} "
                f"(was held by {current_lock.holder_id})"
            )
            return True
    
    async def get_status(self) -> Dict[str, Any]:
        """Get overall lock manager status"""
        async with self._lock:
            return {
                "running": self._running,
                "total_locks": len(self._locks),
                "shared_locks": len(self._shared_locks),
                "waiters": sum(len(w) for w in self._waiters.values()),
                "config": {
                    "default_timeout": self.default_timeout,
                    "cleanup_interval": self.cleanup_interval
                }
            }