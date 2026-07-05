"""Add history fields

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-07-05
"""
from alembic import op
import sqlalchemy as sa

revision = 'b7c8d9e0f1a2'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('tarot_sessions', sa.Column('synthesis', sa.Text(), nullable=True))
    op.add_column('tarot_sessions', sa.Column('spread_name', sa.String(100), server_default='one-card'))
    op.add_column('tarot_sessions', sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()))
    op.add_column('reading_cycles', sa.Column('card_name', sa.String(100), nullable=True))

def downgrade() -> None:
    op.drop_column('reading_cycles', 'card_name')
    op.drop_column('tarot_sessions', 'updated_at')
    op.drop_column('tarot_sessions', 'spread_name')
    op.drop_column('tarot_sessions', 'synthesis')
