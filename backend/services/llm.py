import re
from pathlib import Path
from typing import AsyncGenerator

from openai import AsyncOpenAI

from config import settings
from services.spreads import Spread

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load_file(filename: str) -> str:
    path = PROMPTS_DIR / filename
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    raise FileNotFoundError(f"File not found: {path}")


PERSONA = _load_file("persona.md")


def build_client() -> AsyncOpenAI | None:
    """The OpenAI-compatible provider client from settings; None without LLM_API_KEY."""
    if not settings.LLM_API_KEY:
        return None
    return AsyncOpenAI(
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL or None,
        project=settings.LLM_PROJECT or None,
        default_headers=None if settings.LLM_DATA_LOGGING else {"x-data-logging-enabled": "false"},
    )


client = build_client()


# Typographic characters the whitelist below would drop, gluing words together
# ("что‑то" -> "чтото", "3 дня" -> "3дня"): mapped to their plain equivalents first.
_TYPOGRAPHIC = str.maketrans({
    "‐": "-",  # hyphen
    "‑": "-",  # non-breaking hyphen
    " ": " ",  # figure space
    " ": " ",  # thin space
    " ": " ",  # hair space
    " ": " ",  # narrow no-break space
    "…": "...",  # ellipsis
})


def clean_llm_output(text: str) -> str:
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'[*_`]', '', text)
    text = re.sub(r'#{1,6}\s*', '', text)
    text = text.translate(_TYPOGRAPHIC)
    text = re.sub(r'[^Ѐ-ӿ\u0000-\u007F  \t\n\r.,!?;:\-‒–—()\"\'«»/]', '', text)
    text = re.sub(r'([a-zA-Z])([Ѐ-ӿ])', r'\1 \2', text)
    text = re.sub(r'([Ѐ-ӿ])([a-zA-Z])', r'\1 \2', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _card_label(spread: Spread, card: dict) -> str:
    """One drawn card for the prompt: '<position label>: <card name>[ (перевёрнута)]'."""
    name = card.get("name") or card.get("card_id", "")
    line = f"{spread.label_for(card.get('position', ''))}: {name}"
    return f"{line} (перевёрнута)" if card.get("reversed") else line


def build_reading_prompt(
    spread: Spread,
    cards: list[dict],
    question: str,
    user_name: str,
) -> list[dict]:
    """System message for one cycle. `cards` are DrawnCard-shaped dicts."""
    position_text = "\n".join(
        f"- {position.label}: {position.prompt_addition}" for position in spread.positions
    )
    constraints_text = "\n".join(f"- {c}" for c in spread.aggregation_constraints)
    card_list = "\n".join(_card_label(spread, card) for card in cards)

    system_msg = f"""{PERSONA}

---

{spread.system_prompt}

{position_text}

{constraints_text}

Клиент: {user_name}
Карты:
{card_list}"""

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": question},
    ]


def build_synthesis_prompt(
    spread: Spread,
    cycles: list[dict],
    user_name: str,
) -> list[dict]:
    """System message for the synthesis. `cycles` are the collected cycle_data entries."""
    cycles_text = []
    for i, cycle in enumerate(cycles, 1):
        card_names = ", ".join(_card_label(spread, card) for card in cycle.get("cards", []))
        question = cycle.get("question", "Общий вопрос")
        answer = cycle.get("answer", "")
        cycles_text.append(
            f"Расклад {i}:\n"
            f"Вопрос: {question}\n"
            f"Карты: {card_names}\n"
            f"Ответ: {answer}"
        )

    all_cycles = "\n\n".join(cycles_text)

    system_msg = f"""{PERSONA}

---

{spread.synthesis_prompt}

Клиент: {user_name}

История раскладов:
{all_cycles}"""

    return [{"role": "system", "content": system_msg}]


async def stream_prediction(
    messages: list[dict],
    spread: Spread,
    is_premium: bool = False,
) -> AsyncGenerator[str, None]:
    """Stream the provider's answer. The spread sets max_tokens and temperature."""
    if not client:
        yield "[Модуль ИИ не настроен. Установите LLM_API_KEY в .env]"
        return

    model = settings.LLM_PREMIUM_MODEL if is_premium else settings.LLM_FREE_MODEL

    stream = await client.chat.completions.create(
        model=model,
        messages=messages,
        stream=True,
        max_tokens=spread.max_tokens,
        temperature=spread.temperature,
    )

    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content
