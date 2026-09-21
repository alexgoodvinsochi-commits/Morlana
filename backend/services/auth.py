import hashlib
import hmac
import json
import logging
import time
from urllib.parse import parse_qsl

from config import settings

logger = logging.getLogger(__name__)

DEV_FALLBACK_USER = {"id": 244265949, "first_name": "Dev", "username": "dev_user"}
# Tolerated clock skew for auth_date in the future, seconds.
MAX_FUTURE_SKEW = 60


def _parse_user(params: dict[str, str]) -> dict | None:
    raw = params.get("user")
    if raw is None:
        return None
    user = json.loads(raw)
    return user if isinstance(user, dict) else None


def _has_valid_id(user: dict | None) -> bool:
    if not user:
        return False
    user_id = user.get("id")
    return isinstance(user_id, int) and not isinstance(user_id, bool)


def _calculate_hash(secret_key: bytes, params: dict[str, str], exclude: set[str]) -> str:
    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(params.items()) if key not in exclude
    )
    return hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()


def validate_telegram_init_data(init_data: str) -> dict | None:
    """Validate Telegram Mini App initData and return the Telegram user dict.

    Signed initData (has a 'hash') is always verified with HMAC-SHA256, even in
    DEV_MODE. Unsigned initData is accepted only in DEV_MODE, and only ever as
    the dev account.
    """
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True)
        params = dict(pairs)
        if len(params) != len(pairs):
            logger.warning("initData rejected: duplicate keys")
            return None

        received_hash = params.get("hash")
        if received_hash is None:
            if not settings.DEV_MODE:
                return None
            # Unsigned initData never carries a caller-supplied identity: a stray
            # DEV_MODE=true then exposes only the local dev account instead of
            # letting anyone impersonate any Telegram user.
            return dict(DEV_FALLBACK_USER)

        if not settings.TELEGRAM_BOT_TOKEN:
            logger.warning("initData rejected: TELEGRAM_BOT_TOKEN is not configured")
            return None

        secret_key = hmac.new(
            b"WebAppData", settings.TELEGRAM_BOT_TOKEN.encode(), hashlib.sha256
        ).digest()

        # 'signature' (Ed25519, for third-party validation) is excluded as before.
        # Telegram's docs define the bot-token check over all fields except 'hash',
        # so that variant is accepted too; both require the bot secret.
        variants = [{"hash", "signature"}]
        if "signature" in params:
            variants.append({"hash"})
        received = received_hash.encode()
        if not any(
            hmac.compare_digest(_calculate_hash(secret_key, params, exclude).encode(), received)
            for exclude in variants
        ):
            logger.warning("initData rejected: HMAC mismatch")
            return None

        try:
            auth_date = int(params.get("auth_date", ""))
        except ValueError:
            logger.warning("initData rejected: missing or invalid auth_date")
            return None
        now = time.time()
        if auth_date < now - settings.INIT_DATA_MAX_AGE or auth_date > now + MAX_FUTURE_SKEW:
            logger.warning("initData rejected: auth_date out of range")
            return None

        user = _parse_user(params)
        if not _has_valid_id(user):
            logger.warning("initData rejected: no valid user id")
            return None
        return user
    except Exception as e:
        logger.warning("initData validation error: %s", type(e).__name__)
        return None
