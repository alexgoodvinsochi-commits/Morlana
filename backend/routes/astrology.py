import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import User
from schemas import AstrologyBonusRequest, AstrologyBonusResponse
from services import get_zodiac_sign, validate_telegram_init_data

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/astrology", tags=["astrology"])


@router.post("/bonus", response_model=AstrologyBonusResponse)
async def astrology_bonus(req: AstrologyBonusRequest, db: AsyncSession = Depends(get_db)):
    logger.info(f"astrology_bonus called: real_name={req.real_name}, gender={req.gender}")
    user_data = validate_telegram_init_data(req.initData)
    if not user_data:
        raise HTTPException(status_code=401, detail="Invalid Telegram data")

    telegram_id = user_data.get("id")
    if not telegram_id:
        raise HTTPException(status_code=401, detail="User ID not found")

    zodiac_sign = get_zodiac_sign(req.birth_date) if req.birth_date else None

    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()

    if user:
        user.real_name = req.real_name
        user.gender = req.gender
        if req.birth_date:
            user.birth_date = req.birth_date
            user.birth_time = req.birth_time
            user.zodiac_sign = zodiac_sign
            user.birth_location = req.birth_location
    else:
        user = User(
            telegram_id=telegram_id,
            username=user_data.get("username"),
            real_name=req.real_name,
            gender=req.gender,
            birth_date=req.birth_date,
            birth_time=req.birth_time,
            zodiac_sign=zodiac_sign,
            birth_location=req.birth_location,
            free_requests_left=3,
        )
        db.add(user)

    await db.commit()

    greeting = (
        f"Привет, {req.real_name}! "
        f"Рада познакомиться. "
        f"Давай начнём — задай свой первый вопрос картам."
    )

    return AstrologyBonusResponse(
        zodiac_sign=zodiac_sign or "",
        greeting=greeting,
        free_requests_left=user.free_requests_left,
    )
