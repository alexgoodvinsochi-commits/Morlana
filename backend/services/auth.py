import hashlib
import hmac
import json
import logging
from urllib.parse import unquote

from config import settings

logger = logging.getLogger(__name__)


def validate_telegram_init_data(init_data: str) -> dict | None:
    """Validate Telegram Mini App initData using HMAC-SHA256."""
    try:
        if settings.DEV_MODE:
            logger.info("DEV_MODE: skipping HMAC validation")
            user_data = {}
            for item in init_data.split("&"):
                if not item:
                    continue
                parts = item.split("=", 1)
                if len(parts) == 2:
                    key, value = parts
                    if key == "user":
                        user_data = json.loads(unquote(value))
            if not user_data:
                user_data = {"id": 244265949, "first_name": "Dev", "username": "dev_user"}
            return user_data

        user_data = {}
        for item in init_data.split("&"):
            if not item:
                continue
            key, value = item.split("=", 1)
            if key == "user":
                user_data = json.loads(unquote(value))

        if not settings.TELEGRAM_BOT_TOKEN:
            logger.warning("No bot token configured, skipping HMAC")
            return user_data

        data_check_string = []
        received_hash = None

        for item in init_data.split("&"):
            if not item:
                continue
            key, value = item.split("=", 1)
            if key == "hash":
                received_hash = value
                continue
            if key == "signature":
                continue
            data_check_string.append(f"{key}={value}")

        if not received_hash:
            logger.warning("No hash found in initData")
            return user_data

        data_check_string.sort()
        secret_key = hmac.new(
            b"WebAppData", settings.TELEGRAM_BOT_TOKEN.encode(), hashlib.sha256
        ).digest()

        check_string = "\n".join(data_check_string)
        calculated_hash = hmac.new(
            secret_key,
            check_string.encode(),
            hashlib.sha256,
        ).hexdigest()

        logger.info(f"HMAC check_string: {check_string}")
        logger.info(f"HMAC calculated: {calculated_hash}")
        logger.info(f"HMAC received:   {received_hash}")

        if hmac.compare_digest(calculated_hash, received_hash):
            return user_data

        logger.warning("HMAC mismatch")
        return None
    except Exception as e:
        logger.error(f"HMAC validation error: {e}")
        return None
