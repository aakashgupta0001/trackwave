"""Redis Stream publisher for normalized train events and continuous prediction updates."""

import logging
from typing import Any

from redis.asyncio import Redis

from app.cache.redis import redis_client as default_redis
from app.core.config import get_settings
from app.streaming.schemas import NormalizedTrainEvent, PredictionUpdatePayload

logger = logging.getLogger(__name__)


class EventPublisher:
    """Publishes domain events to Redis Streams for asynchronous pipeline consumption."""

    def __init__(self, redis: Redis | None = None) -> None:
        self.settings = get_settings()
        self._redis = redis

    @property
    def redis(self) -> Redis:
        return self._redis or default_redis

    async def publish_event(self, event: NormalizedTrainEvent) -> str | None:
        """Publish a normalized train event to railcast:train-events.

        Returns the Redis stream entry ID if successful, or None if streaming is
        disabled or Redis is unreachable.
        """
        if not self.settings.STREAMING_ENABLED:
            logger.debug("Streaming disabled; skipping publish for train %s", event.train_number)
            return None

        event_type_str = (
            event.event_type.value if hasattr(event.event_type, "value") else str(event.event_type)
        )
        payload = {
            "data": event.model_dump_json(),
            "train_number": event.train_number,
            "event_type": event_type_str,
            "fingerprint": event.fingerprint or "",
        }

        try:
            msg_id = await self.redis.xadd(
                self.settings.REDIS_STREAM_TRAIN_EVENTS,
                payload,
                maxlen=self.settings.STREAM_MAXLEN,
                approximate=True,
            )
            logger.debug("Published event %s for train %s (msg_id=%s)", event.event_id, event.train_number, msg_id)
            return str(msg_id)
        except Exception as exc:
            logger.warning("Failed to publish train event %s to stream: %s", event.event_id, exc)
            return None

    async def publish_prediction(self, prediction: PredictionUpdatePayload) -> str | None:
        """Publish a continuous prediction update to railcast:prediction-updates.

        Returns the Redis stream entry ID if successful, or None if streaming is
        disabled or Redis is unreachable.
        """
        if not self.settings.STREAMING_ENABLED:
            return None

        payload = {
            "data": prediction.model_dump_json(),
            "train_number": prediction.train_number,
            "station_code": prediction.station_code,
        }

        try:
            msg_id = await self.redis.xadd(
                self.settings.REDIS_STREAM_PREDICTIONS,
                payload,
                maxlen=self.settings.STREAM_MAXLEN,
                approximate=True,
            )
            logger.debug(
                "Published prediction for train %s at station %s (msg_id=%s)",
                prediction.train_number,
                prediction.station_code,
                msg_id,
            )
            return str(msg_id)
        except Exception as exc:
            logger.warning("Failed to publish prediction for train %s: %s", prediction.train_number, exc)
            return None


# Shared default singleton
event_publisher = EventPublisher()
