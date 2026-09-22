"""GET /api/v1/tarot/spreads and /decks: what a reading can be started with."""
import pytest

from tests.helpers import CATALOG, auth_headers, register

ALICE = 6001
STRANGER = 6002

ONE_CARD = {
    "id": "one-card",
    "name": "Одна карта",
    "description": "Быстрый расклад: один вопрос — одна карта",
    "card_count": 1,
    "max_cycles": 6,
    "tier": "free",
}
RIDER_WAITE = {
    "id": "rider-waite",
    "name": "Райдер-Уэйт",
    "back_image": "/decks/rider-waite/PWR78_Card Back.webp",
}


async def test_spreads_lists_the_registry(client):
    headers = await register(client, ALICE)

    resp = await client.get(f"{CATALOG}/spreads", headers=headers)

    assert resp.status_code == 200
    assert resp.json() == [ONE_CARD]


async def test_decks_lists_the_registry(client):
    headers = await register(client, ALICE)

    resp = await client.get(f"{CATALOG}/decks", headers=headers)

    assert resp.status_code == 200
    assert resp.json() == [RIDER_WAITE]
    # The card back is what the client needs; the 78 cards are not in the catalog.
    assert set(resp.json()[0]) == {"id", "name", "back_image"}


async def test_a_spread_added_as_a_file_shows_up_in_the_catalog(client, two_card_spread):
    headers = await register(client, ALICE)

    resp = await client.get(f"{CATALOG}/spreads", headers=headers)

    assert resp.status_code == 200
    assert resp.json() == [
        ONE_CARD,
        {
            "id": "two-card",
            "name": "Две карты",
            "description": "Ситуация и совет",
            "card_count": 2,
            "max_cycles": 2,
            "tier": "free",
        },
    ]


@pytest.mark.parametrize("path", ["/spreads", "/decks"])
async def test_the_catalog_needs_an_authorization_header(client, path):
    resp = await client.get(f"{CATALOG}{path}")

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Missing or invalid Authorization header"


@pytest.mark.parametrize("path", ["/spreads", "/decks"])
async def test_the_catalog_is_closed_to_an_unregistered_account(client, path):
    await register(client, ALICE)

    resp = await client.get(f"{CATALOG}{path}", headers=auth_headers(STRANGER))

    assert resp.status_code == 404
    assert resp.json()["detail"] == "User not found"
