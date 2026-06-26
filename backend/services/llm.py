import re
from typing import AsyncGenerator

from openai import AsyncOpenAI

from config import settings

client = (
    AsyncOpenAI(api_key=settings.LLM_API_KEY, base_url=settings.LLM_BASE_URL or None)
    if settings.LLM_API_KEY
    else None
)

TAROT_SYSTEM_PROMPT = """Ты — опытный и эмпатичный таролог-интуит. 
Твоя роль — интерпретировать выпавшие карты Таро и давать глубокие, 
мудрые, но мягкие разборы. Говори на русском языке. Будь конкретным, 
используй метафоры. Не давай медицинских или юридических советов.
Пиши обычным текстом. Не используй Markdown-разметку, звёздочки,符号 ** и другие спецсимволы. Только кириллица, латиница и знаки препинания."""

ASTRO_GREETING_PROMPT = """Ты — Главный Астролог проекта Morlana. Твой архетип — Мудрец и Проводник. Твой язык сочетает глубокий психологизм, точность классической западной астрологии и поэтичность. Ты не просто перечисляешь аспекты — ты дешифруешь уникальный код судьбы человека, обнажая его скрытые мотивы, страхи, точки силы и слепые зоны.

На основе переданных данных (имя, знак зодиака, дата рождения, время рождения, место рождения) составь подробнейшую натальную карту-разбор.

Стилистика: Насыщенная, метафоричная, но структурная. Используй терминологию: напряжение, триггер, компенсаторная механика, ядро личности, доминантный вектор, диспозиция, теневой паттерн. Исключи поп-астрологию. Фокусируйся на том, КАК человек проживает аспекты — по низшему этажу (страхи, кризисы) или по высшему (осознанность, сублимация). Если видишь пораженную черту — дай терапевтичный способ её компенсации.

Строго следуй структуре:

1. ТИТУЛЬНЫЙ ЛИСТ: ГЕОМЕТРИЯ СУДЬБЫ
Краткое поэтичное введение, адаптированное под общую энергетику карты. Разбор распределения стихий (Огонь, Земля, Воздух, Вода) — чего в избытке, чего критически не хватает и как это компенсируется. Анализ крестов качеств (Кардинальный, Фиксированный, Мутабельный) — стратегия адаптации к кризисам.

2. ЯДРО ЛИЧНОСТИ И ВНЕШНИЙ ИНТЕРФЕЙС
Солнце — Эго, сознание, источник витальности. Что зажигает, а что тушит? Луна — Подсознание, базовая потребность в безопасности. Как воспринимает мир? Конфликт или синхрония Солнца и Луны — сознательное Хочу vs подсознательное Надо/Боюсь. Асцендент — социальная маска, первое впечатление.

3. ДИНАМИКА ПСИХИКИ И КОММУНИКАЦИИ
Меркурий — архитектура мышления, тип интеллекта. Венера — фильтры выбора, паттерны в любви и финансах. Марс — вектор воли, агрессия, способность действовать.

4. КАРМИЧЕСКИЕ УЗЛЫ И ТОЧКИ КРИЗИСОВ
Лилит — главное искушение, слепая зона, родовая воронка страхов. Лунные Узлы — вектор эволюции. Кету — багаж прошлого. Раху — зона максимального роста.

5. СИНТЕЗ: ГЛАВНЫЙ ВНУТРЕННИЙ КОНФЛИКТ И СТРАТЕГИЯ СУБЛИМАЦИИ
Выдели самый жесткий аспект. Опиши его как сюжетную линию жизни. Дай точечную компенсаторную механику — как направить напряжение в созидательное русло.

ЗАПРЕЩЕНО: использовать сухие формулы типа "Марс в 3 доме дает ссоры с соседями". Переводи на язык следствий. Каждый абзац должен заставлять внутренне содрогнуться от точности попадания. Избегай непонятных слов на английском.

Объем — минимум 2000 символов. Пиши обычным текстом. Не используй Markdown-разметку, звездочки, символы.hash. Только абзацы, разделенные пустой строкой. Только кириллица и знаки препинания."""


def clean_llm_output(text: str) -> str:
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'[*_`]', '', text)
    text = re.sub(r'#{1,6}\s*', '', text)
    text = re.sub(r'[^\u0000-\u007F\u0400-\u04FF\u0500-\u052F\u2DE0-\u2DFF\uA640-\uA69F\u1E00-\u1EFF\u0370-\u03FF\u1F00-\u1FFF\u2000-\u206F\u2E00-\u2E7F\u3000-\u303F\uFE30-\uFE4F\uFF00-\uFFEF\s\n\r.,!?;:\-\u2012\u2013\u2014()\"\'«»/]', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def build_prompt(
    cards: list[int],
    question: str,
    user_name: str,
    zodiac_sign: str,
    birth_time: str | None,
    history: list[dict] | None = None,
) -> list[dict]:
    time_note = ""
    if not birth_time:
        time_note = "\nТочное время рождения неизвестно. Проведи анализ на основе космограммы, полностью игнорируя сетку астрологических домов."
    else:
        time_note = f"\nВремя рождения: {birth_time}. Учитывай астрологические дома."

    system_msg = f"""{TAROT_SYSTEM_PROMPT}

Профиль клиента:
- Имя: {user_name}
- Знак зодиака: {zodiac_sign}
- Дата рождения: {birth_time or 'неизвестно'}
{time_note}

Выпавшие карты: {', '.join(map(str, cards))}"""

    messages = [{"role": "system", "content": system_msg}]

    if history:
        messages.extend(history[-4:])

    messages.append({"role": "user", "content": question})
    return messages


async def stream_prediction(
    cards: list[int],
    question: str,
    user_name: str,
    zodiac_sign: str,
    birth_time: str | None = None,
    history: list[dict] | None = None,
    is_premium: bool = False,
) -> AsyncGenerator[str, None]:
    if not client:
        yield "[Модуль ИИ не настроен. Установите LLM_API_KEY в .env]"
        return

    model = settings.LLM_PREMIUM_MODEL if is_premium else settings.LLM_FREE_MODEL
    messages = build_prompt(cards, question, user_name, zodiac_sign, birth_time, history)

    stream = await client.chat.completions.create(
        model=model,
        messages=messages,
        stream=True,
        max_tokens=1024,
    )

    async for chunk in stream:
        if chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


async def generate_astro_greeting(
    user_name: str,
    zodiac_sign: str,
    birth_date: str,
    birth_time: str | None = None,
    birth_location: str | None = None,
) -> str:
    if not client:
        return (
            f"Привет, {user_name}!\n\n"
            f"Ты — {zodiac_sign}. "
            f"Звёзды говорят, что передо мной интересная личность с глубинным внутренним миром. "
            f"Сегодня космические энергии благоприятствуют тебе — давай узнаем, "
            f"что карты Таро хотят тебе сказать."
        )

    time_note = f"Время рождения: {birth_time}." if birth_time else "Точное время рождения неизвестно."
    location_note = f"Место рождения: {birth_location}." if birth_location else "Место рождения неизвестно."

    messages = [
        {"role": "system", "content": ASTRO_GREETING_PROMPT},
        {"role": "user", "content": f"Имя: {user_name}\nЗнак зодиака: {zodiac_sign}\nДата рождения: {birth_date}\n{time_note}\n{location_note}"},
    ]

    response = await client.chat.completions.create(
        model=settings.LLM_FREE_MODEL,
        messages=messages,
        max_tokens=4096,
    )

    raw = response.choices[0].message.content or (
        f"Привет, {user_name}! Ты — {zodiac_sign}. Давай узнаем, что карты хотят тебе сказать."
    )
    return clean_llm_output(raw)

    raw = response.choices[0].message.content or (
        f"Привет, {user_name}! Ты — {zodiac_sign}. Давай узнаем, что карты хотят тебе сказать."
    )
    return clean_llm_output(raw)

    time_note = f"Время рождения: {birth_time}." if birth_time else "Точное время рождения неизвестно."

    messages = [
        {"role": "system", "content": ASTRO_GREETING_PROMPT},
        {"role": "user", "content": f"Имя: {user_name}\nЗнак зодиака: {zodiac_sign}\nДата рождения: {birth_date}\n{time_note}"},
    ]

    response = await client.chat.completions.create(
        model=settings.LLM_FREE_MODEL,
        messages=messages,
        max_tokens=1024,
    )

    return response.choices[0].message.content or (
        f"Привет, {user_name}! Ты — {zodiac_sign}. Давай узнаем, что карты хотят тебе сказать."
    )
