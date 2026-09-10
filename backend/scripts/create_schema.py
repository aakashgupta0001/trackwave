"""One-time idempotent schema bootstrap for a fresh database.

Earlier phases created the schema via `Base.metadata.create_all()` directly rather
than an Alembic migration (see alembic/versions/0007_uncertainty_confidence.py's
docstring) — this script reproduces that step for a fresh deployment target.
`create_all()` only creates tables that don't already exist, so this is safe to
run against a database that's already been bootstrapped.
"""
import asyncio

import app.models  # noqa: F401  registers every model on Base.metadata
from app.db.base import Base
from app.db.session import engine


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


if __name__ == "__main__":
    asyncio.run(main())
