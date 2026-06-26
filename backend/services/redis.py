import json
import logging
from typing import Any

import redis.asyncio as aioredis

from config import settings

logger = logging.getLogger(__name__)


class RedisService:
    def __init__(self):
        self._client: aioredis.Redis | None = None

    async def connect(self):
        self._client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
        await self._client.ping()
        logger.info("Redis connected")

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
            logger.info("Redis closed")

    @property
    def client(self) -> aioredis.Redis:
        if not self._client:
            raise RuntimeError("Redis not connected. Call connect() first.")
        return self._client

    async def get(self, key: str) -> Any | None:
        try:
            value = await self.client.get(key)
            if value is not None:
                try:
                    return json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    return value
            return None
        except Exception:
            logger.exception("Redis GET error for key=%s", key)
            return None

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        try:
            serialized = json.dumps(value) if not isinstance(value, str) else value
            if ttl:
                await self.client.setex(key, ttl, serialized)
            else:
                await self.client.set(key, serialized)
            return True
        except Exception:
            logger.exception("Redis SET error for key=%s", key)
            return False

    async def delete(self, key: str) -> bool:
        try:
            await self.client.delete(key)
            return True
        except Exception:
            logger.exception("Redis DELETE error for key=%s", key)
            return False

    async def exists(self, key: str) -> bool:
        try:
            return bool(await self.client.exists(key))
        except Exception:
            logger.exception("Redis EXISTS error for key=%s", key)
            return False


redis_service = RedisService()
