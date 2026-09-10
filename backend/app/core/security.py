"""Administrative authentication and audit logging for sensitive system operations."""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import threading
from typing import Any
import uuid

from fastapi import Header, HTTPException, status

from app.core.config import get_settings
from app.monitoring.schemas import AuditLogEntry

logger = logging.getLogger(__name__)


def verify_admin_key(x_admin_api_key: str | None = Header(default=None)) -> str:
    """Verify administrator API key for sensitive operations (promotion, rollback, overrides).

    - In development mode: if ADMIN_API_KEY is not configured, allows local requests
      with an informational warning.
    - In production mode: strictly requires a valid X-Admin-API-Key header.
    """
    settings = get_settings()

    if not settings.ADMIN_AUTH_ENABLED:
        return "unauthenticated-dev"

    configured_key = settings.ADMIN_API_KEY

    # Development convenience when no key is explicitly set
    if not configured_key:
        if settings.ENVIRONMENT.lower() == "development":
            logger.debug("Admin authentication bypassed in local development (ADMIN_API_KEY unset)")
            return "local-developer"
        else:
            logger.error("Production refused admin operation: ADMIN_API_KEY is not configured")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin operations disabled: ADMIN_API_KEY not configured in production",
            )

    if not x_admin_api_key or x_admin_api_key.strip() != configured_key.strip():
        logger.warning("Unauthorized admin access attempt with invalid or missing API key")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Admin-API-Key header",
        )

    return "admin-user"


class AuditLogger:
    """Thread-safe persistent audit logger for sensitive system and MLOps actions."""

    def __init__(self, log_path: str = "./data/audit_log.jsonl") -> None:
        self.log_file = Path(log_path)
        self._lock = threading.Lock()
        self._recent_entries: list[AuditLogEntry] = []
        self._load_recent()

    def _load_recent(self) -> None:
        if self.log_file.exists():
            try:
                lines = self.log_file.read_text(encoding="utf-8").strip().splitlines()
                for line in lines[-100:]:
                    if line.strip():
                        data = json.loads(line)
                        self._recent_entries.append(AuditLogEntry.model_validate(data))
            except Exception as exc:
                logger.warning("Could not read existing audit log: %s", exc)

    def record_event(
        self,
        action: str,
        actor: str,
        previous_value: str | None = None,
        new_value: str | None = None,
        reason: str | None = None,
    ) -> AuditLogEntry:
        """Record an administrative or operational mutation event."""
        entry = AuditLogEntry(
            id=str(uuid.uuid4()),
            action=action,
            actor=actor,
            timestamp=datetime.now(timezone.utc),
            previous_value=previous_value,
            new_value=new_value,
            reason=reason,
        )

        with self._lock:
            self._recent_entries.append(entry)
            try:
                self.log_file.parent.mkdir(parents=True, exist_ok=True)
                with self.log_file.open("a", encoding="utf-8") as f:
                    f.write(entry.model_dump_json() + "\n")
            except Exception as exc:
                logger.error("Failed to append to audit log: %s", exc)

        logger.info(
            "AUDIT EVENT [%s] by %s: %s -> %s (reason: %s)",
            action,
            actor,
            previous_value,
            new_value,
            reason,
        )
        return entry

    def get_entries(self, limit: int = 50) -> list[AuditLogEntry]:
        with self._lock:
            return list(reversed(self._recent_entries[-limit:]))


# Shared singleton audit logger
audit_logger = AuditLogger()
