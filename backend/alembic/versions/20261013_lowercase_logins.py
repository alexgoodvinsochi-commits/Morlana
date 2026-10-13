"""lowercase existing logins

Logins became case-insensitive: they are stored and compared in lower case
(routes/auth.py). This migration brings existing rows in line.

Revision ID: a5b6c7d8e9f0
Revises: f4a5b6c7d8e9
Create Date: 2026-10-13
"""
from alembic import op

revision = "a5b6c7d8e9f0"
down_revision = "f4a5b6c7d8e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Two rows differing only by case would collide under uq_users_login.
    # Refuse loudly instead of picking a winner: this needs a human decision.
    clashes = conn.exec_driver_sql(
        """
        SELECT lower(login), count(*)
        FROM users
        WHERE login IS NOT NULL
        GROUP BY lower(login)
        HAVING count(*) > 1
        """
    ).fetchall()
    if clashes:
        names = ", ".join(f"{login} ({count} rows)" for login, count in clashes)
        raise RuntimeError(
            "Cannot lowercase logins, these would collide: " + names
        )

    conn.exec_driver_sql(
        "UPDATE users SET login = lower(login) WHERE login IS NOT NULL AND login <> lower(login)"
    )


def downgrade() -> None:
    # The original capitalisation is not recoverable, and lower-case logins keep
    # working with the previous code: nothing to undo.
    pass
