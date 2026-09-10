from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert
from app.models.enums import AlertSeverity, AlertType


async def find_by_fingerprint(session: AsyncSession, fingerprint: str) -> Alert | None:
    """Alert deduplication (Phase 8, module 27): a fingerprint is stored in
    `alert_metadata["fingerprint"]`. Looking it up before creating an alert is what
    keeps a repeated analysis cycle from emitting the same predictive alert forever.
    """
    result = await session.execute(
        select(Alert)
        .where(Alert.alert_metadata["fingerprint"].astext == fingerprint)
        .order_by(Alert.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def create(
    session: AsyncSession,
    *,
    alert_type: AlertType,
    severity: AlertSeverity,
    title: str,
    description: str | None,
    train_id: int | None = None,
    section_id: int | None = None,
    station_id: int | None = None,
    metadata: dict | None = None,
) -> Alert:
    alert = Alert(
        alert_type=alert_type,
        severity=severity,
        title=title,
        description=description,
        train_id=train_id,
        section_id=section_id,
        station_id=station_id,
        alert_metadata=metadata,
    )
    session.add(alert)
    await session.flush()
    return alert


async def list_active_paginated(
    session: AsyncSession,
    *,
    offset: int,
    limit: int,
    alert_type: AlertType | None = None,
    severity: AlertSeverity | None = None,
    train_id: int | None = None,
    section_id: int | None = None,
    station_id: int | None = None,
) -> tuple[list[Alert], int]:
    conditions = [Alert.resolved_at.is_(None)]
    if alert_type is not None:
        conditions.append(Alert.alert_type == alert_type)
    if severity is not None:
        conditions.append(Alert.severity == severity)
    if train_id is not None:
        conditions.append(Alert.train_id == train_id)
    if section_id is not None:
        conditions.append(Alert.section_id == section_id)
    if station_id is not None:
        conditions.append(Alert.station_id == station_id)

    count_stmt = select(func.count()).select_from(Alert)
    list_stmt = select(Alert).order_by(Alert.created_at.desc())
    for condition in conditions:
        count_stmt = count_stmt.where(condition)
        list_stmt = list_stmt.where(condition)
    list_stmt = list_stmt.offset(offset).limit(limit)

    total = (await session.execute(count_stmt)).scalar_one()
    items = list((await session.execute(list_stmt)).scalars().all())
    return items, total


async def delete_by_fingerprint_prefix(session: AsyncSession, prefix: str) -> int:
    """Test/dev helper: remove alerts whose fingerprint starts with `prefix`. Not used
    in production code paths.
    """
    result = await session.execute(
        select(Alert).where(Alert.alert_metadata["fingerprint"].astext.like(f"{prefix}%"))
    )
    alerts = list(result.scalars().all())
    for alert in alerts:
        await session.delete(alert)
    return len(alerts)
