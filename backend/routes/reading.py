import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Header
from fastapi.responses import StreamingResponse
from sqlalchemy import select, delete, update
from rate_limiter import limiter
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from models import User, TarotSession, ReadingCycle, ChatHistory
from schemas import (
    ReadingActiveResponse,
    ReadingAskRequest,
    ReadingDrawRequest,
    ReadingDrawResponse,
    ReadingHistoryItem,
    ReadingHistoryResponse,
    ReadingInterpretRequest,
    ReadingNextRequest,
    ReadingStartRequest,
    ReadingStartResponse,
    ReadingStateResponse,
    ReadingSynthesisRequest,
)
from schemas.tarot import CycleHistory
from services import (
    draw_cards,
    reading_service,
    stream_prediction,
    validate_telegram_init_data,
)
from services.reading import ReadingState
from services.llm import (
    build_reading_prompt,
    build_synthesis_prompt,
    clean_llm_output,
    get_card_name,
)
from services.redis import redis_service
from services.reading import SESSION_TTL

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tarot/reading", tags=["reading"])

MAX_SESSIONS = 3
# How many of the user's newest active sessions /active checks for live Redis state.
ACTIVE_LOOKUP_LIMIT = 10


async def _cleanup_empty_sessions(db: AsyncSession, user_id: int):
    """Delete abandoned readings: active, 0 cycles, older than SESSION_TTL, no chat messages.

    Their Redis state has expired, so nothing in use is deleted; legacy chat
    sessions (rows in chat_histories) survive.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=SESSION_TTL)
    has_messages = (
        select(ChatHistory.id)
        .where(ChatHistory.session_id == TarotSession.id)
        .exists()
    )
    candidates = await db.execute(
        select(TarotSession.id)
        .where(TarotSession.user_id == user_id)
        .where(TarotSession.status == "active")
        .where(TarotSession.cycle_count == 0)
        .where(TarotSession.created_at < cutoff)
        .where(~has_messages)
    )
    empty_ids = []
    for session_id in candidates.scalars().all():
        # Redis TTL is refreshed on every transition, so an old session may still be live.
        if await reading_service.get_state(session_id) is None:
            empty_ids.append(session_id)
    if empty_ids:
        await db.execute(
            delete(ReadingCycle).where(ReadingCycle.session_id.in_(empty_ids))
        )
        await db.execute(
            delete(TarotSession).where(TarotSession.id.in_(empty_ids))
        )
        logger.info("Cleaned %d empty sessions for user %s", len(empty_ids), user_id)


async def _archive_unfinished_sessions(db: AsyncSession, user_id: int):
    """Move the user's active readings that already have answers to history.

    They are archived without a synthesis (synthesis stays NULL).
    """
    result = await db.execute(
        update(TarotSession)
        .where(TarotSession.user_id == user_id)
        .where(TarotSession.status == "active")
        .where(TarotSession.cycle_count > 0)
        .values(status="archived")
    )
    if result.rowcount:
        logger.info("Archived %d unfinished sessions for user %s", result.rowcount, user_id)


async def _trim_old_archived_sessions(db: AsyncSession, user_id: int):
    """Keep only last MAX_SESSIONS archived sessions, delete older ones."""
    archived = await db.execute(
        select(TarotSession.id)
        .where(TarotSession.user_id == user_id)
        .where(TarotSession.status == "archived")
        .order_by(TarotSession.created_at.desc())
        .offset(MAX_SESSIONS)
    )
    old_ids = list(archived.scalars().all())
    if old_ids:
        await db.execute(
            delete(ReadingCycle).where(ReadingCycle.session_id.in_(old_ids))
        )
        await db.execute(
            delete(TarotSession).where(TarotSession.id.in_(old_ids))
        )
        logger.info("Trimmed %d old archived sessions for user %s", len(old_ids), user_id)


def _cycle_data_key(session_id: str) -> str:
    return f"reading:{session_id}:cycle_data"


def _cycle_counter_key(session_id: str) -> str:
    # Written by ReadingService; the routes only keep its TTL in step.
    return f"reading:{session_id}:cycle"


def _current_question_key(session_id: str) -> str:
    return f"reading:{session_id}:question"


def _current_card_key(session_id: str) -> str:
    return f"reading:{session_id}:card"


async def _refresh_session_ttl(session_id: str) -> None:
    """Keep every key of a live reading alive together.

    reading_service refreshes only :state on each transition, while the cycle
    counter and the collected cycles are written once per cycle. In a reading
    that outlives SESSION_TTL they would expire under a still-live state, and
    the next cycle would be renumbered from 1 and synthesized on its own.
    """
    keys = (
        _cycle_counter_key(session_id),
        _cycle_data_key(session_id),
        _current_question_key(session_id),
        _current_card_key(session_id),
    )
    try:
        for key in keys:
            # EXPIRE on a missing key is a no-op, so deleted keys stay deleted.
            await redis_service.client.expire(key, SESSION_TTL)
    except Exception as e:
        logger.warning("Could not refresh TTL for session %s: %s", session_id, e)


async def _get_user_from_init_data(init_data: str, db: AsyncSession) -> User:
    user_data = validate_telegram_init_data(init_data)
    if not user_data:
        raise HTTPException(status_code=401, detail="Invalid Telegram data")
    result = await db.execute(select(User).where(User.telegram_id == user_data["id"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


async def _get_owned_session(db: AsyncSession, session_id: str, user: User) -> TarotSession:
    """Return the caller's session. Missing and foreign sessions get the same 404."""
    try:
        canonical_id = str(uuid.UUID(session_id))
    except (ValueError, TypeError, AttributeError):
        # Not a UUID: the uuid column would reject it with a DB error.
        raise HTTPException(status_code=404, detail="Reading not found")
    result = await db.execute(select(TarotSession).where(TarotSession.id == canonical_id))
    tarot_session = result.scalar_one_or_none()
    if tarot_session is None or tarot_session.user_id != user.telegram_id:
        raise HTTPException(status_code=404, detail="Reading not found")
    return tarot_session


async def _get_init_data(authorization: str = Header(default="")) -> str:
    if settings.DEV_MODE:
        if not authorization.startswith("Bearer "):
            return "dev"
        return authorization[7:]
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    return authorization[7:]


@router.post("/start", response_model=ReadingStartResponse)
# rate limit removed - auth protection sufficient
async def reading_start(
    request: Request, req: ReadingStartRequest, initData: str = Depends(_get_init_data), db: AsyncSession = Depends(get_db)
):
    user = await _get_user_from_init_data(initData, db)

    await _cleanup_empty_sessions(db, user.telegram_id)
    await _archive_unfinished_sessions(db, user.telegram_id)
    await _trim_old_archived_sessions(db, user.telegram_id)

    session_id = str(uuid.uuid4())

    tarot_session = TarotSession(id=session_id, user_id=user.telegram_id)
    db.add(tarot_session)
    await db.commit()

    state = await reading_service.start(session_id)
    await redis_service.set(_cycle_data_key(session_id), [], ttl=SESSION_TTL)
    logger.info("Reading started: session=%s user=%s", session_id, user.telegram_id)
    return ReadingStartResponse(session_id=session_id, state=state.value)


@router.get("/active", response_model=ReadingActiveResponse)
# rate limit removed - auth protection sufficient
async def reading_active(
    request: Request, initData: str = Depends(_get_init_data), db: AsyncSession = Depends(get_db)
):
    """The caller's newest active reading that can still be resumed (Redis state alive)."""
    user = await _get_user_from_init_data(initData, db)

    result = await db.execute(
        select(TarotSession.id)
        .where(TarotSession.user_id == user.telegram_id)
        .where(TarotSession.status == "active")
        .order_by(TarotSession.created_at.desc())
        .limit(ACTIVE_LOOKUP_LIMIT)
    )
    for session_id in result.scalars().all():
        state = await reading_service.get_state(session_id)
        if state is not None:
            return ReadingActiveResponse(session_id=session_id, state=state.value)
    return ReadingActiveResponse(session_id=None, state=None)


@router.post("/ask")
# rate limit removed - auth protection sufficient
async def reading_ask(
    request: Request, req: ReadingAskRequest, initData: str = Depends(_get_init_data), db: AsyncSession = Depends(get_db)
):
    user = await _get_user_from_init_data(initData, db)
    await _get_owned_session(db, req.session_id, user)

    state = await reading_service.get_state(req.session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Reading not found")

    await _refresh_session_ttl(req.session_id)
    await reading_service.ask(req.session_id)
    await redis_service.set(_current_question_key(req.session_id), req.question, ttl=SESSION_TTL)
    new_state = await reading_service.get_state(req.session_id)
    return {"session_id": req.session_id, "state": new_state.value}


@router.post("/next")
# rate limit removed - auth protection sufficient
async def reading_next(
    request: Request, req: ReadingNextRequest, initData: str = Depends(_get_init_data), db: AsyncSession = Depends(get_db)
):
    user = await _get_user_from_init_data(initData, db)
    await _get_owned_session(db, req.session_id, user)

    state = await reading_service.get_state(req.session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Reading not found")
    if state != ReadingState.READY:
        raise HTTPException(status_code=400, detail=f"Cannot start new cycle in state: {state.value}")

    await _refresh_session_ttl(req.session_id)
    await reading_service.start_new_cycle(req.session_id)
    new_state = await reading_service.get_state(req.session_id)
    return {"session_id": req.session_id, "state": new_state.value}


@router.post("/draw", response_model=ReadingDrawResponse)
# rate limit removed - auth protection sufficient
async def reading_draw(
    request: Request, req: ReadingDrawRequest, initData: str = Depends(_get_init_data), db: AsyncSession = Depends(get_db)
):
    user = await _get_user_from_init_data(initData, db)
    await _get_owned_session(db, req.session_id, user)

    state = await reading_service.get_state(req.session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Reading not found")

    await _refresh_session_ttl(req.session_id)
    await reading_service.draw(req.session_id)
    card_id = draw_cards(1)[0]
    card_name = get_card_name(card_id)
    await redis_service.set(_current_card_key(req.session_id), card_id, ttl=SESSION_TTL)
    new_state = await reading_service.get_state(req.session_id)
    logger.info("Card drawn: session=%s card=%s", req.session_id, card_name)
    return ReadingDrawResponse(card_id=card_id, card_name=card_name, state=new_state.value)


@router.post("/interpret")
# rate limit removed - auth protection sufficient
async def reading_interpret(
    request: Request, req: ReadingInterpretRequest, initData: str = Depends(_get_init_data), db: AsyncSession = Depends(get_db)
):
    user = await _get_user_from_init_data(initData, db)
    await _get_owned_session(db, req.session_id, user)

    state = await reading_service.get_state(req.session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Reading not found")

    await _refresh_session_ttl(req.session_id)

    question = await redis_service.get(_current_question_key(req.session_id))
    if not question:
        raise HTTPException(status_code=400, detail="No question set for this reading")

    card_id = await redis_service.get(_current_card_key(req.session_id))
    if card_id is None:
        raise HTTPException(status_code=400, detail="No card drawn for this reading")

    if state != ReadingState.INTERPRETATION:
        await reading_service.mark_interpreting(req.session_id)

    cards = [int(card_id)]
    is_premium = bool(user.subscription_ends_at and user.subscription_ends_at > datetime.now(timezone.utc)) if user.subscription_ends_at else False

    custom_messages = build_reading_prompt(
        cards=cards,
        question=question,
        user_name=user.real_name,
    )

    async def event_stream():
        # Any failure leaves the reading in ИНТЕРПРЕТАЦИЯ, from which /interpret can be retried.
        try:
            full_response = []
            async for chunk in stream_prediction(
                cards=cards,
                question=question,
                user_name=user.real_name,
                is_premium=is_premium,
                custom_messages=custom_messages,
            ):
                full_response.append(chunk)
                yield f"data: {json.dumps({'text': chunk})}\n\n"

            raw_answer = "".join(full_response)
            cleaned_answer = clean_llm_output(raw_answer)
            if not cleaned_answer.strip():
                raise RuntimeError("LLM returned an empty interpretation")

            # Another request (e.g. a retry) may have completed this cycle meanwhile.
            if await reading_service.get_state(req.session_id) != ReadingState.INTERPRETATION:
                raise RuntimeError("Reading left the interpretation state during streaming")
            cycle_count = await reading_service.get_cycle(req.session_id) + 1

            # Persist to the DB first and move the Redis state last, so a DB failure
            # cannot leave the reading in ГОТОВО without its cycle saved.
            db.add(ReadingCycle(
                session_id=req.session_id,
                cycle_number=cycle_count,
                question=question,
                card_id=cards[0],
                card_name=get_card_name(cards[0]),
                interpretation=cleaned_answer,
            ))
            await db.execute(
                update(TarotSession)
                .where(TarotSession.id == req.session_id)
                .values(cycle_count=cycle_count)
            )
            await db.commit()

            cycle_data = await redis_service.get(_cycle_data_key(req.session_id)) or []
            cycle_data.append({
                "cards": cards,
                "question": question,
                "answer": cleaned_answer,
            })
            await redis_service.set(_cycle_data_key(req.session_id), cycle_data, ttl=SESSION_TTL)

            await reading_service.complete_cycle(req.session_id)
        except Exception:
            logger.exception("Interpretation failed: session=%s", req.session_id)
            try:
                await db.rollback()
            except Exception:
                logger.exception("Rollback failed after interpretation error: session=%s", req.session_id)
            yield f"data: {json.dumps({'error': 'interpretation_failed'})}\n\n"
            yield "data: [DONE]\n\n"
            return

        yield f"data: {json.dumps({'cleaned': cleaned_answer})}\n\n"
        yield "data: [DONE]\n\n"

    sse_headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=sse_headers)


@router.post("/synthesis")
# rate limit removed - auth protection sufficient
async def reading_synthesis(
    request: Request, req: ReadingSynthesisRequest, initData: str = Depends(_get_init_data), db: AsyncSession = Depends(get_db)
):
    user = await _get_user_from_init_data(initData, db)
    tarot_session = await _get_owned_session(db, req.session_id, user)

    state = await reading_service.get_state(req.session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Reading not found")

    if state != ReadingState.COMPLETED:
        await reading_service.end(req.session_id)

    cycles = await redis_service.get(_cycle_data_key(req.session_id)) or []
    if not cycles:
        raise HTTPException(status_code=400, detail="No cycles to synthesize")

    custom_messages = build_synthesis_prompt(
        cycles=cycles,
        user_name=user.real_name,
    )

    full_response = []
    async for chunk in stream_prediction(
        cards=[],
        question="",
        user_name=user.real_name,
        custom_messages=custom_messages,
    ):
        full_response.append(chunk)

    raw_answer = "".join(full_response)
    cleaned_answer = clean_llm_output(raw_answer)

    tarot_session.status = "archived"
    tarot_session.synthesis = cleaned_answer
    await db.commit()

    await _trim_old_archived_sessions(db, user.telegram_id)
    await db.commit()

    async def event_stream():
        for chunk in full_response:
            yield f"data: {json.dumps({'text': chunk})}\n\n"
        yield f"data: {json.dumps({'cleaned': cleaned_answer})}\n\n"
        yield "data: [DONE]\n\n"

    sse_headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=sse_headers)


@router.get("/state", response_model=ReadingStateResponse)
# rate limit removed - auth protection sufficient
async def reading_state(
    request: Request, session_id: str, initData: str = Depends(_get_init_data), db: AsyncSession = Depends(get_db)
):
    user = await _get_user_from_init_data(initData, db)
    await _get_owned_session(db, session_id, user)

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


@router.get("/history", response_model=ReadingHistoryResponse)
# rate limit removed - auth protection sufficient
async def reading_history(
    request: Request, initData: str = Depends(_get_init_data), db: AsyncSession = Depends(get_db)
):
    user = await _get_user_from_init_data(initData, db)

    sessions_result = await db.execute(
        select(TarotSession)
        .where(TarotSession.user_id == user.telegram_id)
        .where(TarotSession.status == "archived")
        .order_by(TarotSession.created_at.desc())
        .limit(3)
    )
    sessions = sessions_result.scalars().all()

    readings = []
    for session in sessions:
        cycles_result = await db.execute(
            select(ReadingCycle)
            .where(ReadingCycle.session_id == session.id)
            .order_by(ReadingCycle.cycle_number)
        )
        cycles = cycles_result.scalars().all()

        readings.append(ReadingHistoryItem(
            session_id=session.id,
            spread_name=session.spread_name or "one-card",
            created_at=session.created_at,
            cycle_count=session.cycle_count,
            synthesis=session.synthesis,
            cycles=[CycleHistory(
                cycle_number=c.cycle_number,
                question=c.question,
                card_id=c.card_id,
                card_name=c.card_name,
            ) for c in cycles],
        ))

    return ReadingHistoryResponse(readings=readings)
