import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.session import AsyncSessionLocal, check_database_connection, engine
from app.main import app


@pytest.fixture(autouse=True)
def isolate_test_provider_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings
    settings = get_settings()
    monkeypatch.setattr(settings, "PRIMARY_DATA_PROVIDER", "SIMULATOR")
    monkeypatch.setattr(settings, "FALLBACK_DATA_PROVIDER", "")
    monkeypatch.setattr(settings, "RAILRADAR_ENABLED", False)


@pytest.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def require_db() -> None:
    """Skip DB-dependent tests with a clear message rather than failing noisily
    when no PostgreSQL instance is reachable (e.g. Docker not running locally).
    """
    if not await check_database_connection():
        pytest.skip("PostgreSQL is not reachable — start it (e.g. `docker compose up postgres`) to run this test.")


@pytest.fixture
async def db_session(require_db: None) -> AsyncSession:
    """A session bound to a transaction that's rolled back after the test, so DB
    tests never leave data behind — regardless of whether the seed script has run.
    """
    async with engine.connect() as connection:
        await connection.begin()
        session_factory = async_sessionmaker(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        async with session_factory() as session:
            yield session
        await connection.rollback()


@pytest.fixture
async def real_session(require_db: None) -> AsyncSession:
    """A normal, committing session — for tests that verify actually-persisted state
    (e.g. seed script idempotency), as opposed to isolated per-test scratch data.
    """
    async with AsyncSessionLocal() as session:
        yield session


@pytest.fixture
async def seeded_client(require_db: None, client: AsyncClient) -> AsyncClient:
    """An HTTP client for API tests that read the Phase 2 sample railway network.
    Runs the (idempotent) seed script first so these tests work against a fresh
    database too, not just one a developer happened to seed manually.
    """
    from scripts.seed import run_seed

    await run_seed()
    return client


@pytest.fixture
async def seeded_session(require_db: None, real_session: AsyncSession) -> AsyncSession:
    """Like `real_session`, but guarantees the (idempotent) seed script has run first —
    for non-HTTP tests (provider adapters, ingestion) that still need the sample network.
    """
    from scripts.seed import run_seed

    await run_seed()
    return real_session


@pytest.fixture
async def eta_client(seeded_client: AsyncClient) -> AsyncClient:
    """Alias used by the Phase 5/6 ETA API test modules."""
    return seeded_client
