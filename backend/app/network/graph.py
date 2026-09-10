"""RailwayGraphService: the bounded, on-demand view of "which other trains use the same
railway sections as this one" — built directly from Station/RailwaySection/TrainRoute
(module 3 of the spec: no duplicate/parallel network representation).

Every query here is scoped to a specific, small set of section_ids — never a full-table
scan of trains or routes — which is what keeps single-train and network-wide analysis
bounded (modules 4, 33, 34).
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.cache.redis import redis_client
from app.core.config import get_settings
from app.models.route import TrainRoute
from app.models.train import Train

logger = logging.getLogger(__name__)


async def find_candidate_trains(
    session: AsyncSession,
    *,
    section_ids: list[int],
    exclude_train_ids: set[int],
    limit: int,
) -> list[Train]:
    """Every other ACTIVE train with at least one route entry on any of `section_ids`.

    This is deliberately section-based only (not station-based): module 5 of the spec
    is explicit that sharing a station alone must not imply an affected relationship —
    only an actual shared *section* is grounds to even consider two trains related, and
    conflict.py determines from there whether their movements actually overlap in time.
    """
    if not section_ids:
        return []

    stmt = (
        select(Train)
        .join(TrainRoute, TrainRoute.train_id == Train.id)
        .where(Train.active.is_(True), TrainRoute.section_id.in_(section_ids))
        .options(selectinload(Train.source_station), selectinload(Train.destination_station))
        .distinct()
        .limit(limit)
    )
    result = await session.execute(stmt)
    candidates = list(result.scalars().all())
    return [t for t in candidates if t.id not in exclude_train_ids]


async def find_delayed_trains(session: AsyncSession, *, min_delay_minutes: float, limit: int) -> list[Train]:
    """Active trains whose latest known TrainEvent reports a delay — the starting set
    for network-wide analysis (module 19). Bounded to `limit` trains (module 34).
    """
    from app.repositories import event_repository, train_repository

    active_trains = await train_repository.list_all(session, active_only=True)
    delayed: list[Train] = []
    for train in active_trains[:limit]:
        latest_event = await event_repository.get_latest_for_train(session, train.id)
        if latest_event is not None and latest_event.delay_minutes >= min_delay_minutes:
            delayed.append(train)
    return delayed


def graph_cache_key(*, focus: str) -> str:
    return f"railcast:network:graph:{focus}"


async def read_graph_cache(key: str) -> dict | None:
    """Best-effort Redis lookup for a previously-computed graph fragment (module 32).
    Never raises — a cache miss/Redis outage just means recomputing from Postgres.
    """
    try:
        raw = await redis_client.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        logger.warning("Redis unavailable reading network graph cache key=%s", key, exc_info=True)
        return None


async def write_graph_cache(key: str, payload: dict) -> None:
    try:
        settings = get_settings()
        await redis_client.set(key, json.dumps(payload, default=str), ex=settings.NETWORK_GRAPH_CACHE_TTL_SECONDS)
    except Exception:
        logger.warning("Redis unavailable writing network graph cache key=%s", key, exc_info=True)
