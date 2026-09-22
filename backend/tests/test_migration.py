"""The stage-2 migration f4a5b6c7d8e9 on rows that already exist.

It runs against `morlana_test` only: the fixtures force that database, and every
test puts the schema back at head before it returns.
"""
import contextlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from tests.helpers import READING, db_execute, db_rows, register, run_cycle, start_reading

BACKEND_DIR = Path(__file__).resolve().parent.parent
PREVIOUS_REVISION = "e3f4a5b6c7d8"
ALICE = 5001


def _alembic(*args: str) -> None:
    from sqlalchemy.engine import make_url

    # These tests run DDL, so never let them point anywhere but the test database.
    assert make_url(os.environ["DATABASE_URL"]).database == "morlana_test"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(f"alembic {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}", pytrace=False)


@contextlib.asynccontextmanager
async def schema_before_stage_2():
    """The test database one revision back, always restored to head afterwards.

    The engine is disposed around the DDL: a pooled connection would keep a
    cached plan for a table whose columns are about to change.
    """
    from database import engine

    await engine.dispose()
    _alembic("downgrade", PREVIOUS_REVISION)
    try:
        yield
    finally:
        await engine.dispose()
        _alembic("upgrade", "head")


async def _column(table: str, column: str) -> dict | None:
    rows = await db_rows(
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_name = :table AND column_name = :column",
        table=table,
        column=column,
    )
    return rows[0] if rows else None


async def test_the_upgrade_backfills_the_cards_of_rows_written_before_stage_2(client):
    headers = await register(client, ALICE)
    session_id = str(uuid.uuid4())

    async with schema_before_stage_2():
        # The schema the previous version wrote into.
        assert await _column("reading_cycles", "cards") is None
        assert await _column("tarot_sessions", "spread_id") is None
        assert (await _column("reading_cycles", "card_id"))["is_nullable"] == "NO"

        await db_execute(
            "INSERT INTO tarot_sessions (id, user_id, status, cycle_count, synthesis) "
            "VALUES (:id, :user_id, 'archived', 3, 'Общий вывод')",
            id=session_id,
            user_id=ALICE,
        )
        await db_execute(
            "INSERT INTO reading_cycles (session_id, cycle_number, question, card_id, card_name, interpretation) "
            "VALUES (:id, 1, 'Первый', 1, NULL, 'Ответ 1'), "
            "(:id, 2, 'Второй', 57, 'Имя из старой колонки', 'Ответ 2'), "
            "(:id, 3, 'Третий', 78, NULL, 'Ответ 3')",
            id=session_id,
        )

    rows = await db_rows(
        "SELECT cycle_number, cards, card_id, card_name FROM reading_cycles ORDER BY cycle_number"
    )
    assert [row["cards"] for row in rows] == [
        [{
            "deck_id": "rider-waite", "card_id": "maj00", "position": "main",
            "reversed": False, "name": "Шут", "image": "/decks/rider-waite/maj00.jpg",
        }],
        [{
            "deck_id": "rider-waite", "card_id": "swords07", "position": "main",
            "reversed": False, "name": "Имя из старой колонки",
            "image": "/decks/rider-waite/swords07.jpg",
        }],
        [{
            "deck_id": "rider-waite", "card_id": "wands14", "position": "main",
            "reversed": False, "name": "Король Жезлы", "image": "/decks/rider-waite/wands14.jpg",
        }],
    ]
    # The old columns are kept untouched, and card_id is nullable from now on.
    assert [(row["card_id"], row["card_name"]) for row in rows] == [
        (1, None), (57, "Имя из старой колонки"), (78, None)
    ]
    assert (await _column("reading_cycles", "card_id"))["is_nullable"] == "YES"
    # An existing reading gets the defaults: it was a one-card Rider-Waite reading.
    assert await db_rows("SELECT spread_id, deck_id FROM tarot_sessions") == [
        {"spread_id": "one-card", "deck_id": "rider-waite"}
    ]

    # And that is exactly what /history serves, with no fallback involved.
    history = (await client.get(f"{READING}/history", headers=headers)).json()["readings"]
    assert [cycle["cards"][0]["card_id"] for cycle in history[0]["cycles"]] == [
        "maj00", "swords07", "wands14"
    ]
    assert [cycle["cards"][0]["name"] for cycle in history[0]["cycles"]] == [
        "Шут", "Имя из старой колонки", "Король Жезлы"
    ]


async def test_the_downgrade_rebuilds_the_legacy_number_from_the_cards(client, llm):
    from services.decks import deck_registry, legacy_number

    headers = await register(client, ALICE)
    session_id = await start_reading(client, headers)
    await run_cycle(client, headers, session_id, "Вопрос")
    card_id = (await db_rows("SELECT cards FROM reading_cycles"))[0]["cards"][0]["card_id"]
    # A row that only has `cards`: what a writer after stage 2 could leave behind.
    await db_execute("UPDATE reading_cycles SET card_id = NULL, card_name = NULL")

    async with schema_before_stage_2():
        assert await db_rows("SELECT card_id, card_name FROM reading_cycles") == [
            {"card_id": legacy_number(card_id), "card_name": deck_registry.default.card_name(card_id)}
        ]
        # The rollback is complete: the JSONB column is gone and card_id is NOT NULL again.
        assert await _column("reading_cycles", "cards") is None
        assert (await _column("reading_cycles", "card_id"))["is_nullable"] == "NO"
        assert await _column("tarot_sessions", "deck_id") is None


async def test_the_downgrade_keeps_card_id_nullable_when_a_card_has_no_legacy_number(client):
    headers = await register(client, ALICE)
    session_id = await start_reading(client, headers)
    await db_execute(
        "INSERT INTO reading_cycles (session_id, cycle_number, question, cards, interpretation) "
        "VALUES (:id, 1, 'Вопрос', CAST(:cards AS jsonb), 'Ответ')",
        id=session_id,
        cards=json.dumps(
            [{
                "deck_id": "oracle", "card_id": "oracle01", "position": "main",
                "reversed": False, "name": "Оракул", "image": "/decks/oracle/oracle01.jpg",
            }]
        ),
    )
    assert headers  # the reading belongs to a real user

    async with schema_before_stage_2():
        # The 1..78 numbering cannot express this card, so the rollback leaves the
        # column nullable instead of failing outright. The name is not numbered,
        # so it is rescued anyway instead of being dropped with `cards`.
        assert await db_rows("SELECT card_id, card_name FROM reading_cycles") == [
            {"card_id": None, "card_name": "Оракул"}
        ]
        assert (await _column("reading_cycles", "card_id"))["is_nullable"] == "YES"
