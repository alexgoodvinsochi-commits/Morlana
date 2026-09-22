"""spreads, decks and multi-card cycles

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-09-22

Stage 2 turns the domain into data. A reading now remembers which spread and
which deck it was started with, and a cycle keeps every card it drew as
DrawnCard objects ({deck_id, card_id, position, reversed, name, image}) instead
of one integer.

reading_cycles.card_id / card_name stay: they are backfilled into `cards` here
and the application keeps writing them for the FIRST card of every cycle, so
readers that still expect the old columns keep working. card_id becomes nullable
because a future spread may draw cards the 1..78 numbering cannot express.

Every statement is idempotent, so a partially applied run can be repeated.

The downgrade rebuilds the old columns from `cards`: the name always, the 1..78
number only for the Rider-Waite ids that numbering can express. A cycle drawn
from another deck therefore rolls back with card_id NULL, and the pre-stage-2
code cannot serve it (its CycleHistory.card_id is a plain int): those rows have
to be given a number or removed by hand before that code is put back.
"""
from alembic import op

revision = 'f4a5b6c7d8e9'
down_revision = 'e3f4a5b6c7d8'
branch_labels = None
depends_on = None

# The historic 1..78 numbering: 1-22 major arcana, then 14 cards each of cups,
# pents, swords, wands, with the names services/llm.py get_card_name() returned.
# Spelled out here on purpose: this is a fact about the old rows and must not
# follow later edits of backend/decks/rider-waite.json.
_SUIT_KEYS = "ARRAY['cups','pents','swords','wands']"
_SUIT_NAMES = "ARRAY['Кубки','Пентакли','Мечи','Жезлы']"
_RANK_NAMES = (
    "ARRAY['Туз','2','3','4','5','6','7','8','9','10','Паж','Рыцарь','Королева','Король']"
)
_MAJOR_NAMES = (
    "ARRAY['Шут','Маг','Верховная Жрица','Императрица','Император',"
    "'Иерофант','Влюблённые','Колесница','Сила','Отшельник',"
    "'Колесо Фортуны','Справедливость','Повешенный','Смерть',"
    "'Умеренность','Дьявол','Башня','Звезда','Луна','Солнце','Суд','Мир']"
)

# mod() instead of the % operator: a literal % in a statement sent through the
# DBAPI is asking for a placeholder-interpolation surprise.
_CARD_KEY = f"""
    CASE
        WHEN card_id BETWEEN 1 AND 22
            THEN 'maj' || lpad((card_id - 1)::text, 2, '0')
        ELSE ({_SUIT_KEYS})[((card_id - 23) / 14) + 1]
             || lpad((mod(card_id - 23, 14) + 1)::text, 2, '0')
    END
"""

_CARD_NAME = f"""
    CASE
        WHEN card_id BETWEEN 1 AND 22 THEN ({_MAJOR_NAMES})[card_id]
        ELSE ({_RANK_NAMES})[mod(card_id - 23, 14) + 1]
             || ' ' || ({_SUIT_NAMES})[((card_id - 23) / 14) + 1]
    END
"""


def upgrade() -> None:
    op.execute(
        "ALTER TABLE tarot_sessions "
        "ADD COLUMN IF NOT EXISTS spread_id varchar(50) NOT NULL DEFAULT 'one-card'"
    )
    op.execute(
        "ALTER TABLE tarot_sessions "
        "ADD COLUMN IF NOT EXISTS deck_id varchar(50) NOT NULL DEFAULT 'rider-waite'"
    )

    op.execute("ALTER TABLE reading_cycles ADD COLUMN IF NOT EXISTS cards jsonb")
    op.execute("ALTER TABLE reading_cycles ALTER COLUMN card_id DROP NOT NULL")

    # Existing rows: one card, always the 'main' position of one-card, never reversed.
    op.execute(
        f"""
        WITH mapped AS (
            SELECT id,
                   ({_CARD_KEY}) AS card_key,
                   ({_CARD_NAME}) AS card_title
            FROM reading_cycles
            WHERE cards IS NULL
              AND card_id BETWEEN 1 AND 78
        )
        UPDATE reading_cycles AS rc
        SET cards = jsonb_build_array(jsonb_build_object(
                'deck_id', 'rider-waite',
                'card_id', m.card_key,
                'position', 'main',
                'reversed', false,
                'name', COALESCE(rc.card_name, m.card_title),
                'image', '/decks/rider-waite/' || m.card_key || '.jpg'
            ))
        FROM mapped m
        WHERE rc.id = m.id
        """
    )


def downgrade() -> None:
    # The name is in the JSON whatever deck the card came from, so rescue it
    # first and on its own: the numbering below only understands Rider-Waite
    # ids, and a card from another deck would lose its name for good when
    # `cards` is dropped. Only rows without a number are touched — with one the
    # old code derives the name from it, so nothing there is at risk.
    op.execute(
        """
        UPDATE reading_cycles
        SET card_name = left(cards->0->>'name', 100)
        WHERE card_id IS NULL
          AND card_name IS NULL
          AND jsonb_typeof(cards) = 'array'
          AND jsonb_array_length(cards) > 0
          AND cards->0->>'name' IS NOT NULL
        """
    )
    # Put the 1..78 number back for any row written after the upgrade that only
    # has `cards`, so the NOT NULL below has nothing to trip on.
    op.execute(
        """
        UPDATE reading_cycles
        SET card_id = CASE
                WHEN left(cards->0->>'card_id', 3) = 'maj'
                    THEN (substring(cards->0->>'card_id' FROM 4))::int + 1
                ELSE 22
                     + 14 * (array_position(
                         ARRAY['cups','pents','swords','wands'],
                         regexp_replace(cards->0->>'card_id', '[0-9]+$', '')) - 1)
                     + (regexp_replace(cards->0->>'card_id', '^[a-z]+', ''))::int
            END
        WHERE card_id IS NULL
          AND jsonb_typeof(cards) = 'array'
          AND jsonb_array_length(cards) > 0
          AND cards->0->>'card_id' ~ '^(maj|cups|pents|swords|wands)[0-9]{2}$'
        """
    )
    # A card that predates this revision always had a number, so in practice no
    # row is left out. One that is (a future spread's card) keeps the column
    # nullable rather than failing the rollback.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM reading_cycles WHERE card_id IS NULL) THEN
                ALTER TABLE reading_cycles ALTER COLUMN card_id SET NOT NULL;
            END IF;
        END
        $$
        """
    )
    op.execute("ALTER TABLE reading_cycles DROP COLUMN IF EXISTS cards")

    op.execute("ALTER TABLE tarot_sessions DROP COLUMN IF EXISTS deck_id")
    op.execute("ALTER TABLE tarot_sessions DROP COLUMN IF EXISTS spread_id")
