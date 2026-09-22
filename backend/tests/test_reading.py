import uuid

import pytest

from tests.helpers import (
    DEFAULT_DECK_ID,
    DEFAULT_SPREAD_ID,
    READING,
    asked_question,
    db_execute,
    db_rows,
    db_scalar,
    delete_reading_document,
    get_state,
    interpret,
    reading_document,
    reading_key,
    register,
    run_cycle,
    start_reading,
    synthesize,
    system_prompt,
    write_reading_document,
)

ALICE = 2001
BOB = 2002

WAITING = "WAITING"
QUESTION_ASKED = "QUESTION_ASKED"
CARDS_DRAWN = "CARDS_DRAWN"
INTERPRETATION = "INTERPRETATION"
READY = "READY"
COMPLETED = "COMPLETED"

DRAWN_CARD_FIELDS = {"deck_id", "card_id", "position", "reversed", "name", "image"}


def assert_drawn_card(card: dict, *, deck_id: str = DEFAULT_DECK_ID, position: str = "main") -> None:
    """Every card the API hands out is a full DrawnCard, ready to render."""
    assert set(card) == DRAWN_CARD_FIELDS
    assert card["deck_id"] == deck_id
    assert card["position"] == position
    assert card["reversed"] is False  # one-card does not allow reversed cards
    assert card["name"]
    assert card["image"] == f"/decks/{deck_id}/{card['card_id']}.jpg"


# --- the happy path -----------------------------------------------------------

async def test_full_cycle_reaches_ready_and_persists_the_cycle(client, llm):
    from services.decks import legacy_number

    headers = await register(client, ALICE)

    started = await client.post(f"{READING}/start", json={}, headers=headers)
    assert started.status_code == 200
    reading = started.json()
    session_id = reading["session_id"]
    assert reading["state"] == WAITING
    assert (reading["spread_id"], reading["deck_id"]) == (DEFAULT_SPREAD_ID, DEFAULT_DECK_ID)
    assert (reading["current_question"], reading["current_cards"], reading["cycles"]) == (None, [], [])

    asked = await client.post(
        f"{READING}/ask", json={"session_id": session_id, "question": "Что меня ждёт?"}, headers=headers
    )
    assert asked.status_code == 200
    # One request per action: /ask answers with the whole reading, no /state needed.
    assert asked.json()["session_id"] == session_id
    assert asked.json()["state"] == QUESTION_ASKED
    assert asked.json()["current_question"] == "Что меня ждёт?"
    assert asked.json()["current_cards"] == []

    drawn = await client.post(f"{READING}/draw", json={"session_id": session_id}, headers=headers)
    assert drawn.status_code == 200
    assert drawn.json()["state"] == CARDS_DRAWN
    cards = drawn.json()["current_cards"]
    assert len(cards) == 1
    assert_drawn_card(cards[0])

    events = await interpret(client, headers, session_id)
    assert events == [{"text": chunk} for chunk in llm.chunks] + [{"cleaned": llm.full_text}, "[DONE]"]
    # The LLM got the drawn card and the question, not something else.
    call = llm.calls[0]
    assert asked_question(call) == "Что меня ждёт?"
    assert f"Главная карта: {cards[0]['name']}" in system_prompt(call)
    assert call["is_premium"] is False
    # The model parameters come from the spread, not from the route.
    assert (call["spread"].id, call["spread"].max_tokens, call["spread"].temperature) == (
        DEFAULT_SPREAD_ID, 2048, 0.7,
    )

    state = await get_state(client, headers, session_id)
    assert state["state"] == READY
    assert state["cycle_count"] == 1
    assert state["max_cycles"] == 6
    assert state["current_cards"] == cards
    assert state["cycles"] == [
        {"cycle_number": 1, "question": "Что меня ждёт?", "cards": cards, "answer": llm.full_text}
    ]

    cycles = await db_rows("SELECT * FROM reading_cycles")
    assert len(cycles) == 1
    assert cycles[0]["session_id"] == session_id
    assert cycles[0]["cycle_number"] == 1
    assert cycles[0]["question"] == "Что меня ждёт?"
    assert cycles[0]["cards"] == cards
    # The legacy single-card columns are still written, from the first card.
    assert cycles[0]["card_id"] == legacy_number(cards[0]["card_id"])
    assert cycles[0]["card_name"] == cards[0]["name"]
    assert cycles[0]["interpretation"] == llm.full_text

    sessions = await db_rows(
        "SELECT id, user_id, status, cycle_count, synthesis, spread_id, deck_id FROM tarot_sessions"
    )
    assert sessions == [
        {
            "id": session_id,
            "user_id": ALICE,
            "status": "active",
            "cycle_count": 1,
            "synthesis": None,
            "spread_id": DEFAULT_SPREAD_ID,
            "deck_id": DEFAULT_DECK_ID,
        }
    ]


async def test_second_cycle_and_synthesis_archive_the_reading(client, llm):
    headers = await register(client, ALICE)
    session_id = await start_reading(client, headers)
    await run_cycle(client, headers, session_id, "Первый вопрос")

    next_cycle = await client.post(f"{READING}/next", json={"session_id": session_id}, headers=headers)
    assert next_cycle.status_code == 200
    assert next_cycle.json()["state"] == WAITING
    # The new cycle starts empty, and the finished one is kept.
    assert next_cycle.json()["current_question"] is None
    assert next_cycle.json()["current_cards"] == []
    assert [cycle["cycle_number"] for cycle in next_cycle.json()["cycles"]] == [1]
    await run_cycle(client, headers, session_id, "Второй вопрос")

    events = await synthesize(client, headers, session_id)
    assert events[-2:] == [{"cleaned": llm.full_text}, "[DONE]"]

    assert (await get_state(client, headers, session_id))["state"] == COMPLETED
    session = (await db_rows("SELECT status, cycle_count, synthesis FROM tarot_sessions"))[0]
    assert session == {"status": "archived", "cycle_count": 2, "synthesis": llm.full_text}
    numbers = await db_rows("SELECT cycle_number, question FROM reading_cycles ORDER BY cycle_number")
    assert numbers == [
        {"cycle_number": 1, "question": "Первый вопрос"},
        {"cycle_number": 2, "question": "Второй вопрос"},
    ]
    # The synthesis prompt was built from both cycles, with the spread's wording.
    synthesis_prompt = system_prompt(llm.calls[-1])
    assert "Первый вопрос" in synthesis_prompt and "Второй вопрос" in synthesis_prompt
    assert llm.calls[-1]["spread"].synthesis_prompt in synthesis_prompt

    # A finished reading accepts no further cycles.
    after_end = await client.post(f"{READING}/next", json={"session_id": session_id}, headers=headers)
    assert after_end.status_code == 409
    assert after_end.json()["detail"] == f"Invalid state transition: {COMPLETED} -> {WAITING}"


async def test_sixth_cycle_completes_the_reading_automatically(client):
    headers = await register(client, ALICE)
    session_id = await start_reading(client, headers)
    body = {"session_id": session_id}

    for number in range(1, 7):
        await run_cycle(client, headers, session_id, f"Вопрос {number}")
        if number < 6:
            assert (await get_state(client, headers, session_id))["state"] == READY
            assert (await client.post(f"{READING}/next", json=body, headers=headers)).status_code == 200

    state = await get_state(client, headers, session_id)
    # The limit is the spread's max_cycles, not a constant of the state machine.
    assert (state["state"], state["cycle_count"], len(state["cycles"])) == (COMPLETED, 6, 6)
    assert state["max_cycles"] == 6
    seventh = await client.post(f"{READING}/next", json=body, headers=headers)
    assert seventh.status_code == 409

    # /synthesis accepts a reading that is already COMPLETED.
    await synthesize(client, headers, session_id)
    session = (await db_rows("SELECT status, cycle_count FROM tarot_sessions"))[0]
    assert session == {"status": "archived", "cycle_count": 6}
    numbers = await db_rows("SELECT cycle_number FROM reading_cycles ORDER BY cycle_number")
    assert [row["cycle_number"] for row in numbers] == [1, 2, 3, 4, 5, 6]


# --- the spread and the deck of a reading -------------------------------------

async def test_start_accepts_the_default_spread_and_deck_explicitly(client):
    headers = await register(client, ALICE)

    resp = await client.post(
        f"{READING}/start",
        json={"spread_id": DEFAULT_SPREAD_ID, "deck_id": DEFAULT_DECK_ID},
        headers=headers,
    )

    assert resp.status_code == 200
    reading = resp.json()
    assert (reading["spread_id"], reading["deck_id"]) == (DEFAULT_SPREAD_ID, DEFAULT_DECK_ID)
    # The choice is remembered in both stores, so every later call uses it.
    assert await db_rows("SELECT spread_id, deck_id FROM tarot_sessions") == [
        {"spread_id": DEFAULT_SPREAD_ID, "deck_id": DEFAULT_DECK_ID}
    ]
    document = await reading_document(reading["session_id"])
    assert (document["spread_id"], document["deck_id"]) == (DEFAULT_SPREAD_ID, DEFAULT_DECK_ID)


@pytest.mark.parametrize(
    "body, detail",
    [
        ({"spread_id": "celtic-cross"}, "Unknown spread"),
        ({"deck_id": "thoth"}, "Unknown deck"),
        ({"spread_id": "celtic-cross", "deck_id": "thoth"}, "Unknown spread"),
    ],
    ids=["unknown-spread", "unknown-deck", "both"],
)
async def test_start_with_an_unknown_spread_or_deck_is_400(client, body, detail):
    headers = await register(client, ALICE)
    running = await start_reading(client, headers)
    await run_cycle(client, headers, running, "Вопрос")

    resp = await client.post(f"{READING}/start", json=body, headers=headers)

    assert resp.status_code == 400
    assert resp.json()["detail"] == detail
    # Refused before any cleanup: the running reading is neither archived nor deleted.
    assert await db_rows("SELECT id, status FROM tarot_sessions") == [{"id": running, "status": "active"}]
    assert (await client.get(f"{READING}/active", headers=headers)).json()["session_id"] == running


async def test_start_refuses_a_spread_the_deck_is_too_small_for(client, two_card_spread, tiny_deck):
    """Both ids exist, but not together: a refusal here, not a 500 from /draw."""
    headers = await register(client, ALICE)

    resp = await client.post(
        f"{READING}/start", json={"spread_id": "two-card", "deck_id": "tiny"}, headers=headers
    )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "Spread needs more cards than the deck has"
    assert await db_rows("SELECT id FROM tarot_sessions") == []


async def test_a_two_card_spread_runs_end_to_end(client, llm, two_card_spread):
    from services.decks import legacy_number

    headers = await register(client, ALICE)
    started = await client.post(f"{READING}/start", json={"spread_id": "two-card"}, headers=headers)
    assert started.status_code == 200
    reading = started.json()
    session_id = reading["session_id"]
    assert (reading["spread_id"], reading["max_cycles"]) == ("two-card", 2)
    assert await db_scalar("SELECT spread_id FROM tarot_sessions") == "two-card"

    await client.post(
        f"{READING}/ask", json={"session_id": session_id, "question": "Как быть?"}, headers=headers
    )
    drawn = await client.post(f"{READING}/draw", json={"session_id": session_id}, headers=headers)
    cards = drawn.json()["current_cards"]

    # Two distinct cards, on the spread's positions, in the spread's order.
    assert [card["position"] for card in cards] == ["situation", "advice"]
    assert len({card["card_id"] for card in cards}) == 2
    for card in cards:
        assert set(card) == DRAWN_CARD_FIELDS
        assert card["deck_id"] == DEFAULT_DECK_ID
        assert isinstance(card["reversed"], bool)  # this spread allows reversed cards

    events = await interpret(client, headers, session_id)
    assert events[-2:] == [{"cleaned": llm.full_text}, "[DONE]"]
    prompt = system_prompt(llm.calls[0])
    for card, label in zip(cards, ["Ситуация", "Совет"]):
        line = f"{label}: {card['name']}" + (" (перевёрнута)" if card["reversed"] else "")
        assert line in prompt
    assert two_card_spread.system_prompt in prompt
    assert two_card_spread.aggregation_constraints[0] in prompt
    # max_tokens and temperature of THIS spread reach the provider call.
    assert (llm.calls[0]["spread"].max_tokens, llm.calls[0]["spread"].temperature) == (777, 0.25)

    # Both cards are stored; the legacy columns keep the first one.
    row = (await db_rows("SELECT cards, card_id, card_name FROM reading_cycles"))[0]
    assert row["cards"] == cards
    assert row["card_id"] == legacy_number(cards[0]["card_id"])
    assert row["card_name"] == cards[0]["name"]

    # max_cycles comes from the spread: the second cycle finishes the reading.
    assert (await client.post(f"{READING}/next", json={"session_id": session_id}, headers=headers)).status_code == 200
    await run_cycle(client, headers, session_id, "И что дальше?")
    state = await get_state(client, headers, session_id)
    assert (state["state"], state["cycle_count"]) == (COMPLETED, 2)
    assert [len(cycle["cards"]) for cycle in state["cycles"]] == [2, 2]

    await synthesize(client, headers, session_id)
    history = (await client.get(f"{READING}/history", headers=headers)).json()["readings"]
    assert [len(cycle["cards"]) for cycle in history[0]["cycles"]] == [2, 2]
    # History reports the spread that was used, not the default one.
    assert history[0]["spread_name"] == "two-card"


# --- ownership ----------------------------------------------------------------

async def test_another_users_session_is_404_everywhere(client):
    alice = await register(client, ALICE)
    bob = await register(client, BOB)
    session_id = await start_reading(client, alice)
    await run_cycle(client, alice, session_id, "Вопрос Алисы")
    body = {"session_id": session_id}

    responses = {
        "ask": await client.post(f"{READING}/ask", json={**body, "question": "Чужой вопрос"}, headers=bob),
        "next": await client.post(f"{READING}/next", json=body, headers=bob),
        "draw": await client.post(f"{READING}/draw", json=body, headers=bob),
        "interpret": await client.post(f"{READING}/interpret", json=body, headers=bob),
        "synthesis": await client.post(f"{READING}/synthesis", json=body, headers=bob),
        "state": await client.get(f"{READING}/state", params=body, headers=bob),
    }

    for name, resp in responses.items():
        assert resp.status_code == 404, name
        assert resp.json()["detail"] == "Reading not found", name

    # Nothing Bob sent touched Alice's reading.
    state = await get_state(client, alice, session_id)
    assert state["state"] == READY
    assert state["cycle_count"] == 1
    assert state["current_question"] == "Вопрос Алисы"
    assert await db_scalar("SELECT status FROM tarot_sessions WHERE id = :id", id=session_id) == "active"
    assert await db_scalar("SELECT count(*) FROM reading_cycles") == 1


@pytest.mark.parametrize("session_id", ["not-a-uuid", str(uuid.UUID(int=0))], ids=["garbage", "unknown-uuid"])
async def test_unknown_session_id_is_404(client, session_id):
    headers = await register(client, ALICE)

    resp = await client.post(f"{READING}/draw", json={"session_id": session_id}, headers=headers)

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Reading not found"


async def test_expired_redis_state_is_404(client):
    headers = await register(client, ALICE)
    session_id = await start_reading(client, headers)
    assert await delete_reading_document(session_id) == 1

    resp = await client.post(
        f"{READING}/ask", json={"session_id": session_id, "question": "Поздно?"}, headers=headers
    )

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Reading not found"


# --- how the live reading is stored -------------------------------------------

async def test_a_reading_is_one_redis_key_with_one_ttl(client):
    from services.reading import SESSION_TTL
    from services.redis import redis_service

    headers = await register(client, ALICE)
    session_id = await start_reading(client, headers)
    key = reading_key(session_id)

    assert await redis_service.client.keys("reading:*") == [key]
    assert await reading_document(session_id) == {
        "state": WAITING,
        "cycle": 0,
        "spread_id": DEFAULT_SPREAD_ID,
        "deck_id": DEFAULT_DECK_ID,
        "question": None,
        "cards": [],
        "cycle_data": [],
    }
    assert 0 < await redis_service.client.ttl(key) <= SESSION_TTL

    # Every write refreshes the one TTL, so no part of a reading can expire alone.
    await redis_service.client.expire(key, 60)
    await run_cycle(client, headers, session_id, "Вопрос")

    assert await redis_service.client.keys("reading:*") == [key]
    assert await redis_service.client.ttl(key) > 60
    document = await reading_document(session_id)
    assert document["state"] == READY
    assert document["cycle"] == 1
    assert document["question"] == "Вопрос"
    assert len(document["cards"]) == 1
    assert [entry["cycle_number"] for entry in document["cycle_data"]] == [1]
    assert set(document["cycle_data"][0]) == {"cycle_number", "question", "cards", "answer"}


async def test_a_reading_left_by_the_previous_version_is_not_found(client):
    """Five keys in the old format are not a reading any more: 404, not a 500."""
    from services.redis import redis_service

    headers = await register(client, ALICE)
    session_id = await start_reading(client, headers)
    await redis_service.client.delete(reading_key(session_id))
    for suffix, value in (
        ("state", "ОЖИДАНИЕ"),
        ("cycle", "0"),
        ("question", '"Вопрос"'),
        ("card", "7"),
        ("cycle_data", "[]"),
    ):
        await redis_service.client.set(f"reading:{session_id}:{suffix}", value)

    state = await client.get(f"{READING}/state", params={"session_id": session_id}, headers=headers)

    assert state.status_code == 404
    assert state.json()["detail"] == "Reading not found"
    # It cannot be resumed either: /active looks only for the new document.
    assert (await client.get(f"{READING}/active", headers=headers)).json() == {
        "session_id": None, "state": None
    }


async def test_a_reading_whose_spread_file_disappeared_falls_back_to_the_default(client, llm, caplog):
    """A deploy that drops a spread or deck file must not strand a reading in flight."""
    import logging

    headers = await register(client, ALICE)
    session_id = await start_reading(client, headers)
    document = await reading_document(session_id)
    document["spread_id"] = "retired-spread"
    document["deck_id"] = "retired-deck"
    await write_reading_document(session_id, document)

    with caplog.at_level(logging.WARNING, logger="routes.reading"):
        events = await run_cycle(client, headers, session_id, "Вопрос")

    assert events[-2:] == [{"cleaned": llm.full_text}, "[DONE]"]
    state = await get_state(client, headers, session_id)
    assert (state["state"], state["cycle_count"], state["max_cycles"]) == (READY, 1, 6)
    # The ids are reported as stored; only the behaviour falls back.
    assert (state["spread_id"], state["deck_id"]) == ("retired-spread", "retired-deck")
    assert_drawn_card(state["current_cards"][0])
    assert llm.calls[0]["spread"].id == DEFAULT_SPREAD_ID
    assert any("falling back" in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize(
    "document",
    [
        {"state": "ОЖИДАНИЕ", "cycle": 0},
        {"state": "SOMETHING_ELSE", "cycle": 0},
        {"cycle": 0},
        [],
    ],
    ids=["russian-state", "unknown-state", "no-state", "not-an-object"],
)
async def test_a_document_this_version_cannot_read_is_not_found(client, document):
    headers = await register(client, ALICE)
    session_id = await start_reading(client, headers)
    await write_reading_document(session_id, document)

    resp = await client.get(f"{READING}/state", params={"session_id": session_id}, headers=headers)

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Reading not found"


# --- the state machine --------------------------------------------------------

async def test_draw_in_wrong_state_is_409(client):
    headers = await register(client, ALICE)
    session_id = await start_reading(client, headers)

    resp = await client.post(f"{READING}/draw", json={"session_id": session_id}, headers=headers)

    assert resp.status_code == 409
    assert resp.json()["detail"] == f"Invalid state transition: {WAITING} -> {CARDS_DRAWN}"
    state = await get_state(client, headers, session_id)
    assert state["state"] == WAITING
    assert state["current_cards"] == []


async def test_wrong_state_calls_never_answer_500(client):
    headers = await register(client, ALICE)
    session_id = await start_reading(client, headers)
    body = {"session_id": session_id}

    # WAITING: only /ask is allowed.
    in_waiting = {
        "next": await client.post(f"{READING}/next", json=body, headers=headers),
        "synthesis": await client.post(f"{READING}/synthesis", json=body, headers=headers),
        "interpret": await client.post(f"{READING}/interpret", json=body, headers=headers),
    }
    assert in_waiting["next"].status_code == 409
    assert in_waiting["next"].json()["detail"] == f"Invalid state transition: {WAITING} -> {WAITING}"
    assert in_waiting["synthesis"].status_code == 409
    assert in_waiting["synthesis"].json()["detail"] == f"Invalid state transition: {WAITING} -> {COMPLETED}"
    assert in_waiting["interpret"].status_code == 400
    assert in_waiting["interpret"].json()["detail"] == "No question set for this reading"

    # QUESTION_ASKED: a second /ask is refused and does not replace the question.
    first = await client.post(f"{READING}/ask", json={**body, "question": "Первый"}, headers=headers)
    second = await client.post(f"{READING}/ask", json={**body, "question": "Второй"}, headers=headers)
    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"] == f"Invalid state transition: {QUESTION_ASKED} -> {QUESTION_ASKED}"
    no_card = await client.post(f"{READING}/interpret", json=body, headers=headers)
    assert no_card.status_code == 400
    assert no_card.json()["detail"] == "No cards drawn for this reading"
    # A refused /next must not wipe the question either.
    assert (await client.post(f"{READING}/next", json=body, headers=headers)).status_code == 409
    state = await get_state(client, headers, session_id)
    assert (state["state"], state["current_question"]) == (QUESTION_ASKED, "Первый")

    # READY: the cycle is complete, /interpret and /draw are refused.
    assert (await client.post(f"{READING}/draw", json=body, headers=headers)).status_code == 200
    await interpret(client, headers, session_id)
    again = await client.post(f"{READING}/interpret", json=body, headers=headers)
    assert again.status_code == 409
    assert again.json()["detail"] == f"Invalid state transition: {READY} -> {INTERPRETATION}"
    assert (await client.post(f"{READING}/draw", json=body, headers=headers)).status_code == 409
    assert await db_scalar("SELECT count(*) FROM reading_cycles") == 1


# --- resuming and abandoning --------------------------------------------------

async def test_active_returns_the_unfinished_reading(client):
    alice = await register(client, ALICE)
    bob = await register(client, BOB)

    nothing_yet = await client.get(f"{READING}/active", headers=alice)
    assert nothing_yet.status_code == 200
    assert nothing_yet.json() == {"session_id": None, "state": None}

    session_id = await start_reading(client, alice)
    await client.post(f"{READING}/ask", json={"session_id": session_id, "question": "Вопрос"}, headers=alice)

    active = await client.get(f"{READING}/active", headers=alice)
    assert active.status_code == 200
    assert active.json() == {"session_id": session_id, "state": QUESTION_ASKED}
    # Another user does not see it.
    assert (await client.get(f"{READING}/active", headers=bob)).json() == {"session_id": None, "state": None}

    # Once the Redis document is gone the reading cannot be resumed.
    await delete_reading_document(session_id)
    assert (await client.get(f"{READING}/active", headers=alice)).json() == {"session_id": None, "state": None}


async def test_active_is_empty_after_synthesis(client):
    headers = await register(client, ALICE)
    session_id = await start_reading(client, headers)
    await run_cycle(client, headers, session_id, "Вопрос")
    await synthesize(client, headers, session_id)

    active = await client.get(f"{READING}/active", headers=headers)

    assert active.json() == {"session_id": None, "state": None}


async def test_start_archives_an_abandoned_reading_and_keeps_its_rows(client, llm):
    headers = await register(client, ALICE)
    abandoned = await start_reading(client, headers)
    await run_cycle(client, headers, abandoned, "Брошенный вопрос")

    fresh = await start_reading(client, headers)

    sessions = await db_rows("SELECT id, status, cycle_count, synthesis FROM tarot_sessions ORDER BY created_at")
    assert sessions == [
        {"id": abandoned, "status": "archived", "cycle_count": 1, "synthesis": None},
        {"id": fresh, "status": "active", "cycle_count": 0, "synthesis": None},
    ]
    kept = await db_rows("SELECT session_id, question, interpretation FROM reading_cycles")
    assert kept == [
        {"session_id": abandoned, "question": "Брошенный вопрос", "interpretation": llm.full_text}
    ]

    assert (await client.get(f"{READING}/active", headers=headers)).json()["session_id"] == fresh
    history = (await client.get(f"{READING}/history", headers=headers)).json()["readings"]
    assert [item["session_id"] for item in history] == [abandoned]
    assert history[0]["synthesis"] is None
    assert [c["question"] for c in history[0]["cycles"]] == ["Брошенный вопрос"]


async def test_start_archives_a_reading_abandoned_long_ago_instead_of_deleting_it(client, llm):
    headers = await register(client, ALICE)
    abandoned = await start_reading(client, headers)
    await run_cycle(client, headers, abandoned, "Вчерашний вопрос")
    # The user comes back the next day: the row is older than SESSION_TTL and the
    # reading's Redis document has expired. Only cycle_count > 0 tells it apart
    # from the dead empty readings that /start deletes.
    await db_execute(
        "UPDATE tarot_sessions SET created_at = now() - interval '1 day' WHERE id = :id", id=abandoned
    )
    assert await delete_reading_document(abandoned) == 1  # one document per reading

    fresh = await start_reading(client, headers)

    sessions = await db_rows("SELECT id, status, cycle_count FROM tarot_sessions ORDER BY created_at")
    assert sessions == [
        {"id": abandoned, "status": "archived", "cycle_count": 1},
        {"id": fresh, "status": "active", "cycle_count": 0},
    ]
    kept = await db_rows("SELECT session_id, cycle_number, question, interpretation FROM reading_cycles")
    assert kept == [
        {
            "session_id": abandoned,
            "cycle_number": 1,
            "question": "Вчерашний вопрос",
            "interpretation": llm.full_text,
        }
    ]
    history = (await client.get(f"{READING}/history", headers=headers)).json()["readings"]
    assert [item["session_id"] for item in history] == [abandoned]
    assert [c["question"] for c in history[0]["cycles"]] == ["Вчерашний вопрос"]


async def test_start_cleans_up_only_dead_empty_readings(client):
    headers = await register(client, ALICE)
    dead_empty = await start_reading(client, headers)
    live_empty = await start_reading(client, headers)
    recent_empty = await start_reading(client, headers)
    # Two readings are older than the session TTL; only one of them lost its document.
    await db_execute(
        "UPDATE tarot_sessions SET created_at = now() - interval '2 hours' WHERE id IN (:a, :b)",
        a=dead_empty,
        b=live_empty,
    )
    await delete_reading_document(dead_empty)
    await delete_reading_document(recent_empty)

    fresh = await start_reading(client, headers)

    remaining = {row["id"] for row in await db_rows("SELECT id FROM tarot_sessions")}
    assert remaining == {live_empty, recent_empty, fresh}


# --- history ------------------------------------------------------------------

async def _make_archived_readings(client, headers, count: int) -> list[str]:
    session_ids = []
    for number in range(1, count + 1):
        session_id = await start_reading(client, headers)
        await run_cycle(client, headers, session_id, f"Вопрос {number}")
        await synthesize(client, headers, session_id)
        session_ids.append(session_id)
    return session_ids


async def test_history_is_not_deleted_and_free_user_sees_three(client):
    headers = await register(client, ALICE)
    session_ids = await _make_archived_readings(client, headers, 5)
    # /start and /synthesis used to trim the history down to the newest three.
    await start_reading(client, headers)

    resp = await client.get(f"{READING}/history", headers=headers)

    assert resp.status_code == 200
    readings = resp.json()["readings"]
    assert [item["session_id"] for item in readings] == session_ids[:1:-1]  # the newest three, newest first
    newest = readings[0]
    assert set(newest) == {"session_id", "spread_name", "created_at", "cycle_count", "synthesis", "cycles"}
    assert newest["spread_name"] == "one-card"
    assert newest["cycle_count"] == 1
    assert newest["synthesis"]
    assert [c["cycle_number"] for c in newest["cycles"]] == [1]
    assert newest["cycles"][0]["question"] == "Вопрос 5"
    assert set(newest["cycles"][0]) == {"cycle_number", "question", "cards"}
    # The client gets ready-to-render cards, not a number it has to look up.
    assert len(newest["cycles"][0]["cards"]) == 1
    assert_drawn_card(newest["cycles"][0]["cards"][0])

    # All five are still in the database with their cycles.
    archived = await db_rows("SELECT id FROM tarot_sessions WHERE status = 'archived' ORDER BY created_at")
    assert [row["id"] for row in archived] == session_ids
    assert await db_scalar("SELECT count(*) FROM reading_cycles") == 5


@pytest.mark.parametrize(
    "card_name, expected_name",
    [(None, "7 Мечи"), ("Старое имя", "Старое имя")],
    ids=["from-the-deck", "from-the-old-column"],
)
async def test_history_rebuilds_the_cards_of_a_row_without_the_new_column(
    client, card_name, expected_name
):
    """A row the stage-2 backfill could not fill still renders, from card_id/card_name."""
    headers = await register(client, ALICE)
    session_id = await start_reading(client, headers)
    await run_cycle(client, headers, session_id, "Вопрос")
    await synthesize(client, headers, session_id)
    await db_execute(
        "UPDATE reading_cycles SET cards = NULL, card_id = 57, card_name = :name", name=card_name
    )

    history = (await client.get(f"{READING}/history", headers=headers)).json()["readings"]

    assert history[0]["cycles"][0]["cards"] == [
        {
            "deck_id": DEFAULT_DECK_ID,
            "card_id": "swords07",
            "position": "main",
            "reversed": False,
            "name": expected_name,
            "image": "/decks/rider-waite/swords07.jpg",
        }
    ]


async def test_history_of_a_row_with_no_card_at_all_is_an_empty_list(client):
    headers = await register(client, ALICE)
    session_id = await start_reading(client, headers)
    await run_cycle(client, headers, session_id, "Вопрос")
    await synthesize(client, headers, session_id)
    await db_execute("UPDATE reading_cycles SET cards = NULL, card_id = NULL, card_name = NULL")

    history = (await client.get(f"{READING}/history", headers=headers)).json()["readings"]

    assert history[0]["cycles"][0]["cards"] == []


async def test_history_limit_follows_the_subscription(client):
    headers = await register(client, ALICE)
    other = await register(client, BOB)
    session_ids = await _make_archived_readings(client, headers, 5)
    await _make_archived_readings(client, other, 1)

    await db_execute(
        "UPDATE users SET subscription_ends_at = now() + interval '1 day' WHERE telegram_id = :id", id=ALICE
    )
    premium = (await client.get(f"{READING}/history", headers=headers)).json()["readings"]
    await db_execute(
        "UPDATE users SET subscription_ends_at = now() - interval '1 day' WHERE telegram_id = :id", id=ALICE
    )
    expired = (await client.get(f"{READING}/history", headers=headers)).json()["readings"]

    # Only Alice's readings, all five of them while the subscription is active.
    assert [item["session_id"] for item in premium] == session_ids[::-1]
    assert [item["session_id"] for item in expired] == session_ids[:1:-1]


async def test_history_limits_come_from_the_settings(client, monkeypatch):
    from config import settings

    headers = await register(client, ALICE)
    session_ids = await _make_archived_readings(client, headers, 5)

    monkeypatch.setattr(settings, "HISTORY_LIMIT_FREE", 2)
    monkeypatch.setattr(settings, "HISTORY_LIMIT_PREMIUM", 4)
    free = (await client.get(f"{READING}/history", headers=headers)).json()["readings"]
    await db_execute(
        "UPDATE users SET subscription_ends_at = now() + interval '1 day' WHERE telegram_id = :id", id=ALICE
    )
    premium = (await client.get(f"{READING}/history", headers=headers)).json()["readings"]

    assert [item["session_id"] for item in free] == session_ids[:2:-1]  # the newest two
    assert [item["session_id"] for item in premium] == session_ids[:0:-1]  # the newest four


async def test_history_loads_the_cycles_of_all_readings_in_one_query(client):
    from sqlalchemy import event

    from database import engine

    headers = await register(client, ALICE)
    await db_execute(
        "UPDATE users SET subscription_ends_at = now() + interval '1 day' WHERE telegram_id = :id", id=ALICE
    )

    async def selects_of_history(expected_readings: int) -> list[str]:
        statements: list[str] = []

        def record(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", record)
        try:
            resp = await client.get(f"{READING}/history", headers=headers)
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", record)
        readings = resp.json()["readings"]
        assert len(readings) == expected_readings
        assert all(len(item["cycles"]) == 1 for item in readings)
        return statements

    await _make_archived_readings(client, headers, 1)
    with_one = await selects_of_history(1)
    await _make_archived_readings(client, headers, 4)
    with_five = await selects_of_history(5)

    # user, sessions, cycles: the number of queries does not grow with the history.
    assert len(with_one) == len(with_five) == 3
    assert len([s for s in with_five if "FROM reading_cycles" in s]) == 1


# --- LLM failure --------------------------------------------------------------

async def test_failing_llm_keeps_interpretation_state_and_retry_succeeds(client, llm):
    headers = await register(client, ALICE)
    session_id = await start_reading(client, headers)
    await client.post(f"{READING}/ask", json={"session_id": session_id, "question": "Вопрос"}, headers=headers)
    await client.post(f"{READING}/draw", json={"session_id": session_id}, headers=headers)

    llm.fail = True
    failed = await interpret(client, headers, session_id)

    assert failed == [{"text": llm.chunks[0]}, {"error": "interpretation_failed"}, "[DONE]"]
    state = await get_state(client, headers, session_id)
    assert state["state"] == INTERPRETATION
    assert state["cycle_count"] == 0
    assert state["cycles"] == []
    assert await db_scalar("SELECT count(*) FROM reading_cycles") == 0
    assert await db_scalar("SELECT cycle_count FROM tarot_sessions WHERE id = :id", id=session_id) == 0

    llm.fail = False
    retried = await interpret(client, headers, session_id)

    assert retried[-2:] == [{"cleaned": llm.full_text}, "[DONE]"]
    state = await get_state(client, headers, session_id)
    assert state["state"] == READY
    assert state["cycle_count"] == 1
    cycles = await db_rows("SELECT cycle_number, interpretation FROM reading_cycles")
    assert cycles == [{"cycle_number": 1, "interpretation": llm.full_text}]
    assert await db_scalar("SELECT cycle_count FROM tarot_sessions WHERE id = :id", id=session_id) == 1


async def test_interpret_retry_after_a_failure_past_the_commit_finishes_the_saved_cycle(
    client, llm, monkeypatch
):
    from services.reading import reading_service

    headers = await register(client, ALICE)
    session_id = await start_reading(client, headers)
    body = {"session_id": session_id}
    await client.post(f"{READING}/ask", json={**body, "question": "Вопрос"}, headers=headers)
    await client.post(f"{READING}/draw", json=body, headers=headers)

    # The cycle row is committed, then Redis goes away before the state moves to READY.
    real_complete_cycle = reading_service.complete_cycle
    failures = []

    async def complete_cycle_fails_once(*args, **kwargs):
        if not failures:
            failures.append("failed")
            raise RuntimeError("Redis went away after the commit (test)")
        return await real_complete_cycle(*args, **kwargs)

    monkeypatch.setattr(reading_service, "complete_cycle", complete_cycle_fails_once)
    failed = await interpret(client, headers, session_id)

    assert failed[-2:] == [{"error": "interpretation_failed"}, "[DONE]"]
    assert (await get_state(client, headers, session_id))["state"] == INTERPRETATION
    assert await db_scalar("SELECT count(*) FROM reading_cycles") == 1

    # The retry must not trip over uq_reading_cycles_session_cycle, and it does not
    # pay for a second LLM answer: the saved interpretation is served.
    retried = await interpret(client, headers, session_id)

    assert retried == [{"text": llm.full_text}, {"cleaned": llm.full_text}, "[DONE]"]
    assert len(llm.calls) == 1
    state = await get_state(client, headers, session_id)
    assert (state["state"], state["cycle_count"]) == (READY, 1)
    assert [cycle["answer"] for cycle in state["cycles"]] == [llm.full_text]  # appended once
    assert await db_rows("SELECT cycle_number, interpretation FROM reading_cycles") == [
        {"cycle_number": 1, "interpretation": llm.full_text}
    ]
    assert await db_scalar("SELECT cycle_count FROM tarot_sessions WHERE id = :id", id=session_id) == 1

    # The reading goes on normally.
    assert (await client.post(f"{READING}/next", json=body, headers=headers)).status_code == 200
    await run_cycle(client, headers, session_id, "Следующий вопрос")
    state = await get_state(client, headers, session_id)
    assert (state["state"], state["cycle_count"], len(state["cycles"])) == (READY, 2, 2)
    numbers = await db_rows("SELECT cycle_number, question FROM reading_cycles ORDER BY cycle_number")
    assert numbers == [
        {"cycle_number": 1, "question": "Вопрос"},
        {"cycle_number": 2, "question": "Следующий вопрос"},
    ]


async def test_cycle_is_saved_when_the_redis_counter_fell_behind_the_saved_rows(client):
    headers = await register(client, ALICE)
    session_id = await start_reading(client, headers)
    await run_cycle(client, headers, session_id, "Первый вопрос")
    # The counter write of the first cycle was lost: cycle_number 1 would be reused.
    document = await reading_document(session_id)
    document["cycle"] = 0
    await write_reading_document(session_id, document)
    assert (await get_state(client, headers, session_id))["cycle_count"] == 0

    await client.post(f"{READING}/next", json={"session_id": session_id}, headers=headers)
    events = await run_cycle(client, headers, session_id, "Второй вопрос")

    assert "cleaned" in events[-2]
    state = await get_state(client, headers, session_id)
    assert (state["state"], state["cycle_count"], len(state["cycles"])) == (READY, 2, 2)
    numbers = await db_rows("SELECT cycle_number, question FROM reading_cycles ORDER BY cycle_number")
    assert numbers == [
        {"cycle_number": 1, "question": "Первый вопрос"},
        {"cycle_number": 2, "question": "Второй вопрос"},
    ]
    assert await db_scalar("SELECT cycle_count FROM tarot_sessions WHERE id = :id", id=session_id) == 2


@pytest.mark.parametrize("failure", ["raises", "empty"])
async def test_failing_llm_on_synthesis_is_502_and_retry_archives(client, llm, failure):
    headers = await register(client, ALICE)
    session_id = await start_reading(client, headers)
    await run_cycle(client, headers, session_id, "Вопрос")
    good_chunks = llm.chunks

    if failure == "raises":
        llm.fail = True
    else:
        llm.chunks = ["**", "__"]  # nothing is left after clean_llm_output
    failed = await client.post(f"{READING}/synthesis", json={"session_id": session_id}, headers=headers)

    assert failed.status_code == 502
    assert failed.json()["detail"] == "Synthesis failed"
    # Nothing was archived with a missing synthesis, and the reading can still be resumed.
    assert await db_rows("SELECT status, synthesis FROM tarot_sessions") == [
        {"status": "active", "synthesis": None}
    ]
    active = await client.get(f"{READING}/active", headers=headers)
    assert active.json() == {"session_id": session_id, "state": COMPLETED}

    llm.fail = False
    llm.chunks = good_chunks
    await synthesize(client, headers, session_id)

    assert await db_rows("SELECT status, synthesis FROM tarot_sessions") == [
        {"status": "archived", "synthesis": llm.full_text}
    ]
