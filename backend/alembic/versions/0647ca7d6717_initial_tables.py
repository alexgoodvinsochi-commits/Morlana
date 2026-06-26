"""initial tables

Revision ID: 0647ca7d6717
Revises: 
Create Date: 2026-06-23 17:22:48.088479

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID


# revision identifiers, used by Alembic.
revision: str = '0647ca7d6717'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'users',
        sa.Column('telegram_id', sa.BigInteger, primary_key=True),
        sa.Column('username', sa.String(255), nullable=True),
        sa.Column('real_name', sa.String(255), nullable=False),
        sa.Column('birth_date', sa.Date, nullable=False),
        sa.Column('birth_time', sa.Time(), nullable=True),
        sa.Column('zodiac_sign', sa.String(50), nullable=True),
        sa.Column('free_requests_left', sa.Integer, server_default='3'),
        sa.Column('subscription_ends_at', TIMESTAMP(timezone=True), nullable=True),
        sa.Column('created_at', TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        'tarot_sessions',
        sa.Column('id', UUID(as_uuid=False), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', sa.BigInteger, sa.ForeignKey('users.telegram_id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(50), server_default='active'),
        sa.Column('created_at', TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        'chat_histories',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('session_id', UUID(as_uuid=False), sa.ForeignKey('tarot_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(50), nullable=False),
        sa.Column('content', sa.Text, nullable=False),
        sa.Column('created_at', TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('chat_histories')
    op.drop_table('tarot_sessions')
    op.drop_table('users')
