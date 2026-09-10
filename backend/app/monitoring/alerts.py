"""Operational alert generation and deterministic fingerprint deduplication."""

from datetime import datetime, timezone
import hashlib
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert
from app.models.enums import AlertSeverity, AlertType

logger = logging.getLogger(__name__)


def compute_alert_fingerprint(alert_type: AlertType, resource_key: str, date_bucket: str) -> str:
    """Deterministic hash fingerprint for deduplication."""
    raw = f"{alert_type.value}:{resource_key}:{date_bucket}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def create_or_update_operational_alert(
    session: AsyncSession,
    alert_type: AlertType,
    severity: AlertSeverity,
    title: str,
    description: str,
    resource_key: str = "system",
    metadata: dict[str, Any] | None = None,
) -> Alert:
    """Create a new operational alert or update an existing one within the current hour/day bucket."""
    now = datetime.now(timezone.utc)
    date_bucket = now.strftime("%Y-%m-%d-%H")  # Hourly deduplication window
    fingerprint = compute_alert_fingerprint(alert_type, resource_key, date_bucket)

    meta = {
        **(metadata or {}),
        "fingerprint": fingerprint,
        "resource_key": resource_key,
        "last_seen_at": now.isoformat(),
    }

    # Search for an existing unresolved alert with this fingerprint
    stmt = (
        select(Alert)
        .where(Alert.alert_type == alert_type)
        .where(Alert.resolved_at.is_(None))
        .order_by(Alert.created_at.desc())
        .limit(10)
    )
    existing_alerts = (await session.execute(stmt)).scalars().all()

    for alt in existing_alerts:
        existing_meta = alt.alert_metadata or {}
        if existing_meta.get("fingerprint") == fingerprint:
            # Deduplicated: update metadata and title without inserting duplicate row
            alt.title = title
            alt.description = description
            alt.alert_metadata = meta
            await session.commit()
            logger.debug("Deduplicated operational alert %s [fp=%s]", alert_type.value, fingerprint)
            return alt

    # Insert new alert
    new_alert = Alert(
        alert_type=alert_type,
        severity=severity,
        title=title,
        description=description,
        alert_metadata=meta,
    )
    session.add(new_alert)
    await session.commit()
    logger.info("Created operational alert: %s (%s) - %s", alert_type.value, severity.value, title)
    return new_alert
