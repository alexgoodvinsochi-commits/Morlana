import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, StringConstraints
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from database import get_db
from models import User
from rate_limiter import limiter
from routes.reading import _get_init_data
from services import validate_telegram_init_data
from services.password import hash_password, needs_rehash, verify_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

INVALID_CREDENTIALS = "Invalid login or password"

LoginStr = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$"
    ),
]
PasswordStr = Annotated[str, StringConstraints(min_length=6, max_length=128)]
RealNameStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class RegisterRequest(BaseModel):
    real_name: RealNameStr
    gender: Literal["male", "female"]
    login: LoginStr
    password: PasswordStr


class LoginRequest(BaseModel):
    # No format rules here: every failure must be the same 401, and legacy logins
    # predate the registration constraints.
    login: Annotated[str, StringConstraints(strip_whitespace=True)]
    password: str


class AuthResponse(BaseModel):
    telegram_id: int
    real_name: str
    gender: str | None
    login: str


def _require_telegram_user(init_data: str) -> dict:
    user_data = validate_telegram_init_data(init_data)
    if not user_data:
        raise HTTPException(status_code=401, detail="Invalid Telegram data")
    return user_data


def _to_response(user: User) -> AuthResponse:
    return AuthResponse(
        telegram_id=user.telegram_id,
        real_name=user.real_name,
        gender=user.gender,
        login=user.login,
    )


@router.post("/register", response_model=AuthResponse)
@limiter.limit("5/minute")
async def register(
    request: Request,
    req: RegisterRequest,
    initData: str = Depends(_get_init_data),
    db: AsyncSession = Depends(get_db),
):
    tg_user = _require_telegram_user(initData)
    telegram_id = tg_user["id"]

    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if user and user.password_hash:
        raise HTTPException(status_code=409, detail="Account already registered")

    taken = await db.execute(
        select(User.telegram_id).where(User.login == req.login, User.telegram_id != telegram_id)
    )
    if taken.first() is not None:
        raise HTTPException(status_code=409, detail="Login already taken")

    password_hash = await run_in_threadpool(hash_password, req.password)

    if user:
        # Legacy row without a password: bind the credentials to it.
        user.real_name = req.real_name
        user.gender = req.gender
        user.login = req.login
        user.password_hash = password_hash
    else:
        user = User(
            telegram_id=telegram_id,
            username=tg_user.get("username"),
            real_name=req.real_name,
            gender=req.gender,
            login=req.login,
            password_hash=password_hash,
            free_requests_left=3,
        )
        db.add(user)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Login already taken")

    logger.info("User registered: telegram_id=%s", telegram_id)
    return _to_response(user)


@router.post("/login", response_model=AuthResponse)
@limiter.limit("10/minute")
async def login(
    request: Request,
    req: LoginRequest,
    initData: str = Depends(_get_init_data),
    db: AsyncSession = Depends(get_db),
):
    tg_user = _require_telegram_user(initData)

    result = await db.execute(select(User).where(User.login == req.login))
    user = result.scalar_one_or_none()
    # The login is a second factor of this Telegram account only.
    if not user or not user.password_hash or user.telegram_id != tg_user["id"]:
        raise HTTPException(status_code=401, detail=INVALID_CREDENTIALS)

    if not await run_in_threadpool(verify_password, req.password, user.password_hash):
        raise HTTPException(status_code=401, detail=INVALID_CREDENTIALS)

    response = _to_response(user)

    if needs_rehash(user.password_hash):
        try:
            user.password_hash = await run_in_threadpool(hash_password, req.password)
            await db.commit()
        except SQLAlchemyError:
            await db.rollback()
            logger.warning("Password rehash failed: telegram_id=%s", user.telegram_id)

    return response


@router.get("/me", response_model=AuthResponse)
@limiter.limit("60/minute")
async def get_me(
    request: Request,
    initData: str = Depends(_get_init_data),
    db: AsyncSession = Depends(get_db),
):
    tg_user = _require_telegram_user(initData)

    result = await db.execute(select(User).where(User.telegram_id == tg_user["id"]))
    user = result.scalar_one_or_none()
    if not user or user.login is None:
        raise HTTPException(status_code=404, detail="User not found")

    return _to_response(user)
