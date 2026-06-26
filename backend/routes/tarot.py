import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import settings
from database import get_db
from models import ChatHistory, TarotSession, User
from schemas import CheckAccessResponse, DrawRequest, DrawResponse, PredictRequest
from services import draw_cards, stream_prediction, validate_telegram_init_data

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tarot", tags=["tarot"])


@router.get("/check-access", response_model=CheckAccessResponse)
async def check_access(initData: str, db: AsyncSession = Depends(get_db)):
    logger.info(f"check_access called: initData_len={len(initData)}")
    user_data = validate_telegram_init_data(initData)
    if not user_data:
        logger.warning("check_access: auth failed")
        raise HTTPException(status_code=401, detail="Invalid Telegram data")

    result = await db.execute(
        select(User).where(User.telegram_id == user_data["id"])
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    has_access = False
    if user.subscription_ends_at and user.subscription_ends_at > datetime.now(timezone.utc):
        has_access = True
    elif user.free_requests_left > 0:
        has_access = True

    logger.info(f"check_access result: user={user.telegram_id}, has_access={has_access}, free={user.free_requests_left}")

    return CheckAccessResponse(
        has_access=has_access,
        free_requests_left=user.free_requests_left,
    )


@router.post("/draw", response_model=DrawResponse)
async def tarot_draw(req: DrawRequest, initData: str = ""):
    if not initData:
        raise HTTPException(status_code=401, detail="Missing initData")
    user_data = validate_telegram_init_data(initData)
    if not user_data:
        raise HTTPException(status_code=401, detail="Invalid Telegram data")

    cards = draw_cards(req.count)
    logger.info("Cards drawn: %s for user %s", cards, user_data.get("id"))
    return DrawResponse(cards=cards, layout_type=req.layout_type)


@router.post("/predict/stream")
async def tarot_predict_stream(request: Request, req: PredictRequest, initData: str = "", db: AsyncSession = Depends(get_db)):
    if not initData:
        raise HTTPException(status_code=401, detail="Missing initData")
    user_data = validate_telegram_init_data(initData)
    if not user_data:
        raise HTTPException(status_code=401, detail="Invalid Telegram data")

    telegram_id = user_data["id"]
    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if not user:
        logger.warning(f"predict: user {telegram_id} not found")
        raise HTTPException(status_code=404, detail="User not found")

    is_premium = bool(user.subscription_ends_at and user.subscription_ends_at > datetime.now(timezone.utc))

    session_result = await db.execute(
        select(TarotSession)
        .options(selectinload(TarotSession.messages))
        .where(TarotSession.id == req.session_id, TarotSession.status == "active")
    )
    session = session_result.scalar_one_or_none()
    if not session:
        session = TarotSession(id=req.session_id, user_id=telegram_id, status="active")
        db.add(session)
        await db.commit()

    history = []
    if session.messages:
        for msg in session.messages[-4:]:
            history.append({"role": msg.role, "content": msg.content})

    user_message = ChatHistory(
        session_id=req.session_id, role="user", content=req.question
    )
    db.add(user_message)
    await db.commit()

    logger.info("Prediction requested by user %s: %s", telegram_id, req.question[:50])

    async def event_stream():
        full_response = []
        async for chunk in stream_prediction(
            cards=req.cards,
            question=req.question,
            user_name=user.real_name,
            zodiac_sign=user.zodiac_sign,
            birth_time=str(user.birth_time) if user.birth_time else None,
            history=history,
            is_premium=is_premium,
        ):
            full_response.append(chunk)
            yield f"data: {json.dumps({'text': chunk})}\n\n"

        assistant_msg = ChatHistory(
            session_id=req.session_id,
            role="assistant",
            content="".join(full_response),
        )
        async with db.begin():
            db.add(assistant_msg)
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
