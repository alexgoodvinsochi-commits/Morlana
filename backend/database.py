from pathlib import Path

from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

ALEMBIC_DIR = Path(__file__).resolve().parent / "alembic"


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        yield session


def get_head_revision() -> str | None:
    """Head of the migration scripts shipped with this code."""
    return ScriptDirectory(str(ALEMBIC_DIR)).get_current_head()


async def get_schema_revision() -> str | None:
    """Revision the database is stamped with, None when it is unversioned."""
    async with engine.connect() as conn:
        if await conn.scalar(text("SELECT to_regclass('alembic_version')")) is None:
            return None
        result = await conn.execute(text("SELECT version_num FROM alembic_version"))
        versions = sorted(row[0] for row in result)
    return ", ".join(versions) or None


async def check_schema_revision() -> str:
    """Alembic is the only schema path: refuse to run against any other revision."""
    head = get_head_revision()
    current = await get_schema_revision()
    if head is None or current != head:
        raise RuntimeError(
            f"Database schema is at {current}, expected {head}. Run: alembic upgrade head"
        )
    return head
