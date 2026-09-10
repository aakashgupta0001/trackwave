"""WebSocket connection manager with topic-based routing and backpressure protection."""

import asyncio
import logging
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from app.core.config import get_settings
from app.streaming.metrics import streaming_metrics
from app.streaming.schemas import (
    PredictionUpdatePayload,
    WebSocketEnvelope,
    WebSocketMessageType,
)
from app.streaming.state import ActiveTrainState

logger = logging.getLogger(__name__)


class WebSocketConnectionManager:
    """Manages active WebSocket connections, topic subscriptions, and non-blocking broadcasts."""

    def __init__(self) -> None:
        self.settings = get_settings()
        # Maps topic -> set of WebSockets
        self._topic_subscribers: dict[str, set[WebSocket]] = {}
        # Maps WebSocket -> set of topics
        self._client_topics: dict[WebSocket, set[str]] = {}
        # Maps WebSocket -> asyncio.Queue for backpressure mitigation
        self._client_queues: dict[WebSocket, asyncio.Queue] = {}
        # Maps WebSocket -> sender worker task
        self._sender_tasks: dict[WebSocket, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, topics: list[str]) -> None:
        """Accept connection, register topics, and start background sender task."""
        await websocket.accept()
        queue: asyncio.Queue = asyncio.Queue(maxsize=self.settings.WEBSOCKET_MAX_QUEUE_SIZE)

        async with self._lock:
            self._client_topics[websocket] = set(topics)
            self._client_queues[websocket] = queue
            for topic in topics:
                if topic not in self._topic_subscribers:
                    self._topic_subscribers[topic] = set()
                self._topic_subscribers[topic].add(websocket)

        # Start dedicated sender worker to prevent slow clients from blocking broadcasts
        sender_task = asyncio.create_task(self._sender_loop(websocket, queue))
        self._sender_tasks[websocket] = sender_task

        logger.info(
            "WebSocket connected; topics=%s (total active=%d)",
            topics,
            len(self._client_topics),
        )

    async def disconnect(self, websocket: WebSocket) -> None:
        """Unregister connection and clean up sender worker task."""
        async with self._lock:
            topics = self._client_topics.pop(websocket, set())
            for topic in topics:
                subscribers = self._topic_subscribers.get(topic)
                if subscribers and websocket in subscribers:
                    subscribers.discard(websocket)
                if subscribers is not None and len(subscribers) == 0:
                    self._topic_subscribers.pop(topic, None)

            self._client_queues.pop(websocket, None)
            sender_task = self._sender_tasks.pop(websocket, None)
            if sender_task and not sender_task.done():
                sender_task.cancel()

        logger.info("WebSocket disconnected; remaining active=%d", len(self._client_topics))

    async def _sender_loop(self, websocket: WebSocket, queue: asyncio.Queue) -> None:
        """Dedicated per-connection task pulling from bounded queue and pushing to client."""
        try:
            while True:
                envelope: WebSocketEnvelope = await queue.get()
                msg_json = envelope.model_dump_json()
                await websocket.send_text(msg_json)
                streaming_metrics.record_websocket_broadcast()
                queue.task_done()
        except asyncio.CancelledError:
            pass
        except (WebSocketDisconnect, Exception) as exc:
            logger.debug("WebSocket send error/disconnect: %s", exc)
        finally:
            await self.disconnect(websocket)

    def _enqueue_message(self, websocket: WebSocket, envelope: WebSocketEnvelope) -> bool:
        """Attempt non-blocking enqueue. If queue is full, drops message to protect pipeline."""
        queue = self._client_queues.get(websocket)
        if queue is None:
            return False
        try:
            queue.put_nowait(envelope)
            return True
        except asyncio.QueueFull:
            logger.warning("WebSocket queue full for client; dropping message on topic=%s", envelope.topic)
            return False

    async def broadcast_to_topic(self, topic: str, envelope: WebSocketEnvelope) -> int:
        """Broadcast message to all clients subscribed to `topic` or wildcard `all`."""
        targets: set[WebSocket] = set()

        async with self._lock:
            if topic in self._topic_subscribers:
                targets.update(self._topic_subscribers[topic])
            if "all" in self._topic_subscribers and topic != "all":
                targets.update(self._topic_subscribers["all"])

        count = 0
        for ws in targets:
            if self._enqueue_message(ws, envelope):
                count += 1
        return count

    async def broadcast_prediction(self, prediction: PredictionUpdatePayload) -> None:
        """Broadcast prediction updates to train and station topics."""
        train_topic = f"train:{prediction.train_number}"
        station_topic = f"station:{prediction.station_code}"

        envelope_train = WebSocketEnvelope(
            topic=train_topic,
            event_type=WebSocketMessageType.PREDICTION_UPDATE,
            data=prediction.model_dump(mode="json"),
        )
        envelope_station = WebSocketEnvelope(
            topic=station_topic,
            event_type=WebSocketMessageType.PREDICTION_UPDATE,
            data=prediction.model_dump(mode="json"),
        )

        await self.broadcast_to_topic(train_topic, envelope_train)
        await self.broadcast_to_topic(station_topic, envelope_station)

    async def broadcast_train_state(self, state: ActiveTrainState) -> None:
        """Broadcast updated train state to train topic."""
        topic = f"train:{state.train_number}"
        envelope = WebSocketEnvelope(
            topic=topic,
            event_type=WebSocketMessageType.TRAIN_STATE,
            data=state.model_dump(mode="json"),
        )
        await self.broadcast_to_topic(topic, envelope)

    async def broadcast_network_alert(self, alert_data: dict[str, Any]) -> None:
        """Broadcast network alert to network topic and affected trains."""
        envelope = WebSocketEnvelope(
            topic="network",
            event_type=WebSocketMessageType.NETWORK_ALERT,
            data=alert_data,
        )
        await self.broadcast_to_topic("network", envelope)

        train_number = alert_data.get("train_number")
        if train_number:
            train_topic = f"train:{train_number}"
            await self.broadcast_to_topic(train_topic, envelope)

    def get_active_connection_count(self) -> int:
        return len(self._client_topics)

    def get_connection_stats(self) -> dict[str, Any]:
        return {
            "total_clients": len(self._client_topics),
            "topics": {topic: len(subs) for topic, subs in self._topic_subscribers.items()},
        }


# Shared singleton connection manager
ws_manager = WebSocketConnectionManager()
