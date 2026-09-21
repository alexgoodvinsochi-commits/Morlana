import hashlib
from urllib.parse import parse_qsl, urlencode

import pytest

from tests.helpers import (
    AUTH,
    DEFAULT_PASSWORD,
    READING,
    auth_headers,
    bearer,
    db_execute,
    db_rows,
    db_scalar,
    register,
    register_payload,
    sign_init_data,
)

ALICE = 1001
BOB = 1002


# --- Telegram initData --------------------------------------------------------

@pytest.mark.parametrize(
    "method, path",
    [
        ("GET", f"{AUTH}/me"),
        ("POST", f"{AUTH}/register"),
        ("POST", f"{AUTH}/login"),
        ("GET", f"{READING}/active"),
        ("GET", f"{READING}/history"),
        ("POST", f"{READING}/start"),
    ],
)
async def test_no_authorization_header_is_401(client, method, path):
    body = register_payload("alice") if path.endswith("/register") else {"login": "alice", "password": "x"}
    resp = await client.request(method, path, json=body if method == "POST" else None)

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Missing or invalid Authorization header"
    assert await db_scalar("SELECT count(*) FROM users") == 0


async def test_unsigned_init_data_is_401(client):
    await register(client, ALICE, "alice")
    signed = dict(parse_qsl(sign_init_data(ALICE)))
    signed.pop("hash")

    # Same payload as a registered user, but without the signature; and the DEV_MODE token.
    for init_data in (urlencode(signed), "dev"):
        resp = await client.get(f"{AUTH}/me", headers=bearer(init_data))
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid Telegram data"


async def test_tampered_init_data_is_401(client):
    await register(client, ALICE, "alice")
    original = dict(parse_qsl(sign_init_data(BOB)))

    # Bob keeps his valid hash but claims to be Alice.
    forged_user = dict(original, user=original["user"].replace(str(BOB), str(ALICE)))
    # A valid payload with a corrupted hash.
    last = original["hash"][-1]
    forged_hash = dict(original, hash=original["hash"][:-1] + ("0" if last != "0" else "1"))
    # Signed with another bot's token.
    other_bot = sign_init_data(ALICE, bot_token="654321:OTHER")

    for init_data in (urlencode(forged_user), urlencode(forged_hash), other_bot):
        resp = await client.get(f"{AUTH}/me", headers=bearer(init_data))
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid Telegram data"


async def test_stale_auth_date_is_401(client):
    await register(client, ALICE, "alice")

    fresh_enough = await client.get(f"{AUTH}/me", headers=auth_headers(ALICE, age_seconds=86400 - 120))
    stale = await client.get(f"{AUTH}/me", headers=auth_headers(ALICE, age_seconds=86400 + 120))
    from_the_future = await client.get(f"{AUTH}/me", headers=auth_headers(ALICE, age_seconds=-3600))

    assert fresh_enough.status_code == 200
    assert stale.status_code == 401
    assert from_the_future.status_code == 401


# --- register / me ------------------------------------------------------------

async def test_me_is_404_before_registration(client):
    resp = await client.get(f"{AUTH}/me", headers=auth_headers(ALICE))

    assert resp.status_code == 404
    assert resp.json()["detail"] == "User not found"


async def test_register_then_me(client):
    headers = auth_headers(ALICE)

    registered = await client.post(f"{AUTH}/register", json=register_payload("alice"), headers=headers)
    me = await client.get(f"{AUTH}/me", headers=headers)

    expected = {"telegram_id": ALICE, "real_name": "Алиса", "gender": "female", "login": "alice"}
    assert registered.status_code == 200
    assert registered.json() == expected
    assert me.status_code == 200
    assert me.json() == expected

    rows = await db_rows("SELECT * FROM users")
    assert len(rows) == 1
    row = rows[0]
    assert (row["telegram_id"], row["login"], row["username"]) == (ALICE, "alice", f"user{ALICE}")
    assert row["free_requests_left"] == 3
    assert row["created_at"] is not None
    # The password is stored as a salted scrypt hash, never in the clear.
    assert row["password_hash"].startswith("scrypt$")
    assert DEFAULT_PASSWORD not in row["password_hash"]


async def test_second_register_is_409(client):
    headers = await register(client, ALICE, "alice")
    hash_before = await db_scalar("SELECT password_hash FROM users WHERE telegram_id = :id", id=ALICE)

    resp = await client.post(
        f"{AUTH}/register", json=register_payload("alice2", password="another-pass-1"), headers=headers
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "Account already registered"
    rows = await db_rows("SELECT login, password_hash FROM users")
    assert rows == [{"login": "alice", "password_hash": hash_before}]


async def test_register_with_login_of_another_account_is_409(client):
    await register(client, ALICE, "shared_login")

    resp = await client.post(
        f"{AUTH}/register", json=register_payload("shared_login"), headers=auth_headers(BOB)
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "Login already taken"
    assert await db_rows("SELECT telegram_id FROM users") == [{"telegram_id": ALICE}]


@pytest.mark.parametrize(
    "overrides",
    [
        {"login": "ab"},
        {"login": "bad login!"},
        {"login": "x" * 33},
        {"password": "12345"},
        {"gender": "other"},
        {"real_name": "   "},
    ],
    ids=["login-too-short", "login-bad-chars", "login-too-long", "password-too-short", "bad-gender", "blank-name"],
)
async def test_register_bad_fields_is_422(client, overrides):
    payload = {**register_payload("alice"), **overrides}

    resp = await client.post(f"{AUTH}/register", json=payload, headers=auth_headers(ALICE))

    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"] == ["body", next(iter(overrides))]
    assert await db_scalar("SELECT count(*) FROM users") == 0


# --- login --------------------------------------------------------------------

async def test_login_with_correct_password(client):
    headers = await register(client, ALICE, "alice")

    resp = await client.post(
        f"{AUTH}/login", json={"login": "alice", "password": DEFAULT_PASSWORD}, headers=headers
    )

    assert resp.status_code == 200
    assert resp.json() == {"telegram_id": ALICE, "real_name": "Алиса", "gender": "female", "login": "alice"}


async def test_login_with_wrong_password_is_401(client):
    headers = await register(client, ALICE, "alice")

    wrong_password = await client.post(
        f"{AUTH}/login", json={"login": "alice", "password": "not-the-password"}, headers=headers
    )
    unknown_login = await client.post(
        f"{AUTH}/login", json={"login": "nobody", "password": DEFAULT_PASSWORD}, headers=headers
    )

    for resp in (wrong_password, unknown_login):
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid login or password"


async def test_login_from_another_telegram_account_is_401(client):
    await register(client, ALICE, "alice")
    await register(client, BOB, "bob")

    # Bob knows Alice's login and password, but signs in from his own Telegram account.
    resp = await client.post(
        f"{AUTH}/login", json={"login": "alice", "password": DEFAULT_PASSWORD}, headers=auth_headers(BOB)
    )

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid login or password"


async def test_legacy_sha256_hash_logs_in_and_is_rehashed(client):
    salt = "0f1e2d3c4b5a6978"
    legacy_hash = f"{salt}:{hashlib.sha256(f'{salt}{DEFAULT_PASSWORD}'.encode()).hexdigest()}"
    await db_execute(
        "INSERT INTO users (telegram_id, real_name, login, password_hash) "
        "VALUES (:id, 'Алиса', 'alice', :hash)",
        id=ALICE,
        hash=legacy_hash,
    )
    headers = auth_headers(ALICE)
    credentials = {"login": "alice", "password": DEFAULT_PASSWORD}

    wrong = await client.post(f"{AUTH}/login", json={"login": "alice", "password": "wrong-pass"}, headers=headers)
    assert wrong.status_code == 401
    assert await db_scalar("SELECT password_hash FROM users") == legacy_hash

    first = await client.post(f"{AUTH}/login", json=credentials, headers=headers)
    assert first.status_code == 200
    assert first.json()["login"] == "alice"

    rehashed = await db_scalar("SELECT password_hash FROM users")
    assert rehashed != legacy_hash
    assert rehashed.startswith("scrypt$16384$8$1$")

    # The new hash verifies the same password, and is not rehashed again.
    second = await client.post(f"{AUTH}/login", json=credentials, headers=headers)
    assert second.status_code == 200
    assert await db_scalar("SELECT password_hash FROM users") == rehashed


# --- rate limiting ------------------------------------------------------------

async def test_register_is_rate_limited(client, rate_limits_on):
    headers = auth_headers(ALICE)

    statuses = []
    for _ in range(6):
        resp = await client.post(f"{AUTH}/register", json=register_payload("alice"), headers=headers)
        statuses.append(resp.status_code)

    # 5/minute: one registration, four "already registered", then the limiter answers.
    assert statuses == [200, 409, 409, 409, 409, 429]
