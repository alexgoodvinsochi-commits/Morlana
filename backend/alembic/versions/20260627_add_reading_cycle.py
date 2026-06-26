"""add reading cycle and cycle_count

Revision ID: a1b2c3d4e5f6
Revises: 0647ca7d6717
Create Date: 2026-06-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '0647ca7d6717'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'tarot_sessions',
        sa.Column('cycle_count', sa.Integer, server_default='0', nullable=False),
    )

    op.create_table(
        'reading_cycles',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('session_id', UUID(as_uuid=False), sa.ForeignKey('tarot_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('cycle_number', sa.Integer, nullable=False),
        sa.Column('question', sa.Text, nullable=False),
        sa.Column('card_id', sa.Integer, nullable=False),
        sa.Column('interpretation', sa.Text, nullable=False),
        sa.Column('created_at', TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('reading_cycles')
    op.drop_column('tarot_sessions', 'cycle_count')
