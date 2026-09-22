"""The spread registry: one JSON file per spread, validated when it is loaded.
No network, no database.

Adding a spread must be a file-only change, and a broken file must stop the
container instead of reaching a user as a half-built prompt.
"""
import json

import pytest
from pydantic import ValidationError

VALID_SPREAD = {
    "id": "two-card",
    "version": 1,
    "name": "Две карты",
    "description": "Ситуация и совет",
    "card_count": 2,
    "positions": [
        {"key": "situation", "label": "Ситуация", "prompt_addition": "Что происходит."},
        {"key": "advice", "label": "Совет", "prompt_addition": "Что делать."},
    ],
    "system_prompt": "Ответь по двум картам.",
    "synthesis_prompt": "Сведи расклады воедино.",
    "aggregation_constraints": ["Свяжи карты между собой."],
    "max_cycles": 2,
    "allow_reversed": True,
    "requires_question": True,
    "max_tokens": 777,
    "temperature": 0.25,
    "tier": "free",
}


def _spread_dict(**overrides) -> dict:
    spread = json.loads(json.dumps(VALID_SPREAD))
    spread.update(overrides)
    return spread


# --- the shipped spread -------------------------------------------------------

def test_one_card_is_the_default_and_keeps_the_values_it_ships_with():
    from services.spreads import DEFAULT_SPREAD_ID, spread_registry

    spread = spread_registry.default

    assert spread.id == DEFAULT_SPREAD_ID == "one-card"
    assert (spread.name, spread.card_count, spread.max_cycles) == ("Одна карта", 1, 6)
    assert (spread.allow_reversed, spread.requires_question, spread.tier) == (False, True, "free")
    assert (spread.max_tokens, spread.temperature) == (2048, 0.7)
    assert spread.position_keys == ["main"]
    assert spread.positions[0].label == "Главная карта"
    assert spread.label_for("main") == "Главная карта"
    # The prompts live in the file, not in Python.
    assert spread.system_prompt.startswith("Формат ответа")
    assert spread.synthesis_prompt.startswith("Синтезируй несколько раскладов")
    assert len(spread.aggregation_constraints) == 2


def test_the_registry_answers_for_a_known_spread_and_raises_for_an_unknown_one():
    from services.spreads import UnknownSpread, spread_registry

    assert spread_registry.has("one-card") is True
    assert spread_registry.has("celtic-cross") is False
    assert spread_registry.get("one-card") is spread_registry.default
    assert [spread.id for spread in spread_registry.all()][0] == "one-card"

    with pytest.raises(UnknownSpread) as exc_info:
        spread_registry.get("celtic-cross")
    assert exc_info.value.spread_id == "celtic-cross"


def test_a_position_key_that_is_not_in_the_spread_falls_back_to_itself():
    from services.spreads import spread_registry

    spread = spread_registry.default

    assert spread.position("main").key == "main"
    assert spread.position("nowhere") is None
    assert spread.label_for("nowhere") == "nowhere"  # a stored card never breaks a prompt


# --- validation ---------------------------------------------------------------

def test_a_valid_file_needs_nothing_but_its_fields():
    from services.spreads import Spread

    spread = Spread.model_validate(_spread_dict())

    assert spread.position_keys == ["situation", "advice"]
    assert spread.label_for("advice") == "Совет"


def test_aggregation_constraints_may_be_left_out():
    from services.spreads import Spread

    spread_dict = _spread_dict()
    del spread_dict["aggregation_constraints"]

    assert Spread.model_validate(spread_dict).aggregation_constraints == []


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"layout_type": "cross"}, "Extra inputs are not permitted"),
        ({"card_count": 3}, "draws 3 cards but declares 2 positions"),
        ({"card_count": 1}, "draws 1 cards but declares 2 positions"),
        (
            {
                "card_count": 2,
                "positions": [
                    {"key": "same", "label": "Раз", "prompt_addition": "a"},
                    {"key": "same", "label": "Два", "prompt_addition": "b"},
                ],
            },
            "duplicate position keys",
        ),
        ({"card_count": 0, "positions": []}, "card_count must be at least 1"),
        ({"max_cycles": 0}, "max_cycles must be at least 1"),
        ({"tier": "gold"}, "Input should be 'free' or 'premium'"),
        (
            {"positions": [{"key": "one", "label": "Раз", "prompt_addition": "a", "hint": "no"}]},
            "Extra inputs are not permitted",
        ),
    ],
    ids=[
        "extra-key",
        "too-few-positions",
        "too-many-positions",
        "duplicate-position-keys",
        "no-cards",
        "no-cycles",
        "unknown-tier",
        "extra-key-in-a-position",
    ],
)
def test_a_file_that_is_not_a_spread_is_refused(overrides, message):
    from services.spreads import Spread

    with pytest.raises(ValidationError, match=message):
        Spread.model_validate(_spread_dict(**overrides))


@pytest.mark.parametrize(
    "missing",
    ["system_prompt", "synthesis_prompt", "positions", "max_tokens", "temperature", "version"],
)
def test_a_spread_without_one_of_its_required_fields_is_refused(missing):
    from services.spreads import Spread

    spread_dict = _spread_dict()
    del spread_dict[missing]

    with pytest.raises(ValidationError):
        Spread.model_validate(spread_dict)


# --- loading a directory ------------------------------------------------------

def _load_spreads_from(tmp_path, monkeypatch, files: dict[str, dict]):
    import services.spreads

    spreads_dir = tmp_path / "spreads"
    spreads_dir.mkdir()
    for name, content in files.items():
        (spreads_dir / name).write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(services.spreads, "SPREADS_DIR", spreads_dir)
    return services.spreads._load_spreads()


def test_a_broken_file_fails_the_load(tmp_path, monkeypatch):
    with pytest.raises(ValidationError):
        _load_spreads_from(
            tmp_path,
            monkeypatch,
            {"one-card.json": _spread_dict(id="one-card", card_count=5)},
        )


def test_a_spread_whose_id_does_not_match_its_file_name_fails_the_load(tmp_path, monkeypatch):
    files = {
        "one-card.json": _spread_dict(
            id="one-card",
            card_count=1,
            positions=[{"key": "main", "label": "Главная карта", "prompt_addition": "a"}],
        ),
        "three-card.json": _spread_dict(),  # declares id 'two-card'
    }

    with pytest.raises(ValueError, match="declares id 'two-card'"):
        _load_spreads_from(tmp_path, monkeypatch, files)


def test_a_folder_without_the_default_spread_fails_the_load(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="Default spread 'one-card' not found"):
        _load_spreads_from(tmp_path, monkeypatch, {"two-card.json": _spread_dict()})


def test_a_second_spread_is_just_another_file(tmp_path, monkeypatch):
    from services.spreads import SpreadRegistry

    spreads = _load_spreads_from(
        tmp_path,
        monkeypatch,
        {
            "one-card.json": _spread_dict(
                id="one-card",
                card_count=1,
                positions=[{"key": "main", "label": "Главная карта", "prompt_addition": "a"}],
            ),
            "two-card.json": _spread_dict(),
        },
    )
    registry = SpreadRegistry(spreads)

    assert [spread.id for spread in registry.all()] == ["one-card", "two-card"]  # the default first
    assert registry.get("two-card").card_count == 2
    assert registry.default.id == "one-card"
