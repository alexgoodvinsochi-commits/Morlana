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
        await redis_service.set(self._state_key(session_id), ReadingState.WAITING.value)
        await redis_service.set(self._cycle_key(session_id), 0)
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

    async def _transition(self, session_id: str, target: ReadingState) -> ReadingState:
        current = await self.get_state(session_id)
        if current is None:
            raise ValueError(f"No active reading for session {session_id}")
        if not self._validate_transition(current, target):
            raise ValueError(
                f"Cannot transition from {current.value} to {target.value}"
            )
        await redis_service.set(self._state_key(session_id), target.value)
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

    async def complete_cycle(self, session_id: str) -> ReadingState:
        """ИНТЕРПРЕТАЦИЯ -> ГОТОВО. Increments cycle counter. Auto-completes after MAX_CYCLES."""
        new_state = await self._transition(session_id, ReadingState.READY)
        cycle = await self.get_cycle(session_id) + 1
        await redis_service.set(self._cycle_key(session_id), cycle)
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
        await redis_service.delete(self._question_key(session_id))
        await redis_service.delete(self._card_key(session_id))
        return await self._transition(session_id, ReadingState.WAITING)


reading_service = ReadingService()
