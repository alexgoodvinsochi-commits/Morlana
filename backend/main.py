from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from rate_limiter import limiter

from config import settings
from database import check_schema_revision
from logging_config import setup_logging
from routes import astrology_router, catalog_router, reading_router, auth_router
from services.redis import redis_service

logger = logging.getLogger(__name__)

setup_logging()


class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Morlana backend...")
    if settings.DEV_MODE:
        logger.warning(
            "DEV_MODE is enabled: unsigned Telegram initData is accepted as the "
            "dev account. Never expose this instance publicly."
        )
        public_origins = [
            origin.strip()
            for origin in settings.CORS_ORIGINS.split(",")
            if origin.strip() and "localhost" not in origin and "127.0.0.1" not in origin
        ]
        if public_origins:
            # Refuse to boot: with DEV_MODE on, any request without a signed
            # initData is served as the dev account, so a public origin here
            # means the instance is about to be exposed unauthenticated.
            raise RuntimeError(
                "DEV_MODE is enabled while CORS_ORIGINS points at non-local origins "
                f"({', '.join(public_origins)}). Set DEV_MODE=false, or remove the "
                "public origins for local development."
            )
    revision = await check_schema_revision()
    logger.info(f"Database schema is at head revision {revision}")
    try:
        await redis_service.connect()
    except Exception as e:
        logger.warning(f"Redis connection failed: {e}")
    yield
    await redis_service.close()
    logger.info("Shutting down Morlana backend")


app = FastAPI(title="Morlana: ИИ-Таролог", version="1.0.0", lifespan=lifespan, default_response_class=UTF8JSONResponse)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(astrology_router)
app.include_router(catalog_router)
app.include_router(reading_router)
app.include_router(auth_router)
# app.include_router(payments_router)


@app.get("/health")
@limiter.exempt
async def health():
    return {"status": "ok"}
