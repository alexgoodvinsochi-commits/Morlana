"""services.llm text handling: the spread's wording and the cards in both prompts,
persona rules, cleaning of the model's answer. No network."""
import pytest


def _spread():
    from services.spreads import spread_registry

    return spread_registry.default


def _card(card_id: str = "maj00", position: str = "main", reversed: bool = False) -> dict:
    from services.decks import deck_registry

    return deck_registry.default.drawn_card(card_id, position, reversed=reversed)


def _cycles() -> list[dict]:
    return [
        {
            "cycle_number": 1,
            "question": "Что меня ждёт?",
            "cards": [_card()],
            "answer": "Карта говорит: да.",
        }
    ]


@pytest.mark.parametrize(
    "rule",
    ["без Markdown", "соглашаться ли на лечение или операцию", "не хочет жить", "112"],
    ids=["plain-text", "no-money-or-treatment-advice", "crisis", "emergency-number"],
)
def test_persona_rules_reach_the_reading_and_the_synthesis_prompt(rule):
    from services.llm import build_reading_prompt, build_synthesis_prompt

    spread = _spread()
    reading = build_reading_prompt(spread, [_card()], "Что меня ждёт?", "Алиса")[0]["content"]
    synthesis = build_synthesis_prompt(spread, _cycles(), "Алиса")[0]["content"]

    assert rule in reading
    assert rule in synthesis


def test_the_reading_prompt_is_built_from_the_spread_file():
    """Everything the prompt says about the layout comes from the JSON, not from code."""
    from services.llm import build_reading_prompt

    spread = _spread()
    messages = build_reading_prompt(spread, [_card()], "Что меня ждёт?", "Алиса")

    assert [message["role"] for message in messages] == ["system", "user"]
    assert messages[1]["content"] == "Что меня ждёт?"  # the question is the user turn
    system = messages[0]["content"]
    assert spread.system_prompt in system
    assert spread.positions[0].prompt_addition in system
    for constraint in spread.aggregation_constraints:
        assert constraint in system
    assert spread.aggregation_constraints  # one-card really does carry constraints
    assert "Клиент: Алиса" in system


@pytest.mark.parametrize(
    "reversed_card, expected",
    [(False, "Главная карта: Шут"), (True, "Главная карта: Шут (перевёрнута)")],
    ids=["upright", "reversed"],
)
def test_a_card_is_rendered_as_its_position_label_and_name(reversed_card, expected):
    from services.llm import build_reading_prompt

    system = build_reading_prompt(
        _spread(), [_card(reversed=reversed_card)], "Вопрос", "Алиса"
    )[0]["content"]

    assert expected in system


def test_every_card_of_a_multi_card_spread_reaches_the_prompt(two_card_spread):
    from services.llm import build_reading_prompt

    cards = [_card("maj00", "situation"), _card("swords07", "advice", reversed=True)]

    system = build_reading_prompt(two_card_spread, cards, "Как быть?", "Алиса")[0]["content"]

    assert "Ситуация: Шут" in system
    assert "Совет: 7 Мечи (перевёрнута)" in system
    assert two_card_spread.system_prompt in system
    for position in two_card_spread.positions:
        assert position.prompt_addition in system


def test_the_synthesis_prompt_uses_the_spread_and_lists_every_cycle():
    from services.llm import build_synthesis_prompt

    spread = _spread()
    cycles = _cycles() + [
        {
            "cycle_number": 2,
            "question": "А на работе?",
            "cards": [_card("wands14")],
            "answer": "Карта говорит: подожди.",
        }
    ]

    messages = build_synthesis_prompt(spread, cycles, "Алиса")

    assert [message["role"] for message in messages] == ["system"]
    system = messages[0]["content"]
    assert spread.synthesis_prompt in system
    assert "Клиент: Алиса" in system
    for cycle in cycles:
        assert cycle["question"] in system
        assert cycle["answer"] in system
    assert "Главная карта: Шут" in system
    assert "Главная карта: Король Жезлы" in system


@pytest.mark.parametrize(
    "raw, cleaned",
    [
        ("что‑то за 3 дня", "что-то за 3 дня"),
        ("из‑за, по‐новому", "из-за, по-новому"),
        ("15–20 минут", "15–20 минут"),
        ("Главная карта: 3 Жезлов", "Главная карта: 3 Жезлов"),
        ("т. п.", "т. п."),
        ("1 000 ₽", "1 000"),
        ("Итак…", "Итак..."),
    ],
)
def test_clean_llm_output_keeps_typographic_hyphens_and_spaces(raw, cleaned):
    from services.llm import clean_llm_output

    assert clean_llm_output(raw) == cleaned


def test_clean_llm_output_still_drops_markdown_and_emoji():
    from services.llm import clean_llm_output

    assert clean_llm_output("* выберите **одно** дело 🙂\n# Итог") == "выберите одно дело \nИтог"
