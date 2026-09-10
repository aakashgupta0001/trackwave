import asyncio
import logging
import sys
from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

logger = logging.getLogger(__name__)

if sys.platform == "win32":
    # psycopg's async mode cannot run on Windows' default ProactorEventLoop.
    # Must be set before any event loop is created (module import time qualifies).
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

settings = get_settings()

engine = create_async_engine(settings.DATABASE_URL, pool_pre_ping=True, echo=False)

AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a request-scoped database session."""
    async with AsyncSessionLocal() as session:
        yield session


async def check_database_connection() -> bool:
    """Used by the health endpoint. Never raises — returns False on any failure."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.warning("Database connectivity check failed", exc_info=True)
        return False
