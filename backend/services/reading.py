import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from services.redis import redis_service

logger = logging.getLogger(__name__)


class ReadingState(str, Enum):
    WAITING = "WAITING"
    QUESTION_ASKED = "QUESTION_ASKED"
    CARDS_DRAWN = "CARDS_DRAWN"
    INTERPRETATION = "INTERPRETATION"
    READY = "READY"
    COMPLETED = "COMPLETED"


VALID_TRANSITIONS: dict[ReadingState, set[ReadingState]] = {
    ReadingState.WAITING: {ReadingState.QUESTION_ASKED},
    ReadingState.QUESTION_ASKED: {ReadingState.CARDS_DRAWN},
    ReadingState.CARDS_DRAWN: {ReadingState.INTERPRETATION},
    ReadingState.INTERPRETATION: {ReadingState.READY},
    ReadingState.READY: {ReadingState.WAITING, ReadingState.COMPLETED},
    ReadingState.COMPLETED: set(),
}

SESSION_TTL = 3600  # 1 hour


class ReadingNotFound(ValueError):
    """The reading has no live state in Redis (never started, or expired)."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        super().__init__(f"No active reading for session {session_id}")


class InvalidTransition(ValueError):
    """The state machine does not allow moving from `current` to `target`."""

    def __init__(self, current: ReadingState, target: ReadingState):
        self.current = current
        self.target = target
        super().__init__(f"Cannot transition from {current.value} to {target.value}")


@dataclass
class ReadingSession:
    """Everything a live reading holds. Stored as one JSON document in Redis.

    `cards` are the cards of the current cycle (DrawnCard dicts, one per position
    of the spread); `cycle_data` is one entry per finished cycle, shaped like the
    API's ReadingCycleView: {cycle_number, question, cards, answer}.
    """

    session_id: str
    state: ReadingState
    spread_id: str
    deck_id: str
    cycle: int = 0
    question: str | None = None
    cards: list[dict] = field(default_factory=list)
    cycle_data: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "cycle": self.cycle,
            "spread_id": self.spread_id,
            "deck_id": self.deck_id,
            "question": self.question,
            "cards": self.cards,
            "cycle_data": self.cycle_data,
        }

    @classmethod
    def from_dict(cls, session_id: str, raw: Any) -> "ReadingSession | None":
        """The document, or None for anything this version cannot read.

        Readings written by the previous version lived in five keys, none of them
        under this name, so they simply look expired and answer 404.
        """
        if not isinstance(raw, dict):
            return None
        try:
            state = ReadingState(raw["state"])
        except (KeyError, TypeError, ValueError):
            logger.error("Unreadable reading document for session %s", session_id)
            return None
        return cls(
            session_id=session_id,
            state=state,
            spread_id=raw.get("spread_id") or "",
            deck_id=raw.get("deck_id") or "",
            cycle=int(raw.get("cycle") or 0),
            question=raw.get("question"),
            cards=list(raw.get("cards") or []),
            cycle_data=list(raw.get("cycle_data") or []),
        )


class ReadingService:
    """The reading state machine, over one Redis key per reading.

    States: WAITING -> QUESTION_ASKED -> CARDS_DRAWN -> INTERPRETATION -> READY,
    then either the next cycle (WAITING) or COMPLETED. The cycle limit belongs to
    the spread, so callers pass `max_cycles` in instead of the service knowing it.
    """

    _KEY_PREFIX = "reading:"

    @staticmethod
    def key(session_id: str) -> str:
        return f"{ReadingService._KEY_PREFIX}{session_id}"

    async def _save(self, session: ReadingSession) -> None:
        # One key, one TTL: every write moves the whole reading forward an hour,
        # so no part of it can expire from under a live state.
        await redis_service.set(self.key(session.session_id), session.to_dict(), ttl=SESSION_TTL)

    async def get(self, session_id: str) -> ReadingSession | None:
        raw = await redis_service.get(self.key(session_id))
        if raw is None:
            return None
        return ReadingSession.from_dict(session_id, raw)

    async def get_state(self, session_id: str) -> ReadingState | None:
        session = await self.get(session_id)
        return session.state if session is not None else None

    async def _require(self, session_id: str) -> ReadingSession:
        session = await self.get(session_id)
        if session is None:
            raise ReadingNotFound(session_id)
        return session

    def _require_transition(self, session: ReadingSession, target: ReadingState) -> None:
        """Raise InvalidTransition unless `target` is reachable from the current state."""
        allowed = VALID_TRANSITIONS.get(session.state, set())
        if target not in allowed:
            logger.warning(
                "Invalid transition: %s -> %s. Allowed: %s",
                session.state.value,
                target.value,
                [s.value for s in allowed],
            )
            raise InvalidTransition(session.state, target)

    async def start(self, session_id: str, spread_id: str, deck_id: str) -> ReadingSession:
        session = ReadingSession(
            session_id=session_id,
            state=ReadingState.WAITING,
            spread_id=spread_id,
            deck_id=deck_id,
        )
        await self._save(session)
        return session

    async def ask(self, session_id: str, question: str) -> ReadingSession:
        """WAITING -> QUESTION_ASKED, keeping the question."""
        session = await self._require(session_id)
        self._require_transition(session, ReadingState.QUESTION_ASKED)
        session.state = ReadingState.QUESTION_ASKED
        session.question = question
        await self._save(session)
        return session

    async def draw(self, session_id: str, cards: list[dict]) -> ReadingSession:
        """QUESTION_ASKED -> CARDS_DRAWN, keeping the cards the server drew."""
        session = await self._require(session_id)
        self._require_transition(session, ReadingState.CARDS_DRAWN)
        session.state = ReadingState.CARDS_DRAWN
        session.cards = cards
        await self._save(session)
        return session

    async def mark_interpreting(self, session_id: str) -> ReadingSession:
        """CARDS_DRAWN -> INTERPRETATION"""
        session = await self._require(session_id)
        self._require_transition(session, ReadingState.INTERPRETATION)
        session.state = ReadingState.INTERPRETATION
        await self._save(session)
        return session

    async def complete_cycle(
        self,
        session_id: str,
        cycle: int,
        max_cycles: int,
        cycle_entry: dict | None = None,
    ) -> ReadingSession:
        """INTERPRETATION -> READY, or straight to COMPLETED on the last cycle.

        `cycle` is the number of the cycle that was just committed to Postgres, so
        a repeated call is idempotent. `cycle_entry` joins `cycle_data` unless that
        cycle is already there (a retry that resumed an already committed row).
        This is a single write: the cycle is in Postgres before the state moves.
        """
        session = await self._require(session_id)
        self._require_transition(session, ReadingState.READY)
        if cycle_entry is not None and len(session.cycle_data) < cycle:
            session.cycle_data.append(cycle_entry)
        session.cycle = cycle
        session.state = ReadingState.READY
        if max_cycles and cycle >= max_cycles:
            logger.info("Session %s reached %d cycles, auto-completing", session_id, max_cycles)
            session.state = ReadingState.COMPLETED
        await self._save(session)
        return session

    async def end(self, session_id: str) -> ReadingSession:
        """READY -> COMPLETED"""
        session = await self._require(session_id)
        self._require_transition(session, ReadingState.COMPLETED)
        session.state = ReadingState.COMPLETED
        await self._save(session)
        return session

    async def start_new_cycle(self, session_id: str) -> ReadingSession:
        """READY -> WAITING (the next cycle of the same reading)."""
        session = await self._require(session_id)
        # Validate first: a wrong-state call must not wipe the question and cards.
        self._require_transition(session, ReadingState.WAITING)
        session.state = ReadingState.WAITING
        session.question = None
        session.cards = []
        await self._save(session)
        return session


reading_service = ReadingService()
