import json
import re
from pathlib import Path
from typing import AsyncGenerator

from openai import AsyncOpenAI

from config import settings

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load_file(filename: str) -> str:
    path = PROMPTS_DIR / filename
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    raise FileNotFoundError(f"File not found: {path}")


def _load_spread(name: str) -> dict:
    config_path = PROMPTS_DIR / "spreads" / f"{name}.json"
    if not config_path.exists():
        raise FileNotFoundError(f"Spread config not found: {config_path}")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["prompt_text"] = _load_file(f"spreads/{config['system_prompt_file']}")
    return config


PERSONA = _load_file("persona.md")
SPREADS = {
    "one-card": _load_spread("one-card"),
}
DEFAULT_SPREAD = "one-card"

SYNTHESIS_PROMPT = """Синтезируй несколько раскладов в один вывод.

Формат:
1. Что повторяется во всех вопросах (1-2 предложения)
2. В какую сторону всё движется (1-2 предложения)
3. Что конкретно делать (2-3 действия)

Максимум 400 слов. Без повторения отдельных раскладов."""

client = (
    AsyncOpenAI(api_key=settings.LLM_API_KEY, base_url=settings.LLM_BASE_URL or None)
    if settings.LLM_API_KEY
    else None
)

MAJOR_ARCANA = [
    "Шут", "Маг", "Верховная Жрица", "Императрица", "Император",
    "Иерофант", "Влюблённые", "Колесница", "Сила", "Отшельник",
    "Колесо Фортуны", "Справедливость", "Повешенный", "Смерть",
    "Умеренность", "Дьявол", "Башня", "Звезда", "Луна", "Солнце",
    "Суд", "Мир",
]

MINOR_RANKS = ["Туз", "2", "3", "4", "5", "6", "7", "8", "9", "10", "Паж", "Рыцарь", "Королева", "Король"]

SUITS = ["Кубки", "Пентакли", "Мечи", "Жезлы"]


def get_card_name(card_id: int) -> str:
    if 1 <= card_id <= 22:
        return MAJOR_ARCANA[card_id - 1]
    minor_index = card_id - 23
    suit_index = minor_index // 14
    rank_index = minor_index % 14
    return f"{MINOR_RANKS[rank_index]} {SUITS[suit_index]}"


def clean_llm_output(text: str) -> str:
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'[*_`]', '', text)
    text = re.sub(r'#{1,6}\s*', '', text)
    text = re.sub(r'[^\u0400-\u04FF\u0000-\u007F\u00A0 \t\n\r.,!?;:\-\u2012\u2013\u2014()\"\'«»/]', '', text)
    text = re.sub(r'([a-zA-Z])([\u0400-\u04FF])', r'\1 \2', text)
    text = re.sub(r'([\u0400-\u04FF])([a-zA-Z])', r'\1 \2', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def build_reading_prompt(
    cards: list[int],
    question: str,
    user_name: str,
    history: list[dict] | None = None,
    spread_name: str = DEFAULT_SPREAD,
) -> list[dict]:
    spread = SPREADS[spread_name]
    card_names = [get_card_name(c) for c in cards]
    card_list = ", ".join(card_names)

    position_hints = []
    for rule in spread.get("position_rules", []):
        position_hints.append(f"- {rule['label']}: {rule['prompt_addition']}")
    position_text = "\n".join(position_hints) if position_hints else ""

    constraints = spread.get("aggregation_rules", {}).get("additional_constraints", [])
    constraints_text = "\n".join(f"- {c}" for c in constraints) if constraints else ""

    system_msg = f"""{PERSONA}

---

{spread['prompt_text']}

{position_text}

{constraints_text}

Клиент: {user_name}
Карты: {card_list}"""

    messages = [{"role": "system", "content": system_msg}]

    if history:
        messages.extend(history[-4:])

    messages.append({"role": "user", "content": question})
    return messages


def get_spread_config(spread_name: str = DEFAULT_SPREAD) -> dict:
    return SPREADS[spread_name]


def build_synthesis_prompt(
    cycles: list[dict],
    user_name: str,
) -> list[dict]:
    cycles_text = []
    for i, cycle in enumerate(cycles, 1):
        cards = cycle.get("cards", [])
        card_names = [get_card_name(c) for c in cards]
        question = cycle.get("question", "Общий вопрос")
        answer = cycle.get("answer", "")
        cycles_text.append(
            f"Расклад {i}:\n"
            f"Вопрос: {question}\n"
            f"Карты: {', '.join(card_names)}\n"
            f"Ответ: {answer}"
        )

    all_cycles = "\n\n".join(cycles_text)

    system_msg = f"""{PERSONA}

---

{SYNTHESIS_PROMPT}

Клиент: {user_name}

История раскладов:
{all_cycles}"""

    return [{"role": "system", "content": system_msg}]


async def stream_prediction(
    cards: list[int],
    question: str,
    user_name: str,
    history: list[dict] | None = None,
    is_premium: bool = False,
    custom_messages: list[dict] | None = None,
    spread_name: str = DEFAULT_SPREAD,
) -> AsyncGenerator[str, None]:
    if not client:
        yield "[Модуль ИИ не настроен. Установите LLM_API_KEY в .env]"
        return

    spread = SPREADS[spread_name]
    model = settings.LLM_PREMIUM_MODEL if is_premium else settings.LLM_FREE_MODEL
    messages = custom_messages if custom_messages else build_reading_prompt(
        cards, question, user_name, history, spread_name
    )

    stream = await client.chat.completions.create(
        model=model,
        messages=messages,
        stream=True,
        max_tokens=spread.get("max_tokens", 2048),
    )

    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content
