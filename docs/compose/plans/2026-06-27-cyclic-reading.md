# Cyclic Tarot Reading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current linear tarot flow with a cyclical "ask question → draw 1 card → interpret → repeat" model, max 6 cycles, with server-side card storage and Redis caching.

**Architecture:** State machine with 6 states (IDLE, QUESTION, DRAW, INTERPRET, READY, END). New ReadingCycle table stores each cycle's question/card/interpretation. Redis caches active sessions. Single ReadingScreen component replaces TarotDraw + Chat.

**Tech Stack:** Python FastAPI, SQLAlchemy async, PostgreSQL, Redis (aioredis), React 18 + TypeScript, Vite, Server-Sent Events.

## Global Constraints

- initData must be passed in Authorization header, not query parameter
- HMAC validation must be enforced (no bypass)
- Server-side RNG for card selection (random.sample, 1-78)
- All API responses in Russian
- No Markdown in LLM output (plain text only)
- Rate limit: 10 requests/minute per user on reading endpoints
- Redis TTL: 1 hour for active sessions
- Max 6 cycles per reading

---

## Task 1: Alembic Migration

**Covers:** [S3]

**Files:**
- Create: `backend/alembic/versions/20260627_add_reading_cycle.py`
- Modify: `backend/models/user.py:31-44`

**Interfaces:**
- Consumes: existing TarotSession model
- Produces: ReadingCycle model, extended TarotSession

- [ ] **Step 1: Add cycle_count and status to TarotSession**

```python
# backend/models/user.py — add to TarotSession class
cycle_count: Mapped[int] = mapped_column(Integer, default=0)
status: Mapped[str] = mapped_column(String(50), default="active")
```

- [ ] **Step 2: Create ReadingCycle model**

```python
# backend/models/user.py — new class after TarotSession
class ReadingCycle(Base):
    __tablename__ = "reading_cycles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("tarot_sessions.id", ondelete="CASCADE"))
    cycle_number: Mapped[int] = mapped_column(Integer)
    question: Mapped[str] = mapped_column(Text)
    card_id: Mapped[int] = mapped_column(Integer)
    interpretation: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc))

    session: Mapped["TarotSession"] = relationship(back_populates="cycles")
```

- [ ] **Step 3: Add relationship to TarotSession**

```python
# backend/models/user.py — add to TarotSession class
cycles: Mapped[list["ReadingCycle"]] = relationship(back_populates="session")
```

- [ ] **Step 4: Generate migration**

Run: `cd backend && alembic revision --autogenerate -m "add reading_cycles table and cycle_count to tarot_sessions"`

- [ ] **Step 5: Verify migration**

Run: `cd backend && alembic upgrade head`

- [ ] **Step 6: Commit**

```bash
git add backend/models/user.py backend/alembic/versions/
git commit -m "feat: add ReadingCycle model and extend TarotSession with cycle_count/status"
```

---

## Task 2: Redis Service

**Covers:** [S7]

**Files:**
- Create: `backend/services/redis.py`
- Modify: `backend/config.py:1-18`
- Modify: `docker-compose.yml:35-44`

**Interfaces:**
- Consumes: REDIS_URL from config
- Produces: `RedisService` class with get/set/delete/exists methods

- [ ] **Step 1: Add REDIS_URL to config**

```python
# backend/config.py — add to Settings class
REDIS_URL: str = "redis://localhost:6379/0"
```

- [ ] **Step 2: Add Redis to docker-compose.yml**

```yaml
# docker-compose.yml — add new service
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redisdata:/data

# Add to volumes section at bottom:
volumes:
  pgdata:
  redisdata:
```

- [ ] **Step 3: Create RedisService**

```python
# backend/services/redis.py
import json
import logging
from typing import Any, Optional

import redis.asyncio as redis

from config import settings

logger = logging.getLogger(__name__)

_client: Optional[redis.Redis] = None


async def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _client


async def close_redis():
    global _client
    if _client:
        await _client.close()
        _client = None


class RedisService:
    PREFIX = "reading:"

    @staticmethod
    def _key(session_id: str) -> str:
        return f"{RedisService.PREFIX}{session_id}"

    @staticmethod
    async def get(session_id: str) -> Optional[dict]:
        r = await get_redis()
        data = await r.get(RedisService._key(session_id))
        if data:
            return json.loads(data)
        return None

    @staticmethod
    async def set(session_id: str, data: dict, ttl: int = 3600):
        r = await get_redis()
        await r.set(RedisService._key(session_id), json.dumps(data), ex=ttl)

    @staticmethod
    async def delete(session_id: str):
        r = await get_redis()
        await r.delete(RedisService._key(session_id))

    @staticmethod
    async def exists(session_id: str) -> bool:
        r = await get_redis()
        return await r.exists(RedisService._key(session_id)) > 0
```

- [ ] **Step 4: Add Redis to backend dependencies**

```bash
cd backend && pip install redis
echo "redis>=5.0.0" >> requirements.txt
```

- [ ] **Step 5: Update docker-compose backend depends_on**

```yaml
# docker-compose.yml — backend service
  backend:
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started
```

- [ ] **Step 6: Commit**

```bash
git add backend/services/redis.py backend/config.py docker-compose.yml backend/requirements.txt
git commit -m "feat: add Redis service for session caching"
```

---

## Task 3: Reading State Machine

**Covers:** [S2]

**Files:**
- Create: `backend/services/reading.py`

**Interfaces:**
- Consumes: RedisService, ReadingCycle model, draw_cards function
- Produces: `ReadingService` class with start/ask/draw/get_state methods

- [ ] **Step 1: Create ReadingService**

```python
# backend/services/reading.py
import random
import logging
from enum import Enum
from typing import Optional

from services.redis import RedisService

logger = logging.getLogger(__name__)


class ReadingState(str, Enum):
    IDLE = "idle"
    QUESTION = "question"
    DRAW = "draw"
    INTERPRET = "interpret"
    READY = "ready"
    END = "end"


class ReadingService:
    MAX_CYCLES = 6

    @staticmethod
    def _default_data(session_id: str, user_id: int) -> dict:
        return {
            "session_id": session_id,
            "user_id": user_id,
            "state": ReadingState.IDLE,
            "cycle_count": 0,
            "current_question": None,
            "current_card": None,
            "cycles": [],
        }

    @staticmethod
    async def start(session_id: str, user_id: int) -> dict:
        data = ReadingService._default_data(session_id, user_id)
        await RedisService.set(session_id, data)
        return data

    @staticmethod
    async def get_state(session_id: str) -> Optional[dict]:
        return await RedisService.get(session_id)

    @staticmethod
    async def ask(session_id: str, question: str) -> dict:
        data = await RedisService.get(session_id)
        if not data:
            raise ValueError("Session not found")
        if data["state"] not in (ReadingState.IDLE, ReadingState.READY):
            raise ValueError(f"Cannot ask question in state: {data['state']}")
        if data["cycle_count"] >= ReadingService.MAX_CYCLES:
            raise ValueError("Maximum cycles reached")

        data["current_question"] = question
        data["state"] = ReadingState.QUESTION
        await RedisService.set(session_id, data)
        return data

    @staticmethod
    async def draw(session_id: str) -> dict:
        data = await RedisService.get(session_id)
        if not data:
            raise ValueError("Session not found")
        if data["state"] != ReadingState.QUESTION:
            raise ValueError(f"Cannot draw card in state: {data['state']}")

        card_id = random.sample(range(1, 79), 1)[0]
        data["current_card"] = card_id
        data["state"] = ReadingState.DRAW
        await RedisService.set(session_id, data)
        return data

    @staticmethod
    async def mark_interpreting(session_id: str) -> dict:
        data = await RedisService.get(session_id)
        if not data:
            raise ValueError("Session not found")
        data["state"] = ReadingState.INTERPRET
        await RedisService.set(session_id, data)
        return data

    @staticmethod
    async def complete_cycle(session_id: str, interpretation: str) -> dict:
        data = await RedisService.get(session_id)
        if not data:
            raise ValueError("Session not found")

        cycle = {
            "cycle_number": data["cycle_count"] + 1,
            "question": data["current_question"],
            "card_id": data["current_card"],
            "interpretation": interpretation,
        }
        data["cycles"].append(cycle)
        data["cycle_count"] += 1
        data["current_question"] = None
        data["current_card"] = None

        if data["cycle_count"] >= ReadingService.MAX_CYCLES:
            data["state"] = ReadingState.END
        else:
            data["state"] = ReadingState.READY

        await RedisService.set(session_id, data)
        return data

    @staticmethod
    async def end(session_id: str) -> dict:
        data = await RedisService.get(session_id)
        if not data:
            raise ValueError("Session not found")
        data["state"] = ReadingState.END
        await RedisService.set(session_id, data)
        return data
```

- [ ] **Step 2: Commit**

```bash
git add backend/services/reading.py
git commit -m "feat: add ReadingService state machine"
```

---

## Task 4: Pydantic Schemas

**Covers:** [S4]

**Files:**
- Modify: `backend/schemas/tarot.py`

**Interfaces:**
- Consumes: ReadingState from reading.py
- Produces: Request/Response schemas for all reading endpoints

- [ ] **Step 1: Add reading schemas**

```python
# backend/schemas/tarot.py — add after existing schemas

class ReadingStartRequest(BaseModel):
    layout_type: str = "1_card"

class ReadingStartResponse(BaseModel):
    session_id: str
    state: str

class ReadingAskRequest(BaseModel):
    session_id: str
    question: str

class ReadingDrawRequest(BaseModel):
    session_id: str

class ReadingDrawResponse(BaseModel):
    card_id: int
    card_name: str
    state: str

class ReadingInterpretRequest(BaseModel):
    session_id: str

class ReadingSynthesisRequest(BaseModel):
    session_id: str

class ReadingStateResponse(BaseModel):
    session_id: str
    state: str
    cycle_count: int
    max_cycles: int
    cycles: list[dict]
    current_question: str | None = None
    current_card: int | None = None
```

- [ ] **Step 2: Commit**

```bash
git add backend/schemas/tarot.py
git commit -m "feat: add Pydantic schemas for reading endpoints"
```

---

## Task 5: LLM Prompts

**Covers:** [S6]

**Files:**
- Modify: `backend/services/llm.py:14-18, 57-87`

**Interfaces:**
- Consumes: cardMap data (card IDs to names)
- Produces: `build_reading_prompt()`, `build_synthesis_prompt()` functions

- [ ] **Step 1: Add reading system prompt**

```python
# backend/services/llm.py — add after TAROT_SYSTEM_PROMPT

READING_SYSTEM_PROMPT = """Ты — опытный и эмпатичный таролог-интуит. 
Твоя роль — интерпретировать выпавшую карту Таро в контексте вопроса клиента.
Говори на русском языке. Будь конкретным, используй метафоры.
Связывай текущую карту с предыдущими циклами расклада, если они есть.
Не давай медицинских или юридических советов.
Пиши обычным текстом. Не используй Markdown-разметку."""

SYNTHESIS_SYSTEM_PROMPT = """Ты — опытный таролог-интуит.
Подведи итог расклада, проанализировав все выпавшие карты и вопросы клиента.
Выяви общие связи и закономерности между циклами.
Дай целостную рекомендацию.
Говори на русском языке. Пиши 3-5 абзацев.
Не используй Markdown-разметку."""
```

- [ ] **Step 2: Add card name mapping (backend)**

```python
# backend/services/llm.py — add at top

MAJOR_ARCANA = [
    "Шут", "Маг", "Жрица", "Императрица", "Император",
    "Иерофант", "Влюблённые", "Колесница", "Сила", "Отшельник",
    "Колесо Фортуны", "Справедливость", "Повешенный", "Смерть",
    "Умеренность", "Дьявол", "Башня", "Звезда", "Луна",
    "Солнце", "Суд", "Мир"
]

MINOR_RANKS = ["Туз", "2", "3", "4", "5", "6", "7", "8", "9", "10", "Паж", "Рыцарь", "Королева", "Король"]
SUIT_NAMES = {"cups": "Кубки", "pents": "Пентакли", "swords": "Мечи", "wands": "Жезлы"}
SUITS_ORDER = ["cups", "pents", "swords", "wands"]


def get_card_name(card_id: int) -> str:
    if 1 <= card_id <= 22:
        return MAJOR_ARCANA[card_id - 1]
    minor_index = card_id - 23
    suit_index = minor_index // 14
    rank_index = minor_index % 14
    suit = SUIT_NAMES[SUITS_ORDER[suit_index]]
    return f"{MINOR_RANKS[rank_index]} {suit}"
```

- [ ] **Step 3: Add build_reading_prompt**

```python
# backend/services/llm.py — add after build_prompt

def build_reading_prompt(
    question: str,
    card_id: int,
    user_name: str,
    zodiac_sign: str,
    birth_time: str | None,
    history_cycles: list[dict] | None = None,
) -> list[dict]:
    card_name = get_card_name(card_id)

    profile = f"""Профиль клиента:
- Имя: {user_name}
- Знак зодиака: {zodiac_sign}
- Время рождения: {birth_time or 'неизвестно'}"""

    history_text = ""
    if history_cycles:
        history_text = "\n\nИстория расклада:\n"
        for c in history_cycles:
            prev_card = get_card_name(c["card_id"])
            history_text += f"[Цикл {c['cycle_number']}] Вопрос: {c['question']} | Карта: {prev_card}\n"

    system_msg = f"""{READING_SYSTEM_PROMPT}

{profile}
{history_text}

Текущий цикл:
Вопрос: {question}
Карта: {card_name} (ID: {card_id})

Дай глубокую интерпретацию выпавшей карты в контексте вопроса."""

    return [{"role": "system", "content": system_msg}]


def build_synthesis_prompt(
    cycles: list[dict],
    user_name: str,
    zodiac_sign: str,
) -> list[dict]:
    cycles_text = ""
    for c in cycles:
        card = get_card_name(c["card_id"])
        cycles_text += f"[Цикл {c['cycle_number']}] Вопрос: {c['question']} | Карта: {card}\n"

    system_msg = f"""{SYNTHESIS_SYSTEM_PROMPT}

Профиль клиента: {user_name}, {zodiac_sign}

Все циклы расклада:
{cycles_text}

Сформируй общий вывод, выявив связи между картами и вопросами."""

    return [{"role": "system", "content": system_msg}]
```

- [ ] **Step 4: Commit**

```bash
git add backend/services/llm.py
git commit -m "feat: add reading and synthesis prompts with card name mapping"
```

---

## Task 6: API Endpoints

**Covers:** [S4]

**Files:**
- Create: `backend/routes/reading.py`
- Modify: `backend/routes/__init__.py`
- Modify: `backend/main.py:14, 49-52`

**Interfaces:**
- Consumes: ReadingService, build_reading_prompt, build_synthesis_prompt, stream_prediction, validate_telegram_init_data
- Produces: 6 HTTP endpoints

- [ ] **Step 1: Create reading router**

```python
# backend/routes/reading.py
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import TarotSession, ReadingCycle, User
from schemas import (
    ReadingStartRequest, ReadingStartResponse,
    ReadingAskRequest, ReadingDrawRequest, ReadingDrawResponse,
    ReadingInterpretRequest, ReadingSynthesisRequest, ReadingStateResponse,
)
from services import validate_telegram_init_data
from services.reading import ReadingService
from services.llm import build_reading_prompt, build_synthesis_prompt, stream_prediction, get_card_name

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/tarot/reading", tags=["reading"])


async def _get_user(initData: str, db: AsyncSession):
    user_data = validate_telegram_init_data(initData)
    if not user_data:
        raise HTTPException(status_code=401, detail="Invalid Telegram data")
    result = await db.execute(select(User).where(User.telegram_id == user_data["id"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user, user_data["id"]


@router.post("/start", response_model=ReadingStartResponse)
async def reading_start(req: ReadingStartRequest, initData: str = "", db: AsyncSession = Depends(get_db)):
    user, telegram_id = await _get_user(initData, db)

    import uuid
    session_id = str(uuid.uuid4())
    session = TarotSession(id=session_id, user_id=telegram_id, status="active", cycle_count=0)
    db.add(session)
    await db.commit()

    data = await ReadingService.start(session_id, telegram_id)
    return ReadingStartResponse(session_id=session_id, state=data["state"])


@router.post("/ask")
async def reading_ask(req: ReadingAskRequest, initData: str = "", db: AsyncSession = Depends(get_db)):
    await _get_user(initData, db)
    try:
        data = await ReadingService.ask(req.session_id, req.question)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"state": data["state"], "cycle_count": data["cycle_count"]}


@router.post("/draw", response_model=ReadingDrawResponse)
async def reading_draw(req: ReadingDrawRequest, initData: str = "", db: AsyncSession = Depends(get_db)):
    await _get_user(initData, db)
    try:
        data = await ReadingService.draw(req.session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ReadingDrawResponse(
        card_id=data["current_card"],
        card_name=get_card_name(data["current_card"]),
        state=data["state"],
    )


@router.post("/interpret")
async def reading_interpret(request: Request, req: ReadingInterpretRequest, initData: str = "", db: AsyncSession = Depends(get_db)):
    user, telegram_id = await _get_user(initData, db)

    data = await ReadingService.get_state(req.session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Session not found")

    await ReadingService.mark_interpreting(req.session_id)

    messages = build_reading_prompt(
        question=data["current_question"],
        card_id=data["current_card"],
        user_name=user.real_name,
        zodiac_sign=user.zodiac_sign,
        birth_time=str(user.birth_time) if user.birth_time else None,
        history_cycles=data.get("cycles", []),
    )

    full_response = []

    async def event_stream():
        async for chunk in stream_prediction(
            cards=[data["current_card"]],
            question=data["current_question"],
            user_name=user.real_name,
            zodiac_sign=user.zodiac_sign,
            birth_time=str(user.birth_time) if user.birth_time else None,
            history=None,
            is_premium=False,
            custom_messages=messages,
        ):
            full_response.append(chunk)
            yield f"data: {json.dumps({'text': chunk})}\n\n"

        interpretation = "".join(full_response)
        completed = await ReadingService.complete_cycle(req.session_id, interpretation)

        cycle = completed["cycles"][-1]
        cycle_obj = ReadingCycle(
            session_id=req.session_id,
            cycle_number=cycle["cycle_number"],
            question=cycle["question"],
            card_id=cycle["card_id"],
            interpretation=cycle["interpretation"],
        )
        db.add(cycle_obj)

        result = await db.execute(select(TarotSession).where(TarotSession.id == req.session_id))
        session = result.scalar_one_or_none()
        if session:
            session.cycle_count = completed["cycle_count"]
            if completed["state"] == "end":
                session.status = "completed"
        await db.commit()

        yield f"data: {json.dumps({'state': completed['state'], 'cycle_count': completed['cycle_count']})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/synthesis")
async def reading_synthesis(request: Request, req: ReadingSynthesisRequest, initData: str = "", db: AsyncSession = Depends(get_db)):
    user, telegram_id = await _get_user(initData, db)

    data = await ReadingService.get_state(req.session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Session not found")

    await ReadingService.end(req.session_id)

    messages = build_synthesis_prompt(
        cycles=data.get("cycles", []),
        user_name=user.real_name,
        zodiac_sign=user.zodiac_sign,
    )

    full_response = []

    async def event_stream():
        async for chunk in stream_prediction(
            cards=[],
            question="",
            user_name=user.real_name,
            zodiac_sign=user.zodiac_sign,
            birth_time=None,
            history=None,
            is_premium=False,
            custom_messages=messages,
        ):
            full_response.append(chunk)
            yield f"data: {json.dumps({'text': chunk})}\n\n"

        result = await db.execute(select(TarotSession).where(TarotSession.id == req.session_id))
        session = result.scalar_one_or_none()
        if session:
            session.status = "completed"
        await db.commit()

        await ReadingService.delete(req.session_id)
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/state", response_model=ReadingStateResponse)
async def reading_state(session_id: str, initData: str = "", db: AsyncSession = Depends(get_db)):
    await _get_user(initData, db)

    data = await ReadingService.get_state(session_id)
    if not data:
        result = await db.execute(
            select(TarotSession).where(TarotSession.id == session_id)
        )
        session = result.scalar_one_or_none()
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        cycles_result = await db.execute(
            select(ReadingCycle).where(ReadingCycle.session_id == session_id).order_by(ReadingCycle.cycle_number)
        )
        db_cycles = cycles_result.scalars().all()
        data = {
            "session_id": session_id,
            "state": "end" if session.status == "completed" else "idle",
            "cycle_count": session.cycle_count,
            "max_cycles": ReadingService.MAX_CYCLES,
            "cycles": [{"cycle_number": c.cycle_number, "question": c.question, "card_id": c.card_id, "interpretation": c.interpretation} for c in db_cycles],
        }

    return ReadingStateResponse(
        session_id=data["session_id"],
        state=data["state"],
        cycle_count=data["cycle_count"],
        max_cycles=ReadingService.MAX_CYCLES,
        cycles=data.get("cycles", []),
        current_question=data.get("current_question"),
        current_card=data.get("current_card"),
    )
```

- [ ] **Step 2: Register router**

```python
# backend/routes/__init__.py
from routes.astrology import router as astrology_router
from routes.tarot import router as tarot_router
from routes.sessions import router as sessions_router
from routes.reading import router as reading_router

__all__ = ["astrology_router", "tarot_router", "sessions_router", "reading_router"]
```

```python
# backend/main.py — line 14
from routes import astrology_router, tarot_router, sessions_router, reading_router

# line 49-52
app.include_router(astrology_router)
app.include_router(tarot_router)
app.include_router(sessions_router)
app.include_router(reading_router)
```

- [ ] **Step 3: Add custom_messages parameter to stream_prediction**

```python
# backend/services/llm.py — modify stream_prediction signature
async def stream_prediction(
    cards: list[int],
    question: str,
    user_name: str,
    zodiac_sign: str,
    birth_time: str | None = None,
    history: list[dict] | None = None,
    is_premium: bool = False,
    custom_messages: list[dict] | None = None,
) -> AsyncGenerator[str, None]:
    if not client:
        yield "[Модуль ИИ не настроен. Установите LLM_API_KEY в .env]"
        return

    model = settings.LLM_PREMIUM_MODEL if is_premium else settings.LLM_FREE_MODEL
    messages = custom_messages if custom_messages else build_prompt(cards, question, user_name, zodiac_sign, birth_time, history)

    stream = await client.chat.completions.create(
        model=model,
        messages=messages,
        stream=True,
        max_tokens=1024,
    )

    async for chunk in stream:
        if chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content
```

- [ ] **Step 4: Commit**

```bash
git add backend/routes/reading.py backend/routes/__init__.py backend/main.py backend/services/llm.py
git commit -m "feat: add reading API endpoints with state machine integration"
```

---

## Task 7: ReadingScreen Component

**Covers:** [S5]

**Files:**
- Create: `frontend/src/components/ReadingScreen.tsx`
- Modify: `frontend/src/App.tsx:10, 50-60, 74-81, 93-121`
- Modify: `frontend/src/api/client.ts` (add apiGet function)
- Modify: `frontend/src/styles/app.css` (add reading styles)

**Interfaces:**
- Consumes: apiPost, apiStream, useTelegram, getCardImage, getCardName
- Produces: ReadingScreen component

- [ ] **Step 1: Create ReadingScreen component**

```tsx
// frontend/src/components/ReadingScreen.tsx
import { useState, useEffect, useRef } from 'react';
import { apiPost, apiStream, apiGet } from '../api/client';
import { useTelegram } from '../hooks/useTelegram';
import { getCardImage, getCardName } from '../utils/cardMap';

interface Cycle {
  cycle_number: number;
  question: string;
  card_id: number;
  interpretation: string;
}

interface ReadingState {
  session_id: string;
  state: string;
  cycle_count: number;
  max_cycles: number;
  cycles: Cycle[];
  current_question: string | null;
  current_card: number | null;
}

interface Props {
  onNewReading: () => void;
}

export default function ReadingScreen({ onNewReading }: Props) {
  const { initData } = useTelegram();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [reading, setReading] = useState<ReadingState | null>(null);
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [streamingText, setStreamingText] = useState('');
  const [error, setError] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    startReading();
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [reading, streamingText]);

  const startReading = async () => {
    try {
      const res = await apiPost<{ session_id: string; state: string }>(
        '/api/v1/tarot/reading/start',
        { layout_type: '1_card' },
        initData,
      );
      setSessionId(res.session_id);
      setReading({
        session_id: res.session_id,
        state: 'idle',
        cycle_count: 0,
        max_cycles: 6,
        cycles: [],
        current_question: null,
        current_card: null,
      });
    } catch {
      setError('Не удалось начать расклад');
    }
  };

  const handleAsk = async () => {
    if (!question.trim() || !sessionId) return;
    setLoading(true);
    setError('');
    try {
      await apiPost('/api/v1/tarot/reading/ask', { session_id: sessionId, question: question.trim() }, initData);
      setReading(prev => prev ? { ...prev, state: 'question', current_question: question.trim() } : null);
      setQuestion('');
    } catch {
      setError('Не удалось отправить вопрос');
    } finally {
      setLoading(false);
    }
  };

  const handleDraw = async () => {
    if (!sessionId) return;
    setLoading(true);
    try {
      const res = await apiPost<{ card_id: number; card_name: string; state: string }>(
        '/api/v1/tarot/reading/draw',
        { session_id: sessionId },
        initData,
      );
      setReading(prev => prev ? { ...prev, state: 'draw', current_card: res.card_id } : null);
      setTimeout(() => handleInterpret(), 1500);
    } catch {
      setError('Не удалось вытянуть карту');
    } finally {
      setLoading(false);
    }
  };

  const handleInterpret = async () => {
    if (!sessionId) return;
    setLoading(true);
    setStreamingText('');
    try {
      await apiStream(
        '/api/v1/tarot/reading/interpret',
        { session_id: sessionId },
        initData,
        (chunk) => setStreamingText(prev => prev + chunk),
        () => {
          setLoading(false);
          refreshState();
        },
      );
    } catch {
      setError('Ошибка при генерации интерпретации');
      setLoading(false);
    }
  };

  const handleSynthesis = async () => {
    if (!sessionId) return;
    setLoading(true);
    setStreamingText('');
    try {
      await apiStream(
        '/api/v1/tarot/reading/synthesis',
        { session_id: sessionId },
        initData,
        (chunk) => setStreamingText(prev => prev + chunk),
        () => {
          setLoading(false);
          refreshState();
        },
      );
    } catch {
      setError('Ошибка при генерации синтеза');
      setLoading(false);
    }
  };

  const refreshState = async () => {
    if (!sessionId) return;
    try {
      const res = await apiGet<ReadingState>(
        `/api/v1/tarot/reading/state?session_id=${sessionId}`,
        initData,
      );
      setReading(res);
      setStreamingText('');
    } catch {
      // ignore
    }
  };

  const handleNewQuestion = () => {
    setReading(prev => prev ? { ...prev, state: 'idle', current_question: null, current_card: null } : null);
  };

  if (error) {
    return (
      <div className="reading-screen">
        <div className="error">{error}</div>
        <button onClick={() => { setError(''); refreshState(); }}>Повторить</button>
      </div>
    );
  }

  if (!reading) {
    return <div className="reading-screen"><div className="spinner" /></div>;
  }

  return (
    <div className="reading-screen">
      <div className="reading-history">
        {reading.cycles.map((cycle) => (
          <div key={cycle.cycle_number} className="reading-cycle">
            <div className="cycle-header">Цикл {cycle.cycle_number}</div>
            <div className="cycle-question">Вопрос: {cycle.question}</div>
            <div className="cycle-card">
              <img src={getCardImage(cycle.card_id)} alt={getCardName(cycle.card_id)} className="cycle-card-img" />
              <span>{getCardName(cycle.card_id)}</span>
            </div>
            <div className="cycle-interpretation">{cycle.interpretation}</div>
          </div>
        ))}
      </div>

      <div className="reading-current">
        {reading.state === 'idle' && (
          <div className="input-area">
            <input
              type="text"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Задайте вопрос картам..."
              disabled={loading}
              onKeyDown={(e) => e.key === 'Enter' && handleAsk()}
            />
            <button onClick={handleAsk} disabled={loading || !question.trim()}>
              {loading ? '...' : 'Отправить'}
            </button>
          </div>
        )}

        {reading.state === 'question' && (
          <button className="draw-btn" onClick={handleDraw} disabled={loading}>
            {loading ? 'Вытягиваю...' : 'Вытянуть карту'}
          </button>
        )}

        {reading.state === 'draw' && reading.current_card && (
          <div className="card-reveal">
            <img src={getCardImage(reading.current_card)} alt={getCardName(reading.current_card)} className="card-reveal-img" />
            <p>{getCardName(reading.current_card)}</p>
          </div>
        )}

        {(reading.state === 'interpret' || (loading && streamingText)) && (
          <div className="streaming-text">
            {streamingText || <span className="spinner" />}
          </div>
        )}

        {reading.state === 'ready' && (
          <div className="action-buttons">
            {reading.cycle_count < reading.max_cycles && (
              <button onClick={handleNewQuestion}>Ещё вопрос</button>
            )}
            <button onClick={handleSynthesis}>Завершить расклад</button>
          </div>
        )}

        {reading.state === 'end' && (
          <div className="reading-end">
            <p>Расклад завершён</p>
            <button onClick={onNewReading}>Новый расклад</button>
          </div>
        )}
      </div>

      <div className="reading-progress">
        Цикл {reading.cycle_count} из {reading.max_cycles}
      </div>

      <div ref={messagesEndRef} />
    </div>
  );
}
```

- [ ] **Step 2: Update App.tsx to use ReadingScreen**

```tsx
// frontend/src/App.tsx — replace entire file
import { useState, useEffect } from 'react';
import { useTelegram } from './hooks/useTelegram';
import ReadingScreen from './components/ReadingScreen';

type Screen = 'reading';

interface AppState {
  screen: Screen;
}

const STORAGE_KEY = 'morlana_reading_state';

function App() {
  const [state, setState] = useState<AppState>({ screen: 'reading' });

  const handleNewReading = () => {
    setState({ screen: 'reading' });
  };

  return (
    <div className="app">
      {state.screen === 'reading' && (
        <ReadingScreen onNewReading={handleNewReading} />
      )}
    </div>
  );
}

export default App;
```

- [ ] **Step 3: Add apiGet to client.ts**

```typescript
// frontend/src/api/client.ts — add after apiPost function

export async function apiGet<T>(path: string, initData?: string): Promise<T> {
  const url = buildUrl(path, initData);
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`API error: ${res.status}`);
  }
  return res.json();
}
```

- [ ] **Step 4: Add reading styles to app.css**

```css
/* frontend/src/styles/app.css — add at end */

.reading-screen {
  max-width: 480px;
  margin: 0 auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  height: 100vh;
}

.reading-history {
  flex: 1;
  overflow-y: auto;
  margin-bottom: 16px;
}

.reading-cycle {
  background: rgba(255, 255, 255, 0.05);
  border-radius: 12px;
  padding: 12px;
  margin-bottom: 12px;
}

.cycle-header {
  font-size: 12px;
  color: #888;
  margin-bottom: 8px;
}

.cycle-question {
  font-style: italic;
  margin-bottom: 8px;
}

.cycle-card {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.cycle-card-img {
  width: 40px;
  height: 67px;
  border-radius: 4px;
}

.cycle-interpretation {
  font-size: 14px;
  line-height: 1.5;
}

.reading-current {
  min-height: 120px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}

.draw-btn {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  border: none;
  padding: 16px 32px;
  border-radius: 12px;
  font-size: 16px;
  cursor: pointer;
}

.card-reveal {
  text-align: center;
}

.card-reveal-img {
  width: 120px;
  height: 200px;
  border-radius: 8px;
}

.streaming-text {
  width: 100%;
  padding: 16px;
  line-height: 1.6;
  white-space: pre-wrap;
}

.action-buttons {
  display: flex;
  gap: 12px;
}

.action-buttons button {
  padding: 12px 24px;
  border-radius: 8px;
  border: none;
  cursor: pointer;
}

.reading-progress {
  text-align: center;
  padding: 8px;
  color: #888;
  font-size: 12px;
}

.reading-end {
  text-align: center;
}
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ReadingScreen.tsx frontend/src/App.tsx frontend/src/api/client.ts frontend/src/styles/app.css
git commit -m "feat: add ReadingScreen component with cyclical reading flow"
```

---

## Task 8: HMAC Fix

**Covers:** [S9]

**Files:**
- Modify: `backend/services/auth.py:64`

**Interfaces:**
- Consumes: existing auth function
- Produces: removed bypass

- [ ] **Step 1: Remove HMAC bypass**

```python
# backend/services/auth.py — line 64
# DELETE these two lines:
# logger.warning("HMAC mismatch — returning user_data anyway for debug")
# return user_data
```

- [ ] **Step 2: Commit**

```bash
git add backend/services/auth.py
git commit -m "fix: remove HMAC validation bypass in auth.py"
```

---

## Task 9: Rate Limiting

**Covers:** [S9]

**Files:**
- Modify: `backend/routes/reading.py` (add limiter)
- Modify: `backend/main.py:20`

**Interfaces:**
- Consumes: Limiter from slowapi
- Produces: rate-limited reading endpoints

- [ ] **Step 1: Add rate limiter to reading routes**

```python
# backend/routes/reading.py — add at top
from main import limiter

# Add @limiter.limit("10/minute") decorator to each reading endpoint
```

- [ ] **Step 2: Commit**

```bash
git add backend/routes/reading.py
git commit -m "feat: add rate limiting to reading endpoints"
```

---

## Task 10: InitData in Headers

**Covers:** [S9]

**Files:**
- Modify: `frontend/src/api/client.ts` (add Authorization header)
- Modify: `backend/services/auth.py` (read from header)
- Modify: `backend/routes/reading.py` (read from header)

**Interfaces:**
- Consumes: existing auth flow
- Produces: initData in Authorization header

- [ ] **Step 1: Update client.ts to use Authorization header**

```typescript
// frontend/src/api/client.ts — modify buildUrl and apiPost/apiGet/apiStream

function buildHeaders(initData?: string): Record<string, string> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (initData) {
    headers['Authorization'] = `Bearer ${initData}`;
  }
  return headers;
}

export async function apiPost<T>(path: string, body: Record<string, unknown>, initData?: string): Promise<T> {
  const url = buildUrl(path);
  const res = await fetch(url, {
    method: 'POST',
    headers: buildHeaders(initData),
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function apiGet<T>(path: string, initData?: string): Promise<T> {
  const url = buildUrl(path);
  const res = await fetch(url, {
    headers: buildHeaders(initData),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}
```

- [ ] **Step 2: Update reading routes to read from header**

```python
# backend/routes/reading.py — add helper
async def _get_init_data(request: Request, initData: str = "") -> str:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return initData
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/client.ts backend/routes/reading.py
git commit -m "feat: move initData to Authorization header"
```

---

## Task 11: Stub for Other Spreads

**Covers:** [S8]

**Files:**
- Modify: `backend/routes/tarot.py:51-61`

**Interfaces:**
- Consumes: existing draw endpoint
- Produces: 501 response for non-1-card draws

- [ ] **Step 1: Add stub to draw endpoint**

```python
# backend/routes/tarot.py — modify tarot_draw function
@router.post("/draw", response_model=DrawResponse)
async def tarot_draw(req: DrawRequest, initData: str = ""):
    if req.count != 1:
        raise HTTPException(status_code=501, detail="Другие расклады скоро будут доступны")
    # ... existing code for single card
```

- [ ] **Step 2: Commit**

```bash
git add backend/routes/tarot.py
git commit -m "feat: stub draw endpoint for non-1-card spreads"
```

---

## Task 12: Final Verification

**Covers:** All sections

**Files:**
- None (verification only)

- [ ] **Step 1: Rebuild and start**

```bash
docker compose up --build -d
```

- [ ] **Step 2: Health check**

```bash
curl http://localhost:8000/health
```

- [ ] **Step 3: Test reading flow**

```bash
# Start reading
curl -X POST http://localhost:8000/api/v1/tarot/reading/start -H "Content-Type: application/json" -d '{"layout_type":"1_card"}'

# Ask question (replace SESSION_ID)
curl -X POST http://localhost:8000/api/v1/tarot/reading/ask -H "Content-Type: application/json" -d '{"session_id":"SESSION_ID","question":"Что меня ждёт в любви?"}'

# Draw card
curl -X POST http://localhost:8000/api/v1/tarot/reading/draw -H "Content-Type: application/json" -d '{"session_id":"SESSION_ID"}'

# Get state
curl "http://localhost:8000/api/v1/tarot/reading/state?session_id=SESSION_ID"
```

- [ ] **Step 4: Open frontend**

Open http://localhost:3000 in browser. Verify ReadingScreen loads.

- [ ] **Step 5: Test HMAC**

```bash
curl -X POST http://localhost:8000/api/v1/tarot/reading/start -H "Content-Type: application/json" -d '{"layout_type":"1_card"}'
# Should return 401
```

- [ ] **Step 6: Commit verification**

```bash
git add -A
git commit -m "chore: verify reading flow works end-to-end"
```
