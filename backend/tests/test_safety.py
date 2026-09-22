"""Crisis messages: recognised before the LLM, answered with a fixed reply. No network."""
import logging

import pytest

from tests.helpers import READING, db_rows, get_state, interpret, register, run_cycle, start_reading, synthesize

ALICE = 3001

READY = "ГОТОВО"
COMPLETED = "ЗАВЕРШЕНО"

CRISIS_QUESTION = "Не хочу больше жить. Что мне делать?"


@pytest.mark.parametrize(
    "text",
    [
        "не хочу жить",
        "Мне не хочется жить",
        "жить не хочу",
        "Жить не хочется совсем",
        "Не хочу больше жить.",
        "Не хочу жить дальше, что меня ждёт?",
        "хочу умереть",
        "Лучше бы меня не было",
        "Думаю покончить с собой",
        "Покончу с собой",
        "Она покончила с собой, и я тоже хочу",
        "Самоубийство - это выход?",
        "У меня суицидальные мысли",
        "Хочу убить себя",
        "Я убью себя",
        "Хочу свести счёты с жизнью",
        "Хочу причинить себе вред",
        "Я продолжаю наносить себе вред",
        "Хочется резать себя",
        "Я режу себя",
        "Опять хочу порезать себя",
        "Думаю повеситься",
        "Хочу выпрыгнуть из окна",
        "Наглотаться таблеток и всё",
        # ё, capitals, extra spaces, punctuation
        "НЕ ХОЧУ ЖИТЬ!!!",
        "не   хочу    жить...",
        "Не хочу—жить",
        "Свести СЧЁТЫ с жизнью",
        "нехочу жить",
        "не хочу... жить",
        # the next sentence starts with a preposition or an adverb: not "жить с мужем"
        "Не хочу жить. С мужем постоянно ссоримся",
        "не хочу жить, у меня никого нет",
        "не хочу жить 😭 у меня никого нет",
        "Не хочу жить — на работе ад",
        "Не хочу жить, как мне быть?",
        "не хочу жить так как он меня бросил",
        "Расстались с ним, жить не хочу",
        # typed the way people type in Telegram
        "не хочеться жить",
        "не хочу жыть",
        "не особо хочется жить последнее время",
        "не хочу дальше жить",
        "жить неохота",
        "устала жить",
        "надоело жить",
        "у меня депрессия жить не хочу",
        "не хочу жить с этой болью",
        "не хочу жить в этом аду",
        "не вижу смысла жить",
        "Нет сил больше жить",
        "иногда хочется просто умереть",
        "умереть хочется",
        "было бы лучше если бы меня не было",
        "всем будет лучше без меня",
        "хочу уснуть и не проснуться",
        "хочу покончить с жизнью",
        "суецид",
        "я режу руки",
        "хочу выйти в окно",
        "выпить все таблетки",
        "боюсь что сделаю с собой что-нибудь",
        # decided in services/safety.py: caught on purpose
        "Не хочу жить без него, вернётся ли он?",
        "Не хочу жить с этим",
        "Не хочу жить в этом мире",
        "Посоветуй сериал про суицид",
        "не хочу жить так как мои родители",
    ],
)
def test_crisis_messages_are_recognised(text):
    from services.safety import is_crisis_message

    assert is_crisis_message(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "Не хочу жить с мужем, стоит ли разводиться?",
        "не хочу жить с родителями",
        "Не хочу жить в этом городе, переезжать ли?",
        "Не хочу жить у свекрови",
        "Не хочется жить вместе до свадьбы",
        "Не хочу жить так, как живут мои родители",
        "Не хочу жить, как все. Какой путь выбрать?",
        "не хочу жить с этим человеком",
        "не хочу жить дальше с мужем",
        "не хочу жить прошлым, отпустить бывшего?",
        "не хочу жить ради других",
        "не хочу жить без любви, встречу ли я мужчину?",
        "не хочу жить от зарплаты до зарплаты",
        "с ним жить не хочу а уйти боюсь",
        "в этом городе жить не хочу",
        "так жить больше не хочу, что изменить?",
        "Устала жить с мужем-тираном, развестись?",
        "Надоело жить в съёмной квартире",
        "Он не хочет жить со мной",
        "Хочу жить, не хочу работать",
        "Не хочу просыпаться рано на работу",
        "Хочу умереть с ним в один день",
        "Стоит ли уйти из жизни бывшего?",
        "Как не убиться на гололеде?",
        "Умираю от любопытства, что он думает обо мне?",
        "Смертельно устала от работы, увольняться?",
        "Выпала Смерть и Башня, что это значит?",
        "Как убить время до встречи?",
        "Выпала Смерть, это плохо?",
        "Что значит карта Смерть в отношениях?",
        "Что означает Повешенный?",
        "Я чуть не умерла от смеха",
        "Не хочу умереть в одиночестве, встречу ли я любовь?",
        "Уйдёт ли он из моей жизни?",
        "Что меня ждёт на работе?",
        "",
    ],
)
def test_tarot_questions_are_not_crisis_messages(text):
    from services.safety import is_crisis_message

    assert is_crisis_message(text) is False


@pytest.mark.parametrize("value", [None, 42, ["не хочу жить"]], ids=["none", "number", "list"])
def test_a_question_that_is_not_text_is_not_a_crisis_message(value):
    # Redis returns what json.loads made of the question: "42" comes back as a number.
    from services.safety import is_crisis_message

    assert is_crisis_message(value) is False


def test_crisis_reply_uses_the_persona_numbers_and_survives_cleaning():
    from services.llm import PERSONA, clean_llm_output
    from services.safety import CRISIS_REPLY

    for number in ("+7 495 989-50-50", "8-800-2000-122", "112"):
        assert number in CRISIS_REPLY
        assert number in PERSONA
    assert "?" not in CRISIS_REPLY  # no questions back
    assert clean_llm_output(CRISIS_REPLY) == CRISIS_REPLY


async def test_crisis_question_gets_the_fixed_reply_without_the_llm(client, llm, caplog):
    from services.safety import CRISIS_REPLY

    headers = await register(client, ALICE)
    session_id = await start_reading(client, headers)

    with caplog.at_level(logging.INFO, logger="routes.reading"):
        events = await run_cycle(client, headers, session_id, CRISIS_QUESTION)

    assert events == [{"text": CRISIS_REPLY}, {"cleaned": CRISIS_REPLY}, "[DONE]"]
    assert llm.calls == []
    logged = [record.getMessage() for record in caplog.records if record.name == "routes.reading"]
    assert any("crisis message detected" in message and session_id in message for message in logged)
    assert not any("жить" in message for message in logged)  # the question is never logged

    # The cycle is saved and completed like any other.
    state = await get_state(client, headers, session_id)
    assert (state["state"], state["cycle_count"]) == (READY, 1)
    assert state["cycles"] == [
        {"cards": [state["current_card"]], "question": CRISIS_QUESTION, "answer": CRISIS_REPLY}
    ]
    assert await db_rows("SELECT cycle_number, question, interpretation FROM reading_cycles") == [
        {"cycle_number": 1, "question": CRISIS_QUESTION, "interpretation": CRISIS_REPLY}
    ]
    assert await db_rows("SELECT status, cycle_count FROM tarot_sessions") == [
        {"status": "active", "cycle_count": 1}
    ]

    # The reading goes on, and a normal question reaches the LLM again.
    assert (await client.post(f"{READING}/next", json={"session_id": session_id}, headers=headers)).status_code == 200
    events = await run_cycle(client, headers, session_id, "Что меня ждёт на работе?")
    assert events[-2:] == [{"cleaned": llm.full_text}, "[DONE]"]
    assert [call["question"] for call in llm.calls] == ["Что меня ждёт на работе?"]


async def test_crisis_cycle_failing_after_the_commit_is_finished_from_the_saved_row(client, llm, monkeypatch):
    from services.reading import reading_service
    from services.safety import CRISIS_REPLY

    headers = await register(client, ALICE)
    session_id = await start_reading(client, headers)

    real_complete_cycle = reading_service.complete_cycle
    failures = []

    async def complete_cycle_fails_once(*args, **kwargs):
        if not failures:
            failures.append("failed")
            raise RuntimeError("Redis went away after the commit (test)")
        return await real_complete_cycle(*args, **kwargs)

    monkeypatch.setattr(reading_service, "complete_cycle", complete_cycle_fails_once)
    failed = await run_cycle(client, headers, session_id, CRISIS_QUESTION)

    assert failed[-2:] == [{"error": "interpretation_failed"}, "[DONE]"]
    assert (await get_state(client, headers, session_id))["state"] == "ИНТЕРПРЕТАЦИЯ"

    # The retry serves the saved row: no second insert, still no LLM.
    retried = await interpret(client, headers, session_id)

    assert retried == [{"text": CRISIS_REPLY}, {"cleaned": CRISIS_REPLY}, "[DONE]"]
    assert llm.calls == []
    state = await get_state(client, headers, session_id)
    assert (state["state"], state["cycle_count"], len(state["cycles"])) == (READY, 1, 1)
    assert await db_rows("SELECT cycle_number, interpretation FROM reading_cycles") == [
        {"cycle_number": 1, "interpretation": CRISIS_REPLY}
    ]


async def test_a_tarot_question_about_where_to_live_still_reaches_the_llm(client, llm):
    headers = await register(client, ALICE)
    session_id = await start_reading(client, headers)

    events = await run_cycle(client, headers, session_id, "Не хочу жить с мужем, стоит ли разводиться?")

    assert events == [{"text": chunk} for chunk in llm.chunks] + [{"cleaned": llm.full_text}, "[DONE]"]
    assert len(llm.calls) == 1
    assert (await get_state(client, headers, session_id))["state"] == READY


async def test_synthesis_of_a_reading_with_a_crisis_cycle_skips_the_llm(client, llm, caplog):
    from services.safety import CRISIS_REPLY

    headers = await register(client, ALICE)
    session_id = await start_reading(client, headers)
    await run_cycle(client, headers, session_id, "Что меня ждёт на работе?")
    await client.post(f"{READING}/next", json={"session_id": session_id}, headers=headers)
    await run_cycle(client, headers, session_id, CRISIS_QUESTION)
    assert len(llm.calls) == 1  # the first interpretation only

    with caplog.at_level(logging.INFO, logger="routes.reading"):
        events = await synthesize(client, headers, session_id)

    assert events == [{"text": CRISIS_REPLY}, {"cleaned": CRISIS_REPLY}, "[DONE]"]
    assert len(llm.calls) == 1
    assert any(
        "crisis message detected" in record.getMessage() and session_id in record.getMessage()
        for record in caplog.records
    )
    assert (await get_state(client, headers, session_id))["state"] == COMPLETED
    assert await db_rows("SELECT status, cycle_count, synthesis FROM tarot_sessions") == [
        {"status": "archived", "cycle_count": 2, "synthesis": CRISIS_REPLY}
    ]
    history = (await client.get(f"{READING}/history", headers=headers)).json()["readings"]
    assert [item["synthesis"] for item in history] == [CRISIS_REPLY]
