"""Helpers shared by the tests.

App modules are imported inside the functions: tests/conftest.py must set the
environment before anything imports `config`.
"""
import hashlib
import hmac
import json
import time
import uuid
from urllib.parse import urlencode

from sqlalchemy import text

TEST_BOT_TOKEN = "123456:TEST"

AUTH = "/api/v1/auth"
READING = "/api/v1/tarot/reading"

DEFAULT_PASSWORD = "correct-horse-42"


def sign_init_data(
    user_id: int,
    age_seconds: int = 0,
    *,
    username: str | None = None,
    bot_token: str = TEST_BOT_TOKEN,
) -> str:
    """Telegram Mini App initData signed the way Telegram signs it.

    `age_seconds` moves auth_date into the past (negative: into the future).
    """
    user = {"id": user_id, "first_name": "Test", "username": username or f"user{user_id}"}
    params = {
        "auth_date": str(int(time.time()) - age_seconds),
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": json.dumps(user, separators=(",", ":")),
    }
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(params.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    params["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(params)


def bearer(init_data: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {init_data}"}


def auth_headers(user_id: int, age_seconds: int = 0) -> dict[str, str]:
    return bearer(sign_init_data(user_id, age_seconds))


def register_payload(login: str, password: str = DEFAULT_PASSWORD, **overrides) -> dict:
    payload = {"real_name": "Алиса", "gender": "female", "login": login, "password": password}
    payload.update(overrides)
    return payload


async def register(client, user_id: int, login: str | None = None, password: str = DEFAULT_PASSWORD):
    """Register `user_id` through the API and return its auth headers."""
    headers = auth_headers(user_id)
    resp = await client.post(
        f"{AUTH}/register", json=register_payload(login or f"user_{user_id}", password), headers=headers
    )
    assert resp.status_code == 200, resp.text
    return headers


# --- database -----------------------------------------------------------------

def _plain(value):
    # Raw SQL returns uuid columns as uuid.UUID; the API and the models use strings.
    return str(value) if isinstance(value, uuid.UUID) else value


async def db_rows(sql: str, **params) -> list[dict]:
    from database import engine

    async with engine.connect() as conn:
        result = await conn.execute(text(sql), params)
        return [{key: _plain(value) for key, value in row.items()} for row in result.mappings().all()]


async def db_scalar(sql: str, **params):
    from database import engine

    async with engine.connect() as conn:
        return _plain(await conn.scalar(text(sql), params))


async def db_execute(sql: str, **params) -> None:
    from database import engine

    async with engine.begin() as conn:
        await conn.execute(text(sql), params)


# --- reading flow -------------------------------------------------------------

def parse_sse(body: str) -> list:
    """Decode an SSE body into its payloads: dicts, plus the literal "[DONE]"."""
    events = []
    for block in body.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        assert block.startswith("data: "), f"unexpected SSE block: {block!r}"
        data = block[len("data: "):]
        events.append(data if data == "[DONE]" else json.loads(data))
    return events


async def start_reading(client, headers) -> str:
    resp = await client.post(f"{READING}/start", json={}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["session_id"]


async def get_state(client, headers, session_id: str) -> dict:
    resp = await client.get(f"{READING}/state", params={"session_id": session_id}, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def interpret(client, headers, session_id: str) -> list:
    resp = await client.post(f"{READING}/interpret", json={"session_id": session_id}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/event-stream")
    return parse_sse(resp.text)


async def run_cycle(client, headers, session_id: str, question: str) -> list:
    """ask -> draw -> interpret; returns the SSE events of the interpretation."""
    resp = await client.post(
        f"{READING}/ask", json={"session_id": session_id, "question": question}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    resp = await client.post(f"{READING}/draw", json={"session_id": session_id}, headers=headers)
    assert resp.status_code == 200, resp.text
    return await interpret(client, headers, session_id)


async def synthesize(client, headers, session_id: str) -> list:
    resp = await client.post(f"{READING}/synthesis", json={"session_id": session_id}, headers=headers)
    assert resp.status_code == 200, resp.text
    return parse_sse(resp.text)
