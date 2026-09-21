from urllib.parse import parse_qsl, urlencode

from tests.helpers import AUTH, auth_headers, db_rows, db_scalar, sign_init_data

BONUS = "/api/v1/astrology/bonus"
CAROL = 4001


async def test_bonus_creates_the_profile_without_credentials(client):
    resp = await client.post(
        BONUS,
        json={
            "initData": sign_init_data(CAROL),
            "real_name": "Карина",
            "gender": "female",
            "birth_date": "1990-04-15",
            "birth_location": "Казань",
        },
    )

    assert resp.status_code == 200
    assert resp.json()["zodiac_sign"] == "Овен"
    assert resp.json()["free_requests_left"] == 3
    rows = await db_rows("SELECT telegram_id, real_name, gender, zodiac_sign, birth_location, login FROM users")
    assert rows == [
        {
            "telegram_id": CAROL,
            "real_name": "Карина",
            "gender": "female",
            "zodiac_sign": "Овен",
            "birth_location": "Казань",
            "login": None,
        }
    ]
    # A profile without login/password is not a registered account yet.
    assert (await client.get(f"{AUTH}/me", headers=auth_headers(CAROL))).status_code == 404


async def test_bonus_without_a_birth_date_and_with_bad_init_data(client):
    ok = await client.post(BONUS, json={"initData": sign_init_data(CAROL), "real_name": "Карина"})
    assert ok.status_code == 200
    assert ok.json()["zodiac_sign"] == ""

    forged = dict(parse_qsl(sign_init_data(CAROL)))
    forged["user"] = forged["user"].replace(str(CAROL), "4002")
    rejected = await client.post(BONUS, json={"initData": urlencode(forged), "real_name": "Мошенник"})

    assert rejected.status_code == 401
    assert await db_scalar("SELECT count(*) FROM users") == 1
    assert await db_scalar("SELECT real_name FROM users") == "Карина"
