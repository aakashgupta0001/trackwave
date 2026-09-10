"""Minimal async polling worker: periodically asks ProviderManager for every active
train's status and ingests whatever comes back (LIVE/SIMULATED/STALE — never UNAVAILABLE,
there's nothing to store). Deliberately simple per the Phase 4 brief — a placeholder that
can later be swapped for Celery/APScheduler/Redis Streams without changing anything
upstream (ProviderManager, ingestion_service) or downstream (the database).

Not started automatically: controlled entirely by LIVE_INGESTION_ENABLED, wired in
app/main.py's lifespan. The API is fully functional with this worker off — see module 17.
"""

import asyncio
import logging
from datetime import date

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal
from app.providers.manager import provider_manager
from app.repositories import train_repository
from app.services import ingestion_service

logger = logging.getLogger(__name__)


class IngestionWorker:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name="ingestion-worker")
        logger.info("Ingestion worker started interval_seconds=%s", self._settings.LIVE_INGESTION_INTERVAL_SECONDS)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info("Ingestion worker stopped")

    async def _run(self) -> None:
        while True:
            try:
                await self._poll_once()
            except Exception:
                logger.exception("Ingestion worker tick failed unexpectedly")
            await asyncio.sleep(self._settings.LIVE_INGESTION_INTERVAL_SECONDS)

    async def _poll_once(self) -> None:
        today = date.today()
        async with AsyncSessionLocal() as session:
            trains = await train_repository.list_all(session, active_only=True)
            for train in trains:
                try:
                    result = await provider_manager.get_train_status(session, train.train_number, today)
                except Exception:
                    logger.exception("Ingestion tick failed for train_number=%s", train.train_number)
                    continue

                if result.data is None:
                    continue  # UNAVAILABLE — nothing to store, already logged by the manager

                await ingestion_service.ingest_train_state(session, result.data)


ingestion_worker = IngestionWorker()
