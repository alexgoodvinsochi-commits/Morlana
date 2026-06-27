import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Header
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from rate_limiter import limiter
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from models import User
from schemas import (
    ReadingAskRequest,
    ReadingDrawRequest,
    ReadingDrawResponse,
    ReadingInterpretRequest,
    ReadingNextRequest,
    ReadingStartRequest,
    ReadingStartResponse,
    ReadingStateResponse,
    ReadingSynthesisRequest,
)
from services import (
    draw_cards,
    reading_service,
    stream_prediction,
    validate_telegram_init_data,
)
from services.llm import (
    build_reading_prompt,
    build_synthesis_prompt,
    get_card_name,
)
from services.redis import redis_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tarot/reading", tags=["reading"])


def _cycle_data_key(session_id: str) -> str:
    return f"reading:{session_id}:cycle_data"


def _current_question_key(session_id: str) -> str:
    return f"reading:{session_id}:question"


def _current_card_key(session_id: str) -> str:
    return f"reading:{session_id}:card"


async def _get_user_from_init_data(init_data: str, db: AsyncSession) -> User:
    user_data = validate_telegram_init_data(init_data)
    if not user_data:
        raise HTTPException(status_code=401, detail="Invalid Telegram data")
    result = await db.execute(select(User).where(User.telegram_id == user_data["id"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def _require_init_data(init_data: str) -> dict:
    user_data = validate_telegram_init_data(init_data)
    if not user_data:
        raise HTTPException(status_code=401, detail="Invalid Telegram data")
    return user_data


async def _get_init_data(authorization: str = Header(default="")) -> str:
    if settings.DEV_MODE:
        if not authorization.startswith("Bearer "):
            return "dev"
        return authorization[7:]
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    return authorization[7:]


@router.post("/start", response_model=ReadingStartResponse)
@limiter.limit("10/minute")
async def reading_start(
    request: Request, req: ReadingStartRequest, initData: str = Depends(_get_init_data), db: AsyncSession = Depends(get_db)
):
    await _get_user_from_init_data(initData, db)
    session_id = str(uuid.uuid4())
    state = await reading_service.start(session_id)
    await redis_service.set(_cycle_data_key(session_id), [])
    logger.info("Reading started: session=%s", session_id)
    return ReadingStartResponse(session_id=session_id, state=state.value)


@router.post("/ask")
@limiter.limit("10/minute")
async def reading_ask(
    request: Request, req: ReadingAskRequest, initData: str = Depends(_get_init_data)
):
    _require_init_data(initData)
    state = await reading_service.get_state(req.session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Reading not found")

    await reading_service.ask(req.session_id)
    await redis_service.set(_current_question_key(req.session_id), req.question)
    new_state = await reading_service.get_state(req.session_id)
    return {"session_id": req.session_id, "state": new_state.value}


@router.post("/next")
@limiter.limit("10/minute")
async def reading_next(
    request: Request, req: ReadingNextRequest, initData: str = Depends(_get_init_data)
):
    _require_init_data(initData)
    state = await reading_service.get_state(req.session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Reading not found")
    if state != ReadingState.READY:
        raise HTTPException(status_code=400, detail=f"Cannot start new cycle in state: {state.value}")

    await reading_service.start_new_cycle(req.session_id)
    new_state = await reading_service.get_state(req.session_id)
    return {"session_id": req.session_id, "state": new_state.value}


@router.post("/draw", response_model=ReadingDrawResponse)
@limiter.limit("10/minute")
async def reading_draw(
    request: Request, req: ReadingDrawRequest, initData: str = Depends(_get_init_data)
):
    _require_init_data(initData)
    state = await reading_service.get_state(req.session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Reading not found")

    await reading_service.draw(req.session_id)
    card_id = draw_cards(1)[0]
    card_name = get_card_name(card_id)
    await redis_service.set(_current_card_key(req.session_id), card_id)
    new_state = await reading_service.get_state(req.session_id)
    logger.info("Card drawn: session=%s card=%s", req.session_id, card_name)
    return ReadingDrawResponse(card_id=card_id, card_name=card_name, state=new_state.value)


@router.post("/interpret")
@limiter.limit("10/minute")
async def reading_interpret(
    request: Request, req: ReadingInterpretRequest, initData: str = Depends(_get_init_data), db: AsyncSession = Depends(get_db)
):
    user = await _get_user_from_init_data(initData, db)

    state = await reading_service.get_state(req.session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Reading not found")

    question = await redis_service.get(_current_question_key(req.session_id))
    if not question:
        raise HTTPException(status_code=400, detail="No question set for this reading")

    card_id = await redis_service.get(_current_card_key(req.session_id))
    if card_id is None:
        raise HTTPException(status_code=400, detail="No card drawn for this reading")

    await reading_service.mark_interpreting(req.session_id)

    cards = [int(card_id)]
    is_premium = bool(user.subscription_ends_at and user.subscription_ends_at > datetime.now(timezone.utc)) if user.subscription_ends_at else False

    custom_messages = build_reading_prompt(
        cards=cards,
        question=question,
        user_name=user.real_name,
        zodiac_sign=user.zodiac_sign,
        birth_time=str(user.birth_time) if user.birth_time else None,
    )

    async def event_stream():
        full_response = []
        async for chunk in stream_prediction(
            cards=cards,
            question=question,
            user_name=user.real_name,
            zodiac_sign=user.zodiac_sign,
            birth_time=str(user.birth_time) if user.birth_time else None,
            is_premium=is_premium,
            custom_messages=custom_messages,
        ):
            full_response.append(chunk)
            yield f"data: {json.dumps({'text': chunk})}\n\n"

        answer = "".join(full_response)

        cycle_data = await redis_service.get(_cycle_data_key(req.session_id)) or []
        cycle_data.append({
            "cards": cards,
            "question": question,
            "answer": answer,
        })
        await redis_service.set(_cycle_data_key(req.session_id), cycle_data)

        await reading_service.complete_cycle(req.session_id)
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/synthesis")
@limiter.limit("10/minute")
async def reading_synthesis(
    request: Request, req: ReadingSynthesisRequest, initData: str = Depends(_get_init_data), db: AsyncSession = Depends(get_db)
):
    user = await _get_user_from_init_data(initData, db)

    state = await reading_service.get_state(req.session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Reading not found")

    await reading_service.end(req.session_id)

    cycles = await redis_service.get(_cycle_data_key(req.session_id)) or []
    if not cycles:
        raise HTTPException(status_code=400, detail="No cycles to synthesize")

    custom_messages = build_synthesis_prompt(
        cycles=cycles,
        user_name=user.real_name,
        zodiac_sign=user.zodiac_sign,
    )

    async def event_stream():
        async for chunk in stream_prediction(
            cards=[],
            question="",
            user_name=user.real_name,
            zodiac_sign=user.zodiac_sign,
            custom_messages=custom_messages,
        ):
            yield f"data: {json.dumps({'text': chunk})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/state", response_model=ReadingStateResponse)
@limiter.limit("10/minute")
async def reading_state(request: Request, session_id: str, initData: str = Depends(_get_init_data)):
    _require_init_data(initData)

    state = await reading_service.get_state(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Reading not found")

    cycle_count = await reading_service.get_cycle(session_id)
    cycles = await redis_service.get(_cycle_data_key(session_id)) or []
    question = await redis_service.get(_current_question_key(session_id))
    card_id = await redis_service.get(_current_card_key(session_id))

    return ReadingStateResponse(
        session_id=session_id,
        state=state.value,
        cycle_count=cycle_count,
        max_cycles=6,
        cycles=cycles,
        current_question=question,
        current_card=int(card_id) if card_id is not None else None,
    )
