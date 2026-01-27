"""
Selective WebSocket broadcaster for optimized real-time communication.
Implements topic-based subscriptions and message filtering for efficient updates.
"""

import asyncio
import json
import time
from typing import Dict, Set, List, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
from fastapi import WebSocket

from utils.logger import get_logger


class MessageType(Enum):
    """WebSocket message types"""
    ROBOT_STATUS = "robot_status"
    SYSTEM_HEALTH = "system_health"
    OPERATION_UPDATE = "operation_update"
    ERROR_NOTIFICATION = "error_notification"
    PROTOCOL_PROGRESS = "protocol_progress"
    CAROUSEL_STATE = "carousel_state"
    WAFER_TRACKING = "wafer_tracking"
    CIRCUIT_BREAKER = "circuit_breaker"
    CONFIGURATION = "configuration"


class SubscriptionLevel(Enum):
    """Subscription levels for message filtering"""
    ALL = "all"  # Receive all messages
    CRITICAL = "critical"  # Only critical/error messages
    ROBOT_SPECIFIC = "robot_specific"  # Only specific robot updates
    OPERATION_TRACKING = "operation_tracking"  # Operation and protocol updates
    MONITORING = "monitoring"  # Health and status monitoring


@dataclass
class ClientSubscription:
    """Client subscription configuration"""
    client_id: str
    websocket: WebSocket
    level: SubscriptionLevel = SubscriptionLevel.ALL
    message_types: Set[MessageType] = field(default_factory=set)
    robot_ids: Set[str] = field(default_factory=set)
    last_activity: float = field(default_factory=time.time)
    message_count: int = 0
    connected_at: float = field(default_factory=time.time)
    
    def matches_filter(self, message_type: MessageType, robot_id: Optional[str] = None) -> bool:
        """Check if client should receive this message"""
        # Check subscription level
        if self.level == SubscriptionLevel.CRITICAL:
            if message_type not in {MessageType.ERROR_NOTIFICATION, MessageType.CIRCUIT_BREAKER}:
                return False
        
        elif self.level == SubscriptionLevel.ROBOT_SPECIFIC:
            if robot_id and robot_id not in self.robot_ids:
                return False
        
        elif self.level == SubscriptionLevel.OPERATION_TRACKING:
            if message_type not in {
                MessageType.OPERATION_UPDATE,
                MessageType.PROTOCOL_PROGRESS,
                MessageType.WAFER_TRACKING
            }:
                return False
        
        elif self.level == SubscriptionLevel.MONITORING:
            if message_type not in {
                MessageType.SYSTEM_HEALTH,
                MessageType.ROBOT_STATUS,
                MessageType.CIRCUIT_BREAKER
            }:
                return False
        
        # Check specific message type subscriptions
        if self.message_types and message_type not in self.message_types:
            return False
        
        return True
    
    def touch(self):
        """Update last activity timestamp"""
        self.last_activity = time.time()


@dataclass
class BroadcastMessage:
    """Message to be broadcast"""
    type: MessageType
    data: Dict[str, Any]
    robot_id: Optional[str] = None
    priority: int = 0  # Higher priority messages sent first
    created_at: float = field(default_factory=time.time)
    ttl: float = 30.0  # Time to live in seconds
    
    @property
    def is_expired(self) -> bool:
        """Check if message has expired"""
        return time.time() - self.created_at > self.ttl


class SelectiveWebSocketBroadcaster:
    """
    High-performance selective WebSocket broadcaster with topic-based subscriptions.
    
    Features:
    - Client subscription management
    - Message filtering and prioritization
    - Batch message delivery
    - Connection health monitoring
    - Performance metrics
    """

    def __init__(
        self,
        batch_size: int = 10,
        batch_timeout: float = 0.1,
        max_queue_size: int = 1000,
        cleanup_interval: float = 60.0
    ):
        self.batch_size = batch_size
        self.batch_timeout = batch_timeout
        self.max_queue_size = max_queue_size
        self.cleanup_interval = cleanup_interval
        
        self._clients: Dict[str, ClientSubscription] = {}
        self._message_queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        self._broadcast_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        
        self._stats = {
            "total_messages": 0,
            "messages_sent": 0,
            "messages_filtered": 0,
            "client_connections": 0,
            "disconnections": 0,
            "errors": 0
        }
        
        self.logger = get_logger("selective_broadcaster")

    async def start(self):
        """Start the broadcaster"""
        if self._broadcast_task is None:
            self._broadcast_task = asyncio.create_task(self._broadcast_loop())
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            self.logger.info("Selective broadcaster started")

    async def stop(self):
        """Stop the broadcaster"""
        # Cancel tasks
        for task in [self._broadcast_task, self._cleanup_task]:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        # Disconnect all clients
        await self.disconnect_all()
        
        self._broadcast_task = None
        self._cleanup_task = None
        self.logger.info("Selective broadcaster stopped")

    async def subscribe_client(
        self,
        client_id: str,
        websocket: WebSocket,
        level: SubscriptionLevel = SubscriptionLevel.ALL,
        message_types: Optional[Set[MessageType]] = None,
        robot_ids: Optional[Set[str]] = None
    ) -> bool:
        """
        Subscribe a client to updates.
        
        Args:
            client_id: Unique client identifier
            websocket: WebSocket connection
            level: Subscription level
            message_types: Specific message types to receive
            robot_ids: Specific robot IDs to monitor
            
        Returns:
            True if subscribed successfully
        """
        try:
            subscription = ClientSubscription(
                client_id=client_id,
                websocket=websocket,
                level=level,
                message_types=message_types or set(),
                robot_ids=robot_ids or set()
            )
            
            self._clients[client_id] = subscription
            self._stats["client_connections"] += 1
            
            self.logger.info(
                f"Client {client_id} subscribed with level {level.value}, "
                f"types: {[t.value for t in (message_types or [])]}, "
                f"robots: {list(robot_ids or [])}"
            )
            
            # Send welcome message
            await self._send_to_client(
                subscription,
                {
                    "type": "subscription_confirmed",
                    "client_id": client_id,
                    "level": level.value,
                    "timestamp": time.time()
                }
            )
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error subscribing client {client_id}: {e}")
            return False

    async def unsubscribe_client(self, client_id: str) -> bool:
        """
        Unsubscribe a client.
        
        Args:
            client_id: Client identifier
            
        Returns:
            True if unsubscribed successfully
        """
        if client_id in self._clients:
            subscription = self._clients[client_id]
            
            try:
                await subscription.websocket.close()
            except Exception:
                pass  # Connection may already be closed
            
            del self._clients[client_id]
            self._stats["disconnections"] += 1
            
            self.logger.info(f"Client {client_id} unsubscribed")
            return True
        
        return False

    async def update_subscription(
        self,
        client_id: str,
        level: Optional[SubscriptionLevel] = None,
        message_types: Optional[Set[MessageType]] = None,
        robot_ids: Optional[Set[str]] = None
    ) -> bool:
        """
        Update client subscription settings.
        
        Args:
            client_id: Client identifier
            level: New subscription level
            message_types: New message types
            robot_ids: New robot IDs
            
        Returns:
            True if updated successfully
        """
        if client_id not in self._clients:
            return False
        
        subscription = self._clients[client_id]
        
        if level is not None:
            subscription.level = level
        
        if message_types is not None:
            subscription.message_types = message_types
        
        if robot_ids is not None:
            subscription.robot_ids = robot_ids
        
        self.logger.info(f"Updated subscription for client {client_id}")
        return True

    async def broadcast_message(
        self,
        message_type: MessageType,
        data: Dict[str, Any],
        robot_id: Optional[str] = None,
        priority: int = 0
    ) -> bool:
        """
        Queue a message for broadcasting.
        
        Args:
            message_type: Type of message
            data: Message data
            robot_id: Related robot ID (optional)
            priority: Message priority (higher = more important)
            
        Returns:
            True if queued successfully
        """
        try:
            message = BroadcastMessage(
                type=message_type,
                data=data,
                robot_id=robot_id,
                priority=priority
            )
            
            # Try to queue message (non-blocking)
            try:
                self._message_queue.put_nowait(message)
                self._stats["total_messages"] += 1
                return True
            except asyncio.QueueFull:
                self.logger.warning("Message queue full, dropping message")
                return False
                
        except Exception as e:
            self.logger.error(f"Error queueing message: {e}")
            return False

    async def broadcast_robot_status(
        self,
        robot_id: str,
        status: Dict[str, Any],
        priority: int = 1
    ) -> bool:
        """Broadcast robot status update"""
        return await self.broadcast_message(
            MessageType.ROBOT_STATUS,
            {"robot_id": robot_id, "status": status},
            robot_id=robot_id,
            priority=priority
        )

    async def broadcast_system_health(
        self,
        health_data: Dict[str, Any],
        priority: int = 2
    ) -> bool:
        """Broadcast system health update"""
        return await self.broadcast_message(
            MessageType.SYSTEM_HEALTH,
            health_data,
            priority=priority
        )

    async def broadcast_error(
        self,
        error_data: Dict[str, Any],
        robot_id: Optional[str] = None,
        priority: int = 10
    ) -> bool:
        """Broadcast error notification (high priority)"""
        return await self.broadcast_message(
            MessageType.ERROR_NOTIFICATION,
            error_data,
            robot_id=robot_id,
            priority=priority
        )

    async def disconnect_all(self):
        """Disconnect all clients"""
        for client_id in list(self._clients.keys()):
            await self.unsubscribe_client(client_id)

    async def get_stats(self) -> Dict[str, Any]:
        """Get broadcaster statistics"""
        active_clients = len(self._clients)
        queue_size = self._message_queue.qsize()
        
        # Calculate client subscription distribution
        level_distribution = {}
        for subscription in self._clients.values():
            level = subscription.level.value
            level_distribution[level] = level_distribution.get(level, 0) + 1
        
        return {
            **self._stats,
            "active_clients": active_clients,
            "queue_size": queue_size,
            "max_queue_size": self.max_queue_size,
            "level_distribution": level_distribution,
            "average_messages_per_client": (
                self._stats["messages_sent"] / max(active_clients, 1)
            )
        }

    async def _broadcast_loop(self):
        """Main broadcast loop"""
        message_batch = []
        
        while True:
            try:
                # Collect messages for batch processing
                timeout = self.batch_timeout
                
                while len(message_batch) < self.batch_size:
                    try:
                        message = await asyncio.wait_for(
                            self._message_queue.get(),
                            timeout=timeout
                        )
                        
                        # Skip expired messages
                        if message.is_expired:
                            continue
                        
                        message_batch.append(message)
                        timeout = 0.01  # Reduce timeout for subsequent messages
                        
                    except asyncio.TimeoutError:
                        break
                
                # Process batch if we have messages
                if message_batch:
                    await self._process_message_batch(message_batch)
                    message_batch.clear()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in broadcast loop: {e}")
                await asyncio.sleep(1)

    async def _process_message_batch(self, messages: List[BroadcastMessage]):
        """Process a batch of messages"""
        # Sort by priority (highest first)
        messages.sort(key=lambda m: m.priority, reverse=True)
        
        # Group messages by client
        client_messages: Dict[str, List[Dict[str, Any]]] = {}
        
        for message in messages:
            for client_id, subscription in self._clients.items():
                if subscription.matches_filter(message.type, message.robot_id):
                    if client_id not in client_messages:
                        client_messages[client_id] = []
                    
                    client_messages[client_id].append({
                        "type": message.type.value,
                        "data": message.data,
                        "robot_id": message.robot_id,
                        "timestamp": message.created_at
                    })

        # Send messages to clients
        for client_id, client_message_list in client_messages.items():
            if client_id in self._clients:  # Client might have disconnected
                subscription = self._clients[client_id]
                
                # Send as batch if multiple messages
                if len(client_message_list) > 1:
                    await self._send_to_client(
                        subscription,
                        {
                            "type": "message_batch",
                            "messages": client_message_list,
                            "count": len(client_message_list)
                        }
                    )
                else:
                    await self._send_to_client(subscription, client_message_list[0])

    async def _send_to_client(
        self,
        subscription: ClientSubscription,
        message: Dict[str, Any]
    ):
        """Send message to specific client"""
        try:
            await subscription.websocket.send_json(message)
            subscription.touch()
            subscription.message_count += 1
            self._stats["messages_sent"] += 1
            
        except Exception as e:
            self.logger.warning(f"Failed to send message to {subscription.client_id}: {e}")
            self._stats["errors"] += 1
            
            # Remove disconnected client
            await self.unsubscribe_client(subscription.client_id)

    async def _cleanup_loop(self):
        """Background cleanup task"""
        while True:
            try:
                await asyncio.sleep(self.cleanup_interval)
                await self._cleanup_inactive_clients()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in cleanup loop: {e}")

    async def _cleanup_inactive_clients(self):
        """Remove inactive clients"""
        current_time = time.time()
        inactive_threshold = 300  # 5 minutes
        
        inactive_clients = []
        
        for client_id, subscription in self._clients.items():
            if current_time - subscription.last_activity > inactive_threshold:
                inactive_clients.append(client_id)
        
        for client_id in inactive_clients:
            await self.unsubscribe_client(client_id)
            self.logger.info(f"Removed inactive client: {client_id}")


# Global broadcaster instance
_broadcaster: Optional[SelectiveWebSocketBroadcaster] = None


async def get_broadcaster() -> SelectiveWebSocketBroadcaster:
    """Get global broadcaster instance"""
    global _broadcaster
    if _broadcaster is None:
        _broadcaster = SelectiveWebSocketBroadcaster()
        await _broadcaster.start()
    return _broadcaster


async def shutdown_broadcaster():
    """Shutdown broadcaster"""
    global _broadcaster
    if _broadcaster:
        await _broadcaster.stop()
        _broadcaster = None