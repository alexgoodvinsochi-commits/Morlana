from datetime import date, datetime, time

from pydantic import BaseModel, field_validator


class AstrologyBonusRequest(BaseModel):
    initData: str
    real_name: str
    birth_date: date
    birth_time: time | None = None
    birth_location: str | None = None


class AstrologyBonusResponse(BaseModel):
    zodiac_sign: str
    greeting: str
    free_requests_left: int


class CheckAccessResponse(BaseModel):
    has_access: bool
    free_requests_left: int


class DrawRequest(BaseModel):
    layout_type: str = "3_cards"
    count: int = 3

    @field_validator("count")
    @classmethod
    def validate_count(cls, v: int) -> int:
        if v < 1 or v > 10:
            raise ValueError("count must be between 1 and 10")
        return v


class DrawResponse(BaseModel):
    cards: list[int]
    layout_type: str


class PredictRequest(BaseModel):
    session_id: str
    layout_type: str
    cards: list[int]
    question: str


class SessionCloseRequest(BaseModel):
    session_id: str
