import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import httpx
import pytest
from alembic.script import ScriptDirectory
from sqlalchemy.exc import IntegrityError

from tests.helpers import AUTH, db_execute, db_rows, db_scalar

BACKEND_DIR = Path(__file__).resolve().parent.parent


async def _boot():
    """Run the app's startup the way uvicorn does; returns only if it booted."""
    import main

    async with main.lifespan(main.app):
        pass


# --- DEV_MODE boot guard ------------------------------------------------------

async def test_lifespan_refuses_dev_mode_with_a_public_origin(monkeypatch):
    import main
    from services.redis import redis_service

    monkeypatch.setattr(main.settings, "DEV_MODE", True)
    monkeypatch.setattr(
        main.settings, "CORS_ORIGINS", "http://localhost:3000, https://morlana.example.com"
    )

    with pytest.raises(RuntimeError) as exc_info:
        await _boot()

    message = str(exc_info.value)
    assert message.startswith("DEV_MODE is enabled while CORS_ORIGINS points at non-local origins")
    assert "https://morlana.example.com" in message
    assert "http://localhost:3000" not in message
    # It stopped before touching anything else.
    assert redis_service._client is None


async def test_dev_mode_with_local_origins_boots_and_serves_the_dev_account(monkeypatch):
    import main

    monkeypatch.setattr(main.settings, "DEV_MODE", True)
    monkeypatch.setattr(main.settings, "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:5173")

    async with main.lifespan(main.app):
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # This is what the guard protects: without a signature the caller IS the dev account.
            unsigned = await client.get(f"{AUTH}/me")
            assert unsigned.status_code == 404
            assert unsigned.json()["detail"] == "User not found"

            monkeypatch.setattr(main.settings, "DEV_MODE", False)
            assert (await client.get(f"{AUTH}/me")).status_code == 401


# --- schema revision guard ----------------------------------------------------

async def test_lifespan_boots_at_head_and_serves_health(client):
    from database import get_head_revision

    resp = await client.get("/health")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert await db_scalar("SELECT version_num FROM alembic_version") == get_head_revision()


async def test_lifespan_refuses_a_database_behind_head():
    from database import ALEMBIC_DIR, get_head_revision

    head = get_head_revision()
    previous = ScriptDirectory(str(ALEMBIC_DIR)).get_revision(head).down_revision
    assert previous and previous != head

    await db_execute("UPDATE alembic_version SET version_num = :rev", rev=previous)
    try:
        with pytest.raises(RuntimeError) as exc_info:
            await _boot()
    finally:
        await db_execute("UPDATE alembic_version SET version_num = :rev", rev=head)

    assert str(exc_info.value) == (
        f"Database schema is at {previous}, expected {head}. Run: alembic upgrade head"
    )
    await _boot()  # back at head, it boots again


async def test_lifespan_refuses_an_unversioned_database():
    from database import get_head_revision

    await db_execute("ALTER TABLE alembic_version RENAME TO alembic_version_hidden")
    try:
        with pytest.raises(RuntimeError) as exc_info:
            await _boot()
    finally:
        await db_execute("ALTER TABLE alembic_version_hidden RENAME TO alembic_version")

    assert str(exc_info.value) == (
        f"Database schema is at None, expected {get_head_revision()}. Run: alembic upgrade head"
    )


def test_models_match_the_migrated_schema():
    """`alembic check`: the migrations alone produce exactly what the models describe."""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "check"],
        cwd=BACKEND_DIR,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "No new upgrade operations detected" in result.stdout + result.stderr


async def test_database_rejects_a_duplicate_cycle_number():
    session_id = str(uuid.uuid4())
    await db_execute("INSERT INTO users (telegram_id, real_name) VALUES (3001, 'Алиса')")
    await db_execute("INSERT INTO tarot_sessions (id, user_id) VALUES (:id, 3001)", id=session_id)
    insert_cycle = (
        "INSERT INTO reading_cycles (session_id, cycle_number, question, card_id, interpretation) "
        "VALUES (:id, 1, 'Вопрос', 7, 'Ответ')"
    )
    await db_execute(insert_cycle, id=session_id)

    with pytest.raises(IntegrityError, match="uq_reading_cycles_session_cycle"):
        await db_execute(insert_cycle, id=session_id)

    assert await db_scalar("SELECT count(*) FROM reading_cycles") == 1
    # Server defaults fill everything the INSERT left out, the stage-2 columns too.
    assert await db_scalar("SELECT status FROM tarot_sessions") == "active"
    assert await db_scalar("SELECT free_requests_left FROM users") == 3
    assert await db_rows("SELECT spread_id, deck_id FROM tarot_sessions") == [
        {"spread_id": "one-card", "deck_id": "rider-waite"}
    ]


async def test_a_cycle_can_be_stored_with_cards_and_no_legacy_number():
    """Stage 2: `cards` is the truth and card_id is nullable, for decks it cannot number."""
    session_id = str(uuid.uuid4())
    cards = [
        {
            "deck_id": "rider-waite",
            "card_id": "maj00",
            "position": "main",
            "reversed": False,
            "name": "Шут",
            "image": "/decks/rider-waite/maj00.jpg",
        }
    ]
    await db_execute("INSERT INTO users (telegram_id, real_name) VALUES (3002, 'Алиса')")
    await db_execute("INSERT INTO tarot_sessions (id, user_id) VALUES (:id, 3002)", id=session_id)

    await db_execute(
        "INSERT INTO reading_cycles (session_id, cycle_number, question, cards, interpretation) "
        "VALUES (:id, 1, 'Вопрос', CAST(:cards AS jsonb), 'Ответ')",
        id=session_id,
        cards=json.dumps(cards),
    )

    assert await db_rows("SELECT cards, card_id, card_name FROM reading_cycles") == [
        {"cards": cards, "card_id": None, "card_name": None}
    ]
