"""Spreads as data.

A spread is one JSON file in `backend/prompts/spreads/`: its wording, its
positions, how many cards it draws, how many cycles it allows and which model
parameters it asks for. Adding a spread needs no code change.

The registry is keyed by file name, which is also the spread id used by the API
and stored in `tarot_sessions.spread_id`. A broken file raises at import, so the
container fails to start instead of serving a spread with a missing prompt.
"""
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

SPREADS_DIR = Path(__file__).parent.parent / "prompts" / "spreads"
DEFAULT_SPREAD_ID = "one-card"


class UnknownSpread(ValueError):
    """No spread with this id is loaded."""

    def __init__(self, spread_id: str):
        self.spread_id = spread_id
        super().__init__(f"Unknown spread: {spread_id}")


class SpreadPosition(BaseModel):
    """One slot of the layout. `key` ends up in DrawnCard.position."""

    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    prompt_addition: str


class Spread(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    version: int
    name: str
    description: str
    card_count: int
    positions: list[SpreadPosition]
    system_prompt: str
    synthesis_prompt: str
    # Rules that apply to the reading as a whole, appended to the system prompt.
    aggregation_constraints: list[str] = []
    max_cycles: int
    allow_reversed: bool
    requires_question: bool
    max_tokens: int
    temperature: float
    # Declared and reported by GET /spreads, but NOT enforced anywhere: /start
    # accepts a 'premium' spread from a free user. Gating it is part of stage 3
    # (quotas and money), together with the paywall. Until then a spread shipped
    # as 'premium' is free for everyone.
    tier: Literal["free", "premium"]

    @model_validator(mode="after")
    def _check_positions(self) -> "Spread":
        if self.card_count < 1:
            raise ValueError("card_count must be at least 1")
        if len(self.positions) != self.card_count:
            raise ValueError(
                f"spread '{self.id}' draws {self.card_count} cards "
                f"but declares {len(self.positions)} positions"
            )
        keys = [position.key for position in self.positions]
        if len(set(keys)) != len(keys):
            raise ValueError(f"spread '{self.id}' has duplicate position keys")
        if self.max_cycles < 1:
            raise ValueError("max_cycles must be at least 1")
        return self

    @property
    def position_keys(self) -> list[str]:
        return [position.key for position in self.positions]

    def position(self, key: str) -> SpreadPosition | None:
        for position in self.positions:
            if position.key == key:
                return position
        return None

    def label_for(self, key: str) -> str:
        """The position label for a DrawnCard, falling back to the raw key."""
        position = self.position(key)
        return position.label if position else key


class SpreadRegistry:
    """Every file in backend/prompts/spreads/*.json, keyed by file name."""

    def __init__(self, spreads: dict[str, Spread]):
        self._spreads = spreads

    def get(self, spread_id: str) -> Spread:
        """The spread, or UnknownSpread (routes turn that into 400 'Unknown spread')."""
        spread = self._spreads.get(spread_id)
        if spread is None:
            raise UnknownSpread(spread_id)
        return spread

    def has(self, spread_id: str) -> bool:
        return spread_id in self._spreads

    def all(self) -> list[Spread]:
        """Spreads in id order, the default one first."""
        return sorted(
            self._spreads.values(),
            key=lambda spread: (spread.id != DEFAULT_SPREAD_ID, spread.id),
        )

    @property
    def default(self) -> Spread:
        return self.get(DEFAULT_SPREAD_ID)


def _load_spreads() -> dict[str, Spread]:
    spreads: dict[str, Spread] = {}
    for path in sorted(SPREADS_DIR.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        spread = Spread.model_validate(raw)
        if spread.id != path.stem:
            raise ValueError(f"Spread {path.name} declares id '{spread.id}'")
        spreads[spread.id] = spread
    if DEFAULT_SPREAD_ID not in spreads:
        raise ValueError(f"Default spread '{DEFAULT_SPREAD_ID}' not found in {SPREADS_DIR}")
    return spreads


spread_registry = SpreadRegistry(_load_spreads())
