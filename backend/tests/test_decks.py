"""The deck manifest: the only place that knows what a card is called and where
its picture is. No network, no database.

A deck is `backend/decks/<id>.json` plus a folder of images under
`frontend/public/decks/<id>/`; adding one must need no code change.
"""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

BACKEND_DIR = Path(__file__).resolve().parent.parent
# Only mounted when the whole repository is available (CI, or an extra -v mount);
# the test container sees backend/ alone.
DECK_IMAGES_DIR = BACKEND_DIR.parent / "frontend" / "public"

# What services/llm.py get_card_name() returned for 1..78 before stage 2. Written
# out here on purpose: it is the old truth the manifest may not silently rename.
LEGACY_MAJOR = [
    "Шут", "Маг", "Верховная Жрица", "Императрица", "Император",
    "Иерофант", "Влюблённые", "Колесница", "Сила", "Отшельник",
    "Колесо Фортуны", "Справедливость", "Повешенный", "Смерть",
    "Умеренность", "Дьявол", "Башня", "Звезда", "Луна", "Солнце",
    "Суд", "Мир",
]
LEGACY_RANKS = ["Туз", "2", "3", "4", "5", "6", "7", "8", "9", "10", "Паж", "Рыцарь", "Королева", "Король"]
LEGACY_SUITS = ["Кубки", "Пентакли", "Мечи", "Жезлы"]


def legacy_card_name(number: int) -> str:
    """get_card_name() as it was, verbatim."""
    if 1 <= number <= 22:
        return LEGACY_MAJOR[number - 1]
    minor_index = number - 23
    return f"{LEGACY_RANKS[minor_index % 14]} {LEGACY_SUITS[minor_index // 14]}"


def _default_deck():
    from services.decks import deck_registry

    return deck_registry.default


def _manifest_dict(**overrides) -> dict:
    manifest = {
        "id": "tiny",
        "name": "Крошечная колода",
        "image_base": "/decks/tiny",
        "back_image": "/decks/tiny/back.webp",
        "card_extension": ".jpg",
        "cards": [
            {"id": "maj00", "name": "Шут", "arcana": "major"},
            {"id": "cups01", "name": "Туз Кубки", "arcana": "minor", "suit": "cups", "rank": "Туз"},
        ],
    }
    manifest.update(overrides)
    return manifest


# --- the shipped deck ---------------------------------------------------------

def test_the_default_deck_holds_78_cards_in_the_historic_order():
    from services.decks import DEFAULT_DECK_ID, LEGACY_CARD_ORDER

    deck = _default_deck()

    assert deck.id == DEFAULT_DECK_ID == "rider-waite"
    assert len(deck.cards) == 78
    assert deck.card_ids == list(LEGACY_CARD_ORDER)
    assert [card.id for card in deck.cards if card.arcana == "major"] == [f"maj{i:02d}" for i in range(22)]
    assert len([card for card in deck.cards if card.arcana == "minor"]) == 56


def test_no_card_was_renamed_by_the_manifest():
    """The name behind every old 1..78 number is exactly the one get_card_name gave."""
    from services.decks import card_id_from_legacy_number

    deck = _default_deck()
    card_ids = [card_id_from_legacy_number(number) for number in range(1, 79)]

    assert None not in card_ids
    assert [deck.card_name(card_id) for card_id in card_ids] == [
        legacy_card_name(number) for number in range(1, 79)
    ]


def test_every_card_resolves_to_the_image_naming_convention():
    deck = _default_deck()

    for card in deck.cards:
        assert deck.card_image(card.id) == f"/decks/rider-waite/{card.id}.jpg"


@pytest.mark.skipif(
    not (DECK_IMAGES_DIR / "decks" / "rider-waite").is_dir(),
    reason="frontend/public is outside the backend container; checked in CI and with -v ./frontend:/frontend",
)
def test_every_image_the_manifest_points_at_exists_on_disk():
    deck = _default_deck()

    missing = [
        image
        for image in [deck.card_image(card.id) for card in deck.cards] + [deck.back_image]
        if not (DECK_IMAGES_DIR / image.lstrip("/")).is_file()
    ]

    assert missing == []


def test_the_manifest_file_is_what_the_registry_loaded():
    from services.decks import DECKS_DIR

    raw = json.loads((DECKS_DIR / "rider-waite.json").read_text(encoding="utf-8"))
    deck = _default_deck()

    assert raw["id"] == deck.id
    assert [card["id"] for card in raw["cards"]] == deck.card_ids
    assert deck.back_image == "/decks/rider-waite/PWR78_Card Back.webp"


# --- the DrawnCard builder ----------------------------------------------------

def test_drawn_card_is_the_shape_the_api_the_database_and_redis_all_speak():
    from schemas import DrawnCard

    deck = _default_deck()

    card = deck.drawn_card("swords07", "main")

    assert card == {
        "deck_id": "rider-waite",
        "card_id": "swords07",
        "position": "main",
        "reversed": False,
        "name": "7 Мечи",
        "image": "/decks/rider-waite/swords07.jpg",
    }
    assert DrawnCard.model_validate(card).card_id == "swords07"
    assert deck.drawn_card("swords07", "advice", reversed=True)["reversed"] is True


def test_a_card_may_override_its_image():
    from services.decks import DeckManifest

    deck = DeckManifest.model_validate(
        _manifest_dict(cards=[{"id": "maj00", "name": "Шут", "arcana": "major", "image": "/x/fool.png"}])
    )

    assert deck.card_image("maj00") == "/x/fool.png"
    assert deck.drawn_card("maj00", "main")["image"] == "/x/fool.png"


# --- the legacy 1..78 numbering ----------------------------------------------

@pytest.mark.parametrize(
    "number, card_id",
    [(1, "maj00"), (22, "maj21"), (23, "cups01"), (36, "cups14"), (57, "swords07"), (78, "wands14")],
)
def test_legacy_numbers_and_card_ids_are_the_same_deck(number, card_id):
    from services.decks import card_id_from_legacy_number, legacy_number

    assert card_id_from_legacy_number(number) == card_id
    assert legacy_number(card_id) == number


@pytest.mark.parametrize("number", [0, -1, 79, 1000])
def test_a_number_outside_the_old_deck_has_no_card(number):
    from services.decks import card_id_from_legacy_number

    assert card_id_from_legacy_number(number) is None


def test_a_card_outside_the_old_deck_has_no_number():
    from services.decks import legacy_number

    assert legacy_number("oracle01") is None


# --- the registry -------------------------------------------------------------

def test_the_registry_answers_for_a_known_deck_and_raises_for_an_unknown_one():
    from services.decks import UnknownDeck, deck_registry

    assert deck_registry.has("rider-waite") is True
    assert deck_registry.has("thoth") is False
    assert deck_registry.get("rider-waite") is deck_registry.default
    assert [deck.id for deck in deck_registry.all()][0] == "rider-waite"

    with pytest.raises(UnknownDeck) as exc_info:
        deck_registry.get("thoth")
    assert exc_info.value.deck_id == "thoth"


def test_an_unknown_card_is_a_typed_error():
    from services.decks import UnknownCard

    deck = _default_deck()
    assert deck.has_card("maj00") is True
    assert deck.has_card("maj99") is False

    with pytest.raises(UnknownCard) as exc_info:
        deck.card_name("maj99")

    assert (exc_info.value.deck_id, exc_info.value.card_id) == ("rider-waite", "maj99")


# --- a broken manifest must not start the container ---------------------------

@pytest.mark.parametrize(
    "overrides",
    [
        {"colour": "red"},
        {"cards": [{"id": "maj00", "name": "Шут", "arcana": "major", "meaning": "начало"}]},
        {"cards": [{"id": "maj00", "name": "Шут", "arcana": "trump"}]},
        {"cards": [{"id": "maj00", "arcana": "major"}]},
        {"cards": []},
        {
            "cards": [
                {"id": "maj00", "name": "Шут", "arcana": "major"},
                {"id": "maj00", "name": "Другой Шут", "arcana": "major"},
            ]
        },
    ],
    ids=["extra-key", "extra-card-key", "unknown-arcana", "card-without-a-name", "no-cards", "duplicate-ids"],
)
def test_a_manifest_that_is_not_a_deck_is_refused(overrides):
    from services.decks import DeckManifest

    with pytest.raises(ValidationError):
        DeckManifest.model_validate(_manifest_dict(**overrides))


def _load_decks_from(tmp_path, monkeypatch, files: dict[str, str]):
    import services.decks

    decks_dir = tmp_path / "decks"
    decks_dir.mkdir()
    for name, content in files.items():
        (decks_dir / name).write_text(content, encoding="utf-8")
    monkeypatch.setattr(services.decks, "DECKS_DIR", decks_dir)
    return services.decks._load_decks()


def test_a_broken_manifest_fails_the_load(tmp_path, monkeypatch):
    with pytest.raises(ValidationError):
        _load_decks_from(
            tmp_path,
            monkeypatch,
            {"rider-waite.json": json.dumps(_manifest_dict(id="rider-waite", colour="red"))},
        )


def test_a_manifest_whose_id_does_not_match_its_file_name_fails_the_load(tmp_path, monkeypatch):
    files = {
        "rider-waite.json": json.dumps(_manifest_dict(id="rider-waite"), ensure_ascii=False),
        "other.json": json.dumps(_manifest_dict(id="tiny"), ensure_ascii=False),
    }

    with pytest.raises(ValueError, match="declares id 'tiny'"):
        _load_decks_from(tmp_path, monkeypatch, files)


def test_a_folder_without_the_default_deck_fails_the_load(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="Default deck 'rider-waite' not found"):
        _load_decks_from(tmp_path, monkeypatch, {"tiny.json": json.dumps(_manifest_dict())})


# --- drawing ------------------------------------------------------------------

def test_the_draw_uses_a_cryptographic_rng():
    """random.random() is seeded predictably enough to be replayed from outside."""
    import secrets

    import services.tarot

    assert isinstance(services.tarot._rng, secrets.SystemRandom)


def test_draw_for_spread_puts_one_card_on_every_position(two_card_spread):
    from services.spreads import spread_registry
    from services.tarot import draw_for_spread

    deck = _default_deck()

    one = draw_for_spread(deck, spread_registry.default)
    two = draw_for_spread(deck, two_card_spread)

    assert [card["position"] for card in one] == ["main"]
    assert [card["position"] for card in two] == ["situation", "advice"]
    assert all(deck.has_card(card["card_id"]) for card in one + two)
    assert all(set(card) == {"deck_id", "card_id", "position", "reversed", "name", "image"} for card in two)


def test_a_draw_never_repeats_a_card():
    from services.tarot import draw_cards

    deck = _default_deck()

    cards = draw_cards(deck, len(deck.cards))

    assert sorted(card["card_id"] for card in cards) == sorted(deck.card_ids)
    assert [card["position"] for card in cards] == [str(i) for i in range(1, 79)]


def test_reversed_cards_appear_only_when_the_spread_allows_them():
    from services.tarot import draw_cards

    deck = _default_deck()

    upright = [draw_cards(deck, 1)[0]["reversed"] for _ in range(50)]
    allowed = [draw_cards(deck, 1, allow_reversed=True)[0]["reversed"] for _ in range(200)]

    assert upright == [False] * 50
    assert any(allowed)  # 200 upright in a row would be a 1-in-2^200 accident


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"count": 0}, "count must be at least 1"),
        ({"count": 79}, "has only 78 cards, 79 asked"),
        ({"count": 2, "positions": ["only-one"]}, "2 cards asked but 1 positions given"),
    ],
    ids=["no-cards", "more-than-the-deck", "positions-do-not-match"],
)
def test_an_impossible_draw_is_refused(kwargs, message):
    from services.tarot import draw_cards

    with pytest.raises(ValueError, match=message):
        draw_cards(_default_deck(), **kwargs)


def test_a_second_deck_is_just_another_file(tmp_path, monkeypatch):
    from services.decks import DeckRegistry

    decks = _load_decks_from(
        tmp_path,
        monkeypatch,
        {
            "rider-waite.json": json.dumps(_manifest_dict(id="rider-waite"), ensure_ascii=False),
            "tiny.json": json.dumps(_manifest_dict(), ensure_ascii=False),
        },
    )
    registry = DeckRegistry(decks)

    assert [deck.id for deck in registry.all()] == ["rider-waite", "tiny"]  # the default first
    assert registry.get("tiny").drawn_card("cups01", "main") == {
        "deck_id": "tiny",
        "card_id": "cups01",
        "position": "main",
        "reversed": False,
        "name": "Туз Кубки",
        "image": "/decks/tiny/cups01.jpg",
    }
