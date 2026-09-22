"""Tarot decks as data.

A deck is a folder of images under `frontend/public/decks/<deck_id>/` plus one
manifest in `backend/decks/<deck_id>.json`. Adding a deck needs no code change.

The manifest is the single source of truth for card names and images: nothing
else in backend or frontend knows what a card is called or where its picture is.
A broken manifest raises at import, like the prompt files do, so the container
fails to start instead of serving a half-built deck.
"""
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, PrivateAttr, field_validator, model_validator

DECKS_DIR = Path(__file__).parent.parent / "decks"
DEFAULT_DECK_ID = "rider-waite"


class UnknownDeck(ValueError):
    """No deck with this id is loaded."""

    def __init__(self, deck_id: str):
        self.deck_id = deck_id
        super().__init__(f"Unknown deck: {deck_id}")


class UnknownCard(ValueError):
    """The deck has no card with this id."""

    def __init__(self, deck_id: str, card_id: str):
        self.deck_id = deck_id
        self.card_id = card_id
        super().__init__(f"Unknown card {card_id} in deck {deck_id}")


class DeckCard(BaseModel):
    """One card of a deck. `id` is the image base name on disk ('maj00', 'cups01')."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    arcana: Literal["major", "minor"]
    suit: str | None = None
    rank: str | None = None
    # Overrides the '<image_base>/<id><card_extension>' convention for this card only.
    image: str | None = None


class DeckManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    image_base: str
    back_image: str
    card_extension: str
    cards: list[DeckCard]

    _by_id: dict[str, DeckCard] = PrivateAttr(default_factory=dict)

    @field_validator("cards")
    @classmethod
    def _cards_are_unique(cls, cards: list[DeckCard]) -> list[DeckCard]:
        if not cards:
            raise ValueError("deck has no cards")
        ids = [card.id for card in cards]
        duplicates = sorted({card_id for card_id in ids if ids.count(card_id) > 1})
        if duplicates:
            raise ValueError(f"duplicate card ids: {', '.join(duplicates)}")
        return cards

    @model_validator(mode="after")
    def _index_cards(self) -> "DeckManifest":
        self._by_id = {card.id: card for card in self.cards}
        return self

    @property
    def card_ids(self) -> list[str]:
        return [card.id for card in self.cards]

    def card(self, card_id: str) -> DeckCard:
        """The card, or UnknownCard."""
        card = self._by_id.get(card_id)
        if card is None:
            raise UnknownCard(self.id, card_id)
        return card

    def has_card(self, card_id: str) -> bool:
        return card_id in self._by_id

    def card_name(self, card_id: str) -> str:
        return self.card(card_id).name

    def card_image(self, card_id: str) -> str:
        """'/decks/<deck_id>/<card_id>.jpg' unless the manifest overrides it."""
        card = self.card(card_id)
        return card.image or f"{self.image_base}/{card.id}{self.card_extension}"

    def drawn_card(self, card_id: str, position: str, reversed: bool = False) -> dict:
        """A DrawnCard-shaped dict: what the API, Redis and reading_cycles.cards store."""
        return {
            "deck_id": self.id,
            "card_id": card_id,
            "position": position,
            "reversed": bool(reversed),
            "name": self.card_name(card_id),
            "image": self.card_image(card_id),
        }


class DeckRegistry:
    """Every manifest in backend/decks/*.json, keyed by file name."""

    def __init__(self, decks: dict[str, DeckManifest]):
        self._decks = decks

    def get(self, deck_id: str) -> DeckManifest:
        """The deck, or UnknownDeck (routes turn that into 400 'Unknown deck')."""
        deck = self._decks.get(deck_id)
        if deck is None:
            raise UnknownDeck(deck_id)
        return deck

    def has(self, deck_id: str) -> bool:
        return deck_id in self._decks

    def all(self) -> list[DeckManifest]:
        """Decks in id order, the default one first."""
        return sorted(
            self._decks.values(),
            key=lambda deck: (deck.id != DEFAULT_DECK_ID, deck.id),
        )

    @property
    def default(self) -> DeckManifest:
        return self.get(DEFAULT_DECK_ID)


def _load_decks() -> dict[str, DeckManifest]:
    decks: dict[str, DeckManifest] = {}
    for path in sorted(DECKS_DIR.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        deck = DeckManifest.model_validate(raw)
        if deck.id != path.stem:
            raise ValueError(f"Deck {path.name} declares id '{deck.id}'")
        decks[deck.id] = deck
    if DEFAULT_DECK_ID not in decks:
        raise ValueError(f"Default deck '{DEFAULT_DECK_ID}' not found in {DECKS_DIR}")
    return decks


deck_registry = DeckRegistry(_load_decks())


# --- legacy 1..78 card numbers -------------------------------------------------
#
# Before stage 2 a card was an int 1..78: 1-22 the major arcana, then 14 cards
# each of cups, pents, swords, wands. reading_cycles.card_id still holds that int
# for the first card of a cycle, so the two mappings below stay. They are written
# out here, not derived from a manifest, because the historic order is a fact
# about the old data and must not move when a manifest is edited.

_LEGACY_SUITS = ("cups", "pents", "swords", "wands")

LEGACY_CARD_ORDER: tuple[str, ...] = tuple(
    [f"maj{i:02d}" for i in range(22)]
    + [f"{suit}{rank:02d}" for suit in _LEGACY_SUITS for rank in range(1, 15)]
)

_LEGACY_NUMBERS = {card_id: number for number, card_id in enumerate(LEGACY_CARD_ORDER, 1)}


def legacy_number(card_id: str) -> int | None:
    """The old 1..78 number of a card id, or None for a card outside that deck."""
    return _LEGACY_NUMBERS.get(card_id)


def card_id_from_legacy_number(number: int) -> str | None:
    """The card id behind an old 1..78 number, or None if it is out of range."""
    if 1 <= number <= len(LEGACY_CARD_ORDER):
        return LEGACY_CARD_ORDER[number - 1]
    return None
