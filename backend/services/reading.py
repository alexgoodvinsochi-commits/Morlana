import logging
from enum import Enum

from services.redis import redis_service

logger = logging.getLogger(__name__)


class ReadingState(str, Enum):
    WAITING = "ОЖИДАНИЕ"
    QUESTION_ASKED = "ВОПРОС ЗАДАН"
    CARD_DRAWN = "КАРТА ВЫТЯНУТА"
    INTERPRETATION = "ИНТЕРПРЕТАЦИЯ"
    READY = "ГОТОВО"
    COMPLETED = "ЗАВЕРШЕНО"


VALID_TRANSITIONS: dict[ReadingState, set[ReadingState]] = {
    ReadingState.WAITING: {ReadingState.QUESTION_ASKED},
    ReadingState.QUESTION_ASKED: {ReadingState.CARD_DRAWN},
    ReadingState.CARD_DRAWN: {ReadingState.INTERPRETATION},
    ReadingState.INTERPRETATION: {ReadingState.READY},
    ReadingState.READY: {ReadingState.WAITING, ReadingState.COMPLETED},
    ReadingState.COMPLETED: set(),
}

MAX_CYCLES = 6
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


class ReadingService:
    """Manages the reading state machine for tarot sessions.

    States: ОЖИДАНИЕ → ВОПРОС ЗАДАН → КАРТА ВЫТЯНУТА → ИНТЕРПРЕТАЦИЯ → ГОТОВО → ЗАВЕРШЕНО
    Maximum 6 cycles per session, after which automatic synthesis (ЗАВЕРШЕНО) occurs.
    """

    _KEY_PREFIX = "reading:"

    @staticmethod
    def _state_key(session_id: str) -> str:
        return f"{ReadingService._KEY_PREFIX}{session_id}:state"

    @staticmethod
    def _cycle_key(session_id: str) -> str:
        return f"{ReadingService._KEY_PREFIX}{session_id}:cycle"

    @staticmethod
    def _question_key(session_id: str) -> str:
        return f"{ReadingService._KEY_PREFIX}{session_id}:question"

    @staticmethod
    def _card_key(session_id: str) -> str:
        return f"{ReadingService._KEY_PREFIX}{session_id}:card"

    async def start(self, session_id: str) -> ReadingState:
        await redis_service.set(self._state_key(session_id), ReadingState.WAITING.value, ttl=SESSION_TTL)
        await redis_service.set(self._cycle_key(session_id), 0, ttl=SESSION_TTL)
        return ReadingState.WAITING

    async def get_state(self, session_id: str) -> ReadingState | None:
        state_val = await redis_service.get(self._state_key(session_id))
        if state_val is None:
            return None
        try:
            return ReadingState(state_val)
        except ValueError:
            logger.error(f"Invalid state value '{state_val}' for session {session_id}")
            return None

    async def get_cycle(self, session_id: str) -> int:
        cycle = await redis_service.get(self._cycle_key(session_id))
        return int(cycle) if cycle is not None else 0

    def _validate_transition(self, current: ReadingState, target: ReadingState) -> bool:
        allowed = VALID_TRANSITIONS.get(current, set())
        if target not in allowed:
            logger.warning(
                f"Invalid transition: {current.value} -> {target.value}. "
                f"Allowed: {[s.value for s in allowed]}"
            )
            return False
        return True

    async def _check_transition(self, session_id: str, target: ReadingState) -> None:
        """Raise ReadingNotFound / InvalidTransition unless `target` is reachable now."""
        current = await self.get_state(session_id)
        if current is None:
            raise ReadingNotFound(session_id)
        if not self._validate_transition(current, target):
            raise InvalidTransition(current, target)

    async def _transition(self, session_id: str, target: ReadingState) -> ReadingState:
        await self._check_transition(session_id, target)
        await redis_service.set(self._state_key(session_id), target.value, ttl=SESSION_TTL)
        return target

    async def ask(self, session_id: str) -> ReadingState:
        """ОЖИДАНИЕ -> ВОПРОС ЗАДАН"""
        return await self._transition(session_id, ReadingState.QUESTION_ASKED)

    async def draw(self, session_id: str) -> ReadingState:
        """ВОПРОС ЗАДАН -> КАРТА ВЫТЯНУТА"""
        return await self._transition(session_id, ReadingState.CARD_DRAWN)

    async def mark_interpreting(self, session_id: str) -> ReadingState:
        """КАРТА ВЫТЯНУТА -> ИНТЕРПРЕТАЦИЯ"""
        return await self._transition(session_id, ReadingState.INTERPRETATION)

    async def complete_cycle(self, session_id: str, cycle: int | None = None) -> ReadingState:
        """ИНТЕРПРЕТАЦИЯ -> ГОТОВО. Advances the cycle counter. Auto-completes after MAX_CYCLES.

        `cycle` is the number of the cycle that was just saved; without it the
        counter is incremented. Passing it keeps a repeated call idempotent.
        """
        new_state = await self._transition(session_id, ReadingState.READY)
        if cycle is None:
            cycle = await self.get_cycle(session_id) + 1
        await redis_service.set(self._cycle_key(session_id), cycle, ttl=SESSION_TTL)
        if cycle >= MAX_CYCLES:
            logger.info(f"Session {session_id} reached {MAX_CYCLES} cycles, auto-completing")
            await self._transition(session_id, ReadingState.COMPLETED)
            return ReadingState.COMPLETED
        return new_state

    async def end(self, session_id: str) -> ReadingState:
        """ГОТОВО -> ЗАВЕРШЕНО"""
        return await self._transition(session_id, ReadingState.COMPLETED)

    async def start_new_cycle(self, session_id: str) -> ReadingState:
        """ГОТОВО -> ОЖИДАНИЕ (начало нового цикла)"""
        # Validate first: a wrong-state call must not wipe the current question and card.
        await self._check_transition(session_id, ReadingState.WAITING)
        await redis_service.delete(self._question_key(session_id))
        await redis_service.delete(self._card_key(session_id))
        return await self._transition(session_id, ReadingState.WAITING)


reading_service = ReadingService()
