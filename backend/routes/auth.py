import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import User
from services import validate_telegram_init_data
from services.password import hash_password, verify_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    initData: str
    real_name: str
    gender: str
    login: str
    password: str


class LoginRequest(BaseModel):
    login: str
    password: str


class AuthResponse(BaseModel):
    telegram_id: int
    real_name: str
    gender: str | None
    login: str


@router.post("/register", response_model=AuthResponse)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    user_data = validate_telegram_init_data(req.initData)
    if not user_data:
        raise HTTPException(status_code=401, detail="Invalid Telegram data")

    telegram_id = user_data.get("id")
    if not telegram_id:
        raise HTTPException(status_code=401, detail="User ID not found")

    existing = await db.execute(select(User).where(User.login == req.login))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Login already taken")

    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()

    if user:
        user.real_name = req.real_name
        user.gender = req.gender
        user.login = req.login
        user.password_hash = hash_password(req.password)
    else:
        user = User(
            telegram_id=telegram_id,
            username=user_data.get("username"),
            real_name=req.real_name,
            gender=req.gender,
            login=req.login,
            password_hash=hash_password(req.password),
            free_requests_left=3,
        )
        db.add(user)

    await db.commit()
    return AuthResponse(
        telegram_id=user.telegram_id,
        real_name=user.real_name,
        gender=user.gender,
        login=user.login,
    )


@router.post("/login", response_model=AuthResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.login == req.login))
    user = result.scalar_one_or_none()

    if not user or not user.password_hash:
        raise HTTPException(status_code=401, detail="Invalid login or password")

    if not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid login or password")

    return AuthResponse(
        telegram_id=user.telegram_id,
        real_name=user.real_name,
        gender=user.gender,
        login=user.login,
    )


@router.get("/me", response_model=AuthResponse)
async def get_me(login: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.login == login))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return AuthResponse(
        telegram_id=user.telegram_id,
        real_name=user.real_name,
        gender=user.gender,
        login=user.login,
    )
