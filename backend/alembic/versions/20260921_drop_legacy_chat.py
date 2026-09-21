"""drop legacy chat

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-09-21

chat_histories belonged to the removed /api/v1/tarot/predict/stream flow.
The cyclic reading keeps its data in reading_cycles.
"""
from alembic import op

revision = 'e3f4a5b6c7d8'
down_revision = 'd2e3f4a5b6c7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS chat_histories")


def downgrade() -> None:
    # Recreates the table empty: the rows dropped by upgrade() are gone.
    # IF NOT EXISTS: a pre-e3f4a5b6c7d8 build started against the migrated database
    # brings the table back through its create_all, and the rollback must not trip on it.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_histories (
            id SERIAL NOT NULL,
            session_id UUID NOT NULL,
            role VARCHAR(50) NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
            PRIMARY KEY (id),
            FOREIGN KEY (session_id) REFERENCES tarot_sessions (id) ON DELETE CASCADE
        )
        """
    )
