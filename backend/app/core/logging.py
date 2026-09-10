import logging
import sys
from datetime import datetime, timezone
from typing import Any

from app.core.config import get_settings


class JSONFormatter(logging.Formatter):
    """Renders log records as single-line JSON so they stay parseable in aggregation tools."""

    def format(self, record: logging.LogRecord) -> str:
        import json

        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Extra structured fields attached via `logger.info(..., extra={...})`.
        reserved = logging.LogRecord("", 0, "", 0, "", None, None).__dict__.keys()
        for key, value in record.__dict__.items():
            if key not in reserved and key not in payload:
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def setup_logging() -> None:
    settings = get_settings()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(settings.LOG_LEVEL.upper())

    # Keep noisy third-party loggers at a sane level regardless of app LOG_LEVEL.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
