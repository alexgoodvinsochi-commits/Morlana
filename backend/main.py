from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from rate_limiter import limiter

from config import settings
from database import init_db
from logging_config import setup_logging
from routes import astrology_router, tarot_router, sessions_router, reading_router  # , payments_router
from services.redis import redis_service

logger = logging.getLogger(__name__)

setup_logging()


class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Morlana backend...")
    await init_db()
    logger.info("Database initialized")
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
app.include_router(tarot_router)
app.include_router(sessions_router)
app.include_router(reading_router)
# app.include_router(payments_router)


@app.get("/health")
@limiter.exempt
async def health():
    return {"status": "ok"}
