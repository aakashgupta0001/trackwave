"""Redis Stream consumer worker for the railcast-prediction-workers consumer group."""

import asyncio
import logging
from typing import Any

from redis.asyncio import Redis

from app.cache.redis import redis_client as default_redis
from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.streaming.metrics import streaming_metrics
from app.streaming.pipeline import streaming_pipeline
from app.streaming.schemas import NormalizedTrainEvent

logger = logging.getLogger(__name__)


class StreamingConsumer:
    """Consumes incoming train events from Redis Streams, processing them via

    the continuous prediction pipeline and acknowledging upon completion.
    """

    def __init__(
        self,
        redis: Redis | None = None,
        stream_name: str | None = None,
        group_name: str | None = None,
        consumer_name: str | None = None,
    ) -> None:
        self.settings = get_settings()
        self._redis = redis
        self.stream_name = stream_name or self.settings.REDIS_STREAM_TRAIN_EVENTS
        self.group_name = group_name or self.settings.REDIS_CONSUMER_GROUP
        self.consumer_name = consumer_name or self.settings.REDIS_CONSUMER_NAME
        self.running: bool = False

    @property
    def redis(self) -> Redis:
        return self._redis or default_redis

    async def setup_consumer_group(self) -> None:
        """Ensure consumer group exists on the stream."""
        try:
            await self.redis.xgroup_create(
                name=self.stream_name,
                groupname=self.group_name,
                id="0",
                mkstream=True,
            )
            logger.info("Created consumer group %s on %s", self.group_name, self.stream_name)
        except Exception as exc:
            if "BUSYGROUP" in str(exc):
                logger.debug("Consumer group %s already exists", self.group_name)
            else:
                logger.warning("Could not create consumer group: %s", exc)

    async def process_message(self, msg_id: str, fields: dict[str, Any]) -> bool:
        """Parse stream entry, execute pipeline within a DB session, and ACK on success."""
        raw_data = fields.get("data")
        if not raw_data:
            logger.warning("Stream message %s has no 'data' payload; acknowledging and discarding", msg_id)
            await self.redis.xack(self.stream_name, self.group_name, msg_id)
            return False

        try:
            event = NormalizedTrainEvent.model_validate_json(raw_data)
        except Exception as exc:
            logger.error("Failed to parse NormalizedTrainEvent from msg_id=%s: %s", msg_id, exc)
            # Poison pill: ACK to prevent blocking pipeline
            await self.redis.xack(self.stream_name, self.group_name, msg_id)
            return False

        try:
            async with AsyncSessionLocal() as session:
                await streaming_pipeline.process_stream_event(session, event)

            # Acknowledge processed message in Redis Stream
            await self.redis.xack(self.stream_name, self.group_name, msg_id)
            return True
        except Exception as exc:
            logger.error("Error processing stream event %s (msg_id=%s): %s", event.event_id, msg_id, exc, exc_info=True)
            return False

    async def run(self, max_messages: int | None = None, poll_interval_ms: int = 1000) -> None:
        """Run consumer loop reading pending and new messages."""
        self.running = True
        streaming_metrics.set_worker_status("RUNNING")
        await self.setup_consumer_group()

        processed_count = 0
        logger.info(
            "StreamingConsumer started [group=%s, worker=%s, stream=%s]",
            self.group_name,
            self.consumer_name,
            self.stream_name,
        )

        try:
            while self.running:
                try:
                    # 1. First drain unacknowledged pending messages for this consumer (ID '0')
                    pending_response = await self.redis.xreadgroup(
                        groupname=self.group_name,
                        consumername=self.consumer_name,
                        streams={self.stream_name: "0"},
                        count=10,
                    )
                    has_pending = False
                    if pending_response:
                        for _stream, messages in pending_response:
                            for msg_id, fields in messages:
                                has_pending = True
                                await self.process_message(msg_id, fields)
                                processed_count += 1
                                if max_messages and processed_count >= max_messages:
                                    return

                    # 2. If no pending, read new messages (ID '>')
                    if not has_pending:
                        response = await self.redis.xreadgroup(
                            groupname=self.group_name,
                            consumername=self.consumer_name,
                            streams={self.stream_name: ">"},
                            count=10,
                            block=poll_interval_ms,
                        )
                        if response:
                            for _stream, messages in response:
                                for msg_id, fields in messages:
                                    await self.process_message(msg_id, fields)
                                    processed_count += 1
                                    if max_messages and processed_count >= max_messages:
                                        return

                except asyncio.CancelledError:
                    break
                except Exception as exc:
                    logger.warning("Consumer loop error: %s", exc)
                    await asyncio.sleep(1.0)

        finally:
            self.running = False
            streaming_metrics.set_worker_status("STOPPED")
            logger.info("StreamingConsumer stopped (processed %d messages)", processed_count)

    def stop(self) -> None:
        self.running = False
