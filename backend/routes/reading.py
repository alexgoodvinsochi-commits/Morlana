import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Awaitable

from fastapi import APIRouter, Depends, HTTPException, Request, Header
from fastapi.responses import StreamingResponse
from sqlalchemy import select, delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from models import User, TarotSession, ReadingCycle
from schemas import (
    DeckInfo,
    ReadingActiveResponse,
    ReadingAskRequest,
    ReadingDrawRequest,
    ReadingHistoryItem,
    ReadingHistoryResponse,
    ReadingInterpretRequest,
    ReadingNextRequest,
    ReadingStartRequest,
    ReadingStateResponse,
    ReadingSynthesisRequest,
    SpreadInfo,
)
from schemas.tarot import CycleHistory
from services import validate_telegram_init_data
from services.decks import (
    DEFAULT_DECK_ID,
    DeckManifest,
    UnknownDeck,
    card_id_from_legacy_number,
    deck_registry,
    legacy_number,
)
from services.llm import (
    build_reading_prompt,
    build_synthesis_prompt,
    clean_llm_output,
    stream_prediction,
)
from services.reading import (
    SESSION_TTL,
    InvalidTransition,
    ReadingNotFound,
    ReadingSession,
    ReadingState,
    reading_service,
)
from services.safety import CRISIS_REPLY, is_crisis_message
from services.spreads import DEFAULT_SPREAD_ID, Spread, UnknownSpread, spread_registry
from services.tarot import draw_for_spread

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tarot/reading", tags=["reading"])
# What the client may choose from before starting a reading.
catalog_router = APIRouter(prefix="/api/v1/tarot", tags=["catalog"])

# How many of the user's newest active sessions /active checks for live Redis state.
ACTIVE_LOOKUP_LIMIT = 10


async def _cleanup_empty_sessions(db: AsyncSession, user_id: int):
    """Delete abandoned readings: active, 0 cycles, older than SESSION_TTL.

    Their Redis state has expired, so nothing in use is deleted.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=SESSION_TTL)
    candidates = await db.execute(
        select(TarotSession.id)
        .where(TarotSession.user_id == user_id)
        .where(TarotSession.status == "active")
        .where(TarotSession.cycle_count == 0)
        .where(TarotSession.created_at < cutoff)
    )
    empty_ids = []
    for session_id in candidates.scalars().all():
        # Redis TTL is refreshed on every write, so an old session may still be live.
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


def _require_spread(spread_id: str) -> Spread:
    """The spread the caller asked for; an unknown id is a 400, not a 500."""
    try:
        return spread_registry.get(spread_id)
    except UnknownSpread:
        raise HTTPException(status_code=400, detail="Unknown spread")


def _require_deck(deck_id: str) -> DeckManifest:
    try:
        return deck_registry.get(deck_id)
    except UnknownDeck:
        raise HTTPException(status_code=400, detail="Unknown deck")


def _session_spread(session: ReadingSession) -> Spread:
    """The spread of a reading already in flight.

    Its file could have been removed since the reading started; the reading goes
    on with the default spread rather than becoming unanswerable.
    """
    if spread_registry.has(session.spread_id):
        return spread_registry.get(session.spread_id)
    logger.warning(
        "Unknown spread '%s' for session %s, falling back to '%s'",
        session.spread_id, session.session_id, DEFAULT_SPREAD_ID,
    )
    return spread_registry.default


def _deck_or_default(deck_id: str, session_id: str) -> DeckManifest:
    """The deck of a reading that already exists (see _session_spread)."""
    if deck_registry.has(deck_id):
        return deck_registry.get(deck_id)
    logger.warning(
        "Unknown deck '%s' for session %s, falling back to '%s'",
        deck_id, session_id, DEFAULT_DECK_ID,
    )
    return deck_registry.default


def _history_cards(cycle: ReadingCycle, deck: DeckManifest) -> list[dict]:
    """The cards of an archived cycle, rebuilt from the old columns if need be.

    Rows written before stage 2 are backfilled by the migration; this fallback
    covers whatever the backfill could not resolve.
    """
    if cycle.cards:
        return list(cycle.cards)
    card_id = card_id_from_legacy_number(cycle.card_id) if cycle.card_id else None
    if card_id is None or not deck.has_card(card_id):
        return []
    card = deck.drawn_card(card_id, "main")
    if cycle.card_name:
        card["name"] = cycle.card_name
    return [card]


def _card_ids(cards: list[dict] | None) -> list[str]:
    return [str(card.get("card_id")) for card in cards or []]


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


async def _get_live_session(session_id: str) -> ReadingSession:
    """The live reading from Redis. Expired, absent and old-format keys give 404."""
    session = await reading_service.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Reading not found")
    return session


def _is_premium(user: User) -> bool:
    ends_at = user.subscription_ends_at
    return ends_at is not None and ends_at > datetime.now(timezone.utc)


async def _apply_transition(step: Awaitable[ReadingSession]) -> ReadingSession:
    """Run one state-machine step, turning its errors into HTTP answers."""
    try:
        return await step
    except ReadingNotFound:
        # The Redis state expired between the caller's lookup and the transition.
        raise HTTPException(status_code=404, detail="Reading not found")
    except InvalidTransition as e:
        raise HTTPException(
            status_code=409,
            detail=f"Invalid state transition: {e.current.value} -> {e.target.value}",
        )


def _state_response(session: ReadingSession, spread: Spread) -> ReadingStateResponse:
    """The one answer every reading action returns."""
    return ReadingStateResponse(
        session_id=session.session_id,
        state=session.state.value,
        cycle_count=session.cycle,
        max_cycles=spread.max_cycles,
        spread_id=session.spread_id,
        deck_id=session.deck_id,
        current_question=session.question,
        current_cards=session.cards,
        cycles=session.cycle_data,
    )


async def _get_init_data(authorization: str = Header(default="")) -> str:
    if settings.DEV_MODE:
        if not authorization.startswith("Bearer "):
            return "dev"
        return authorization[7:]
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    return authorization[7:]


@catalog_router.get("/spreads", response_model=list[SpreadInfo])
# rate limit removed - auth protection sufficient
async def list_spreads(
    request: Request, initData: str = Depends(_get_init_data), db: AsyncSession = Depends(get_db)
):
    """The spreads a reading can be started with."""
    await _get_user_from_init_data(initData, db)
    return [
        SpreadInfo(
            id=spread.id,
            name=spread.name,
            description=spread.description,
            card_count=spread.card_count,
            max_cycles=spread.max_cycles,
            tier=spread.tier,
        )
        for spread in spread_registry.all()
    ]


@catalog_router.get("/decks", response_model=list[DeckInfo])
# rate limit removed - auth protection sufficient
async def list_decks(
    request: Request, initData: str = Depends(_get_init_data), db: AsyncSession = Depends(get_db)
):
    """The decks a reading can be started with."""
    await _get_user_from_init_data(initData, db)
    return [
        DeckInfo(id=deck.id, name=deck.name, back_image=deck.back_image)
        for deck in deck_registry.all()
    ]


@router.post("/start", response_model=ReadingStateResponse)
# rate limit removed - auth protection sufficient
async def reading_start(
    request: Request, req: ReadingStartRequest, initData: str = Depends(_get_init_data), db: AsyncSession = Depends(get_db)
):
    user = await _get_user_from_init_data(initData, db)

    spread_id = req.spread_id or DEFAULT_SPREAD_ID
    deck_id = req.deck_id or DEFAULT_DECK_ID
    # Refuse an unknown id before touching the user's other readings.
    spread = _require_spread(spread_id)
    deck = _require_deck(deck_id)
    # The pair is checked here, the only place that knows both: /draw would
    # otherwise fail with a 500 on a spread that asks a small deck for more
    # cards than it holds.
    if spread.card_count > len(deck.cards):
        raise HTTPException(status_code=400, detail="Spread needs more cards than the deck has")

    await _cleanup_empty_sessions(db, user.telegram_id)
    await _archive_unfinished_sessions(db, user.telegram_id)

    session_id = str(uuid.uuid4())

    tarot_session = TarotSession(
        id=session_id,
        user_id=user.telegram_id,
        spread_id=spread_id,
        deck_id=deck_id,
        # The legacy column /history reports; keep it on the id that was chosen,
        # or every reading is reported as the default spread.
        spread_name=spread_id,
    )
    db.add(tarot_session)
    await db.commit()

    session = await reading_service.start(session_id, spread_id=spread_id, deck_id=deck_id)
    logger.info(
        "Reading started: session=%s user=%s spread=%s deck=%s",
        session_id, user.telegram_id, spread_id, deck_id,
    )
    return _state_response(session, spread)


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


@router.post("/ask", response_model=ReadingStateResponse)
# rate limit removed - auth protection sufficient
async def reading_ask(
    request: Request, req: ReadingAskRequest, initData: str = Depends(_get_init_data), db: AsyncSession = Depends(get_db)
):
    user = await _get_user_from_init_data(initData, db)
    await _get_owned_session(db, req.session_id, user)

    session = await _get_live_session(req.session_id)
    spread = _session_spread(session)

    session = await _apply_transition(reading_service.ask(req.session_id, req.question))
    return _state_response(session, spread)


@router.post("/next", response_model=ReadingStateResponse)
# rate limit removed - auth protection sufficient
async def reading_next(
    request: Request, req: ReadingNextRequest, initData: str = Depends(_get_init_data), db: AsyncSession = Depends(get_db)
):
    user = await _get_user_from_init_data(initData, db)
    await _get_owned_session(db, req.session_id, user)

    session = await _get_live_session(req.session_id)
    spread = _session_spread(session)

    session = await _apply_transition(reading_service.start_new_cycle(req.session_id))
    return _state_response(session, spread)


@router.post("/draw", response_model=ReadingStateResponse)
# rate limit removed - auth protection sufficient
async def reading_draw(
    request: Request, req: ReadingDrawRequest, initData: str = Depends(_get_init_data), db: AsyncSession = Depends(get_db)
):
    user = await _get_user_from_init_data(initData, db)
    await _get_owned_session(db, req.session_id, user)

    session = await _get_live_session(req.session_id)
    spread = _session_spread(session)
    deck = _deck_or_default(session.deck_id, session.session_id)

    # The server draws: card_count cards of the deck, on the spread's positions.
    cards = draw_for_spread(deck, spread)

    session = await _apply_transition(reading_service.draw(req.session_id, cards))
    logger.info("Cards drawn: session=%s cards=%s", req.session_id, _card_ids(cards))
    return _state_response(session, spread)


@router.post("/interpret")
# rate limit removed - auth protection sufficient
async def reading_interpret(
    request: Request, req: ReadingInterpretRequest, initData: str = Depends(_get_init_data), db: AsyncSession = Depends(get_db)
):
    user = await _get_user_from_init_data(initData, db)
    await _get_owned_session(db, req.session_id, user)

    session = await _get_live_session(req.session_id)
    spread = _session_spread(session)

    question = session.question or ""
    if spread.requires_question and not question.strip():
        raise HTTPException(status_code=400, detail="No question set for this reading")

    cards = session.cards
    if not cards:
        raise HTTPException(status_code=400, detail="No cards drawn for this reading")

    if session.state != ReadingState.INTERPRETATION:
        session = await _apply_transition(reading_service.mark_interpreting(req.session_id))

    is_premium = _is_premium(user)

    custom_messages = build_reading_prompt(
        spread=spread,
        cards=cards,
        question=question,
        user_name=user.real_name,
    )

    # The cycle row and the Redis state cannot be written atomically. If an earlier
    # attempt committed the row and failed before READY (Redis blip, client gone),
    # the retry finishes that cycle from the saved row: inserting it again would
    # violate uq_reading_cycles_session_cycle on every retry.
    last_cycle = (await db.execute(
        select(ReadingCycle)
        .where(ReadingCycle.session_id == req.session_id)
        .order_by(ReadingCycle.cycle_number.desc())
        .limit(1)
    )).scalar_one_or_none()
    last_number = last_cycle.cycle_number if last_cycle is not None else 0
    saved_answer = None
    if (
        last_cycle is not None
        and last_number > session.cycle
        and last_cycle.question == question
        and _card_ids(last_cycle.cards) == _card_ids(cards)
    ):
        saved_answer = last_cycle.interpretation

    async def event_stream():
        # Any failure leaves the reading in INTERPRETATION, from which /interpret can be retried.
        try:
            if saved_answer is not None:
                cleaned_answer = saved_answer
                cycle_count = last_number
                logger.info("Resuming saved cycle %d: session=%s", cycle_count, req.session_id)
                yield f"data: {json.dumps({'text': cleaned_answer})}\n\n"
            else:
                full_response = []
                if is_crisis_message(question):
                    # No LLM for a person in crisis: the fixed reply takes the normal
                    # path below, so the cycle is saved and the reading goes on.
                    logger.info("Interpretation skipped the LLM, crisis message detected: session=%s", req.session_id)
                    full_response.append(CRISIS_REPLY)
                    yield f"data: {json.dumps({'text': CRISIS_REPLY})}\n\n"
                else:
                    async for chunk in stream_prediction(
                        messages=custom_messages,
                        spread=spread,
                        is_premium=is_premium,
                    ):
                        full_response.append(chunk)
                        yield f"data: {json.dumps({'text': chunk})}\n\n"

                raw_answer = "".join(full_response)
                cleaned_answer = clean_llm_output(raw_answer)
                if not cleaned_answer.strip():
                    raise RuntimeError("LLM returned an empty interpretation")

                # Another request (e.g. a retry) may have completed this cycle meanwhile.
                live = await reading_service.get(req.session_id)
                if live is None or live.state != ReadingState.INTERPRETATION:
                    raise RuntimeError("Reading left the interpretation state during streaming")
                # Numbered after the saved rows too: a Redis counter that fell behind
                # them must not reuse a taken cycle_number.
                cycle_count = max(live.cycle, last_number) + 1

                # Persist to the DB first and move the Redis state last, so a DB failure
                # cannot leave the reading in READY without its cycle saved.
                db.add(ReadingCycle(
                    session_id=req.session_id,
                    cycle_number=cycle_count,
                    question=question,
                    cards=cards,
                    # The legacy single-card columns stay filled from the first card.
                    card_id=legacy_number(cards[0].get("card_id", "")),
                    card_name=cards[0].get("name"),
                    interpretation=cleaned_answer,
                ))
                await db.execute(
                    update(TarotSession)
                    .where(TarotSession.id == req.session_id)
                    .values(cycle_count=cycle_count)
                )
                await db.commit()

            await reading_service.complete_cycle(
                req.session_id,
                cycle=cycle_count,
                max_cycles=spread.max_cycles,
                cycle_entry={
                    "cycle_number": cycle_count,
                    "question": question,
                    "cards": cards,
                    "answer": cleaned_answer,
                },
            )
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

    session = await _get_live_session(req.session_id)
    spread = _session_spread(session)

    if session.state != ReadingState.COMPLETED:
        session = await _apply_transition(reading_service.end(req.session_id))

    cycles = session.cycle_data
    if not cycles:
        raise HTTPException(status_code=400, detail="No cycles to synthesize")

    custom_messages = build_synthesis_prompt(
        spread=spread,
        cycles=cycles,
        user_name=user.real_name,
    )

    # An LLM failure must not archive the reading: it stays active and in COMPLETED,
    # so /synthesis can simply be called again.
    full_response = []
    if any(is_crisis_message(cycle.get("question")) for cycle in cycles):
        # A reading with a crisis message gets no LLM synthesis either.
        logger.info("Synthesis skipped the LLM, crisis message detected: session=%s", req.session_id)
        full_response.append(CRISIS_REPLY)
    else:
        try:
            async for chunk in stream_prediction(
                messages=custom_messages,
                spread=spread,
            ):
                full_response.append(chunk)
        except Exception:
            logger.exception("Synthesis failed: session=%s", req.session_id)
            raise HTTPException(status_code=502, detail="Synthesis failed")

    raw_answer = "".join(full_response)
    cleaned_answer = clean_llm_output(raw_answer)
    if not cleaned_answer.strip():
        logger.error("Synthesis failed: LLM returned an empty synthesis: session=%s", req.session_id)
        raise HTTPException(status_code=502, detail="Synthesis failed")

    tarot_session.status = "archived"
    tarot_session.synthesis = cleaned_answer
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

    session = await _get_live_session(session_id)
    return _state_response(session, _session_spread(session))


@router.get("/history", response_model=ReadingHistoryResponse)
# rate limit removed - auth protection sufficient
async def reading_history(
    request: Request, initData: str = Depends(_get_init_data), db: AsyncSession = Depends(get_db)
):
    user = await _get_user_from_init_data(initData, db)
    limit = settings.HISTORY_LIMIT_PREMIUM if _is_premium(user) else settings.HISTORY_LIMIT_FREE

    sessions_result = await db.execute(
        select(TarotSession)
        .where(TarotSession.user_id == user.telegram_id)
        .where(TarotSession.status == "archived")
        .order_by(TarotSession.created_at.desc())
        .limit(limit)
    )
    sessions = sessions_result.scalars().all()

    # One query for the cycles of every returned session.
    cycles_by_session: dict[str, list[ReadingCycle]] = {s.id: [] for s in sessions}
    if sessions:
        cycles_result = await db.execute(
            select(ReadingCycle)
            .where(ReadingCycle.session_id.in_(list(cycles_by_session)))
            .order_by(ReadingCycle.session_id, ReadingCycle.cycle_number)
        )
        for cycle in cycles_result.scalars().all():
            cycles_by_session[cycle.session_id].append(cycle)

    readings = []
    for session in sessions:
        cycles = cycles_by_session[session.id]
        deck = _deck_or_default(session.deck_id or DEFAULT_DECK_ID, session.id)

        readings.append(ReadingHistoryItem(
            session_id=session.id,
            spread_name=session.spread_name or DEFAULT_SPREAD_ID,
            created_at=session.created_at,
            cycle_count=session.cycle_count,
            synthesis=session.synthesis,
            cycles=[CycleHistory(
                cycle_number=c.cycle_number,
                question=c.question,
                cards=_history_cards(c, deck),
            ) for c in cycles],
        ))

    return ReadingHistoryResponse(readings=readings)
