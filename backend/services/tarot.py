import random


def draw_cards(count: int) -> list[int]:
    """Draw random unique tarot cards (1-78, Rider-Waite deck)."""
    return random.sample(range(1, 79), count)
