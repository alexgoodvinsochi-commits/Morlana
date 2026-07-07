"""Add user auth fields

Revision ID: c1d2e3f4a5b6
Revises: b7c8d9e0f1a2
Create Date: 2026-07-05
"""
from alembic import op
import sqlalchemy as sa

revision = 'c1d2e3f4a5b6'
down_revision = 'b7c8d9e0f1a2'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('users', sa.Column('login', sa.String(100), nullable=True))
    op.add_column('users', sa.Column('password_hash', sa.String(255), nullable=True))
    op.create_unique_constraint('uq_users_login', 'users', ['login'])

def downgrade() -> None:
    op.drop_constraint('uq_users_login', 'users', type_='unique')
    op.drop_column('users', 'password_hash')
    op.drop_column('users', 'login')
