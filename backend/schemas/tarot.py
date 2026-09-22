from datetime import date, datetime, time

from pydantic import BaseModel


class AstrologyBonusRequest(BaseModel):
    initData: str
    real_name: str
    birth_date: date | None = None
    birth_time: time | None = None
    birth_location: str | None = None
    gender: str | None = None


class AstrologyBonusResponse(BaseModel):
    zodiac_sign: str
    greeting: str
    free_requests_left: int


class DrawnCard(BaseModel):
    """One card on the table. The only card shape the API speaks.

    `card_id` is the image base name in the deck manifest ('maj00', 'cups01'),
    `position` a position key of the spread, `image` a URL the client renders.
    Built by services.decks.DeckManifest.drawn_card().
    """

    deck_id: str
    card_id: str
    position: str
    reversed: bool = False
    name: str
    image: str


class ReadingStartRequest(BaseModel):
    """Both ids are optional: the routes fall back to the default spread and deck."""

    spread_id: str | None = None
    deck_id: str | None = None


class ReadingActiveResponse(BaseModel):
    session_id: str | None = None
    state: str | None = None


class ReadingAskRequest(BaseModel):
    session_id: str
    question: str


class ReadingNextRequest(BaseModel):
    session_id: str


class ReadingDrawRequest(BaseModel):
    session_id: str


class ReadingInterpretRequest(BaseModel):
    session_id: str


class ReadingSynthesisRequest(BaseModel):
    session_id: str


class ReadingCycleView(BaseModel):
    """A finished cycle of the reading in progress."""

    cycle_number: int
    question: str
    cards: list[DrawnCard] = []
    answer: str


class ReadingStateResponse(BaseModel):
    """The whole reading. /start, /ask, /draw, /next and /state all answer with it."""

    session_id: str
    state: str
    cycle_count: int
    max_cycles: int
    spread_id: str
    deck_id: str
    current_question: str | None = None
    current_cards: list[DrawnCard] = []
    cycles: list[ReadingCycleView] = []


class SpreadInfo(BaseModel):
    """An entry of GET /api/v1/tarot/spreads."""

    id: str
    name: str
    description: str
    card_count: int
    max_cycles: int
    tier: str


class DeckInfo(BaseModel):
    """An entry of GET /api/v1/tarot/decks."""

    id: str
    name: str
    back_image: str


class CycleHistory(BaseModel):
    cycle_number: int
    question: str
    cards: list[DrawnCard] = []


class ReadingHistoryItem(BaseModel):
    session_id: str
    spread_name: str
    created_at: datetime
    cycle_count: int
    synthesis: str | None
    cycles: list[CycleHistory]


class ReadingHistoryResponse(BaseModel):
    readings: list[ReadingHistoryItem]
