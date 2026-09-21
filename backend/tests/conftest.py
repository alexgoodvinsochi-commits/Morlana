"""Test harness: real Postgres + real Redis, the real app, a stubbed LLM.

The environment is set here, BEFORE anything imports `config`, so the app can
only ever see the test database and the test Redis db:

* DATABASE_URL: host/credentials come from TEST_DATABASE_URL or DATABASE_URL,
  the database name is always forced to `morlana_test`;
* REDIS_URL: host comes from TEST_REDIS_URL or REDIS_URL, the db is always 15.
"""
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy.engine import make_url

TEST_DB_NAME = "morlana_test"
TEST_REDIS_DB = 15
BACKEND_DIR = Path(__file__).resolve().parent.parent


def _test_database_url() -> str:
    base = (
        os.environ.get("TEST_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or "postgresql+psycopg://user:pass@localhost:5432/postgres"
    )
    return make_url(base).set(database=TEST_DB_NAME).render_as_string(hide_password=False)


def _test_redis_url() -> str:
    base = os.environ.get("TEST_REDIS_URL") or os.environ.get("REDIS_URL") or "redis://localhost:6379/0"
    return urlunsplit(urlsplit(base)._replace(path=f"/{TEST_REDIS_DB}"))


os.environ.update(
    {
        "DATABASE_URL": _test_database_url(),
        "REDIS_URL": _test_redis_url(),
        "TELEGRAM_BOT_TOKEN": "123456:TEST",
        "DEV_MODE": "false",
        "CORS_ORIGINS": "http://localhost:3000",
        "LLM_API_KEY": "",
        "INIT_DATA_MAX_AGE": "86400",
        "HISTORY_LIMIT_FREE": "3",
        "HISTORY_LIMIT_PREMIUM": "50",
    }
)

import httpx
import psycopg
import pytest
import pytest_asyncio
import redis.asyncio as aioredis
from sqlalchemy import text

from tests.helpers import TEST_BOT_TOKEN, sign_init_data  # noqa: F401  (re-exported for the tests)

assert os.environ["TELEGRAM_BOT_TOKEN"] == TEST_BOT_TOKEN


def _pg_connect(dbname: str) -> psycopg.Connection:
    url = make_url(os.environ["DATABASE_URL"])
    return psycopg.connect(
        host=url.host,
        port=url.port or 5432,
        user=url.username,
        password=url.password,
        dbname=dbname,
        autocommit=True,
    )


@pytest.fixture(scope="session", autouse=True)
def migrated_db():
    """A fresh `morlana_test` built by `alembic upgrade head`, the only schema path."""
    assert make_url(os.environ["DATABASE_URL"]).database == TEST_DB_NAME

    with _pg_connect("postgres") as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB_NAME,)
        ).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')

    with _pg_connect(TEST_DB_NAME) as conn:
        # Never drop anything outside the test database.
        assert conn.execute("SELECT current_database()").fetchone()[0] == TEST_DB_NAME
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")

    # A subprocess, not an in-process call: alembic/env.py runs fileConfig(),
    # which would disable the loggers of the already imported app.
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(f"alembic upgrade head failed:\n{result.stdout}\n{result.stderr}", pytrace=False)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _dispose_engine(migrated_db):
    yield
    from database import engine

    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def clean_state(migrated_db):
    """Every test starts with empty tables and an empty Redis db 15."""
    from database import engine

    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
            )
        )
        tables = ", ".join(f'"{row[0]}"' for row in result)
        if tables:
            await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))

    redis_url = os.environ["REDIS_URL"]
    assert redis_url.endswith(f"/{TEST_REDIS_DB}")
    redis_client = aioredis.from_url(redis_url)
    try:
        await redis_client.flushdb()
    finally:
        await redis_client.aclose()


@pytest.fixture(autouse=True)
def rate_limits_off():
    """slowapi is off by default; the rate-limit test turns it on via `rate_limits_on`."""
    from rate_limiter import limiter

    limiter.enabled = False
    yield
    limiter.enabled = False


@pytest.fixture
def rate_limits_on(rate_limits_off):
    from rate_limiter import limiter

    limiter.reset()
    limiter.enabled = True
    yield limiter
    limiter.enabled = False
    limiter.reset()


class LLMStub:
    """Stands in for services.llm.stream_prediction inside routes.reading."""

    def __init__(self):
        self.chunks = ["Карта говорит: ", "всё будет ", "хорошо."]
        self.fail = False
        self.calls: list[dict] = []

    @property
    def full_text(self) -> str:
        return "".join(self.chunks)

    async def stream(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            # Partial output first: the upstream dies in the middle of a stream.
            yield self.chunks[0]
            raise RuntimeError("LLM upstream failure (test stub)")
        for chunk in self.chunks:
            yield chunk


@pytest.fixture(autouse=True)
def llm(monkeypatch) -> LLMStub:
    """No test ever reaches a real LLM. Set `llm.fail = True` for the failing variant."""
    import routes.reading

    stub = LLMStub()
    monkeypatch.setattr(routes.reading, "stream_prediction", stub.stream)
    return stub


@pytest_asyncio.fixture
async def client(clean_state):
    """HTTP client over the real ASGI app with its lifespan running."""
    import main

    async with main.lifespan(main.app):
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
            yield http_client
