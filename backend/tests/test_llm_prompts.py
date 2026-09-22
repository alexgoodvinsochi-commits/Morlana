"""services.llm text handling: persona rules in both prompts, cleaning of the model's answer. No network."""
import pytest

CYCLES = [{"cards": [1], "question": "Что меня ждёт?", "answer": "Карта говорит: да."}]


@pytest.mark.parametrize(
    "rule",
    ["без Markdown", "соглашаться ли на лечение или операцию", "не хочет жить", "112"],
    ids=["plain-text", "no-money-or-treatment-advice", "crisis", "emergency-number"],
)
def test_persona_rules_reach_the_reading_and_the_synthesis_prompt(rule):
    from services.llm import build_reading_prompt, build_synthesis_prompt

    reading = build_reading_prompt([1], "Что меня ждёт?", "Алиса")[0]["content"]
    synthesis = build_synthesis_prompt(CYCLES, "Алиса")[0]["content"]

    assert rule in reading
    assert rule in synthesis


@pytest.mark.parametrize(
    "raw, cleaned",
    [
        ("что\u2011то за 3\u202fдня", "что-то за 3 дня"),
        ("из\u2011за, по\u2010новому", "из-за, по-новому"),
        ("15\u201320\u202fминут", "15\u201320 минут"),
        ("Главная карта:\u202f3 Жезлов", "Главная карта: 3 Жезлов"),
        ("т.\u200aп.", "т. п."),
        ("1\u2009000\u2007\u20bd", "1 000"),
        ("Итак\u2026", "Итак..."),
    ],
)
def test_clean_llm_output_keeps_typographic_hyphens_and_spaces(raw, cleaned):
    from services.llm import clean_llm_output

    assert clean_llm_output(raw) == cleaned


def test_clean_llm_output_still_drops_markdown_and_emoji():
    from services.llm import clean_llm_output

    assert clean_llm_output("* выберите **одно** дело 🙂\n# Итог") == "выберите одно дело \nИтог"
