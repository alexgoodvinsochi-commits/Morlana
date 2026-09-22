"""Drawing cards. The server draws; the client never sends a card id."""
import secrets
from collections.abc import Sequence

from services.decks import DeckManifest
from services.spreads import Spread

# Cryptographic RNG: the draw is the product, and random.random() is seeded
# predictably enough to be replayed from the outside.
_rng = secrets.SystemRandom()


def draw_cards(
    deck: DeckManifest,
    count: int,
    allow_reversed: bool = False,
    positions: Sequence[str] | None = None,
) -> list[dict]:
    """`count` distinct cards of `deck` as DrawnCard-shaped dicts.

    `positions` are the spread's position keys, taken in order; without them the
    positions are numbered '1'..'<count>'. `reversed` is False for every card
    unless the spread allows reversed ones.
    """
    if count < 1:
        raise ValueError("count must be at least 1")
    if count > len(deck.cards):
        raise ValueError(f"deck '{deck.id}' has only {len(deck.cards)} cards, {count} asked")

    keys = list(positions) if positions is not None else [str(i) for i in range(1, count + 1)]
    if len(keys) != count:
        raise ValueError(f"{count} cards asked but {len(keys)} positions given")

    card_ids = _rng.sample(deck.card_ids, count)
    return [
        deck.drawn_card(
            card_id,
            keys[i],
            reversed=allow_reversed and _rng.choice((True, False)),
        )
        for i, card_id in enumerate(card_ids)
    ]


def draw_for_spread(deck: DeckManifest, spread: Spread) -> list[dict]:
    """The whole layout of one spread: card_count cards on its positions."""
    return draw_cards(deck, spread.card_count, spread.allow_reversed, spread.position_keys)
