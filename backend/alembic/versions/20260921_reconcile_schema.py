"""reconcile schema with models

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-09-21

Until this revision the schema had two sources of truth: the migrations and
Base.metadata.create_all() in the app lifespan. Databases therefore exist in
two lineages that both claim revision c1d2e3f4a5b6:

* built purely by migrations: no users.gender / users.birth_location,
  users.birth_date NOT NULL, most defaulted columns nullable,
  tarot_sessions.id DEFAULT gen_random_uuid();
* built by create_all and stamped later: gender / birth_location present,
  birth_date nullable, NOT NULL columns without server defaults,
  tarot_sessions.cycle_count nullable, possibly users_login_key instead of
  uq_users_login.

Every statement below is idempotent, so both lineages converge on the schema
the models declare and `alembic check` is clean afterwards.
"""
from alembic import op

revision = 'd2e3f4a5b6c7'
down_revision = 'c1d2e3f4a5b6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- users -----------------------------------------------------------
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS gender varchar(50)")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS birth_location varchar(255)")
    op.execute("ALTER TABLE users ALTER COLUMN birth_date DROP NOT NULL")

    op.execute("UPDATE users SET free_requests_left = 3 WHERE free_requests_left IS NULL")
    op.execute("UPDATE users SET created_at = now() WHERE created_at IS NULL")
    op.execute("ALTER TABLE users ALTER COLUMN free_requests_left SET DEFAULT 3")
    op.execute("ALTER TABLE users ALTER COLUMN free_requests_left SET NOT NULL")
    op.execute("ALTER TABLE users ALTER COLUMN created_at SET DEFAULT now()")
    op.execute("ALTER TABLE users ALTER COLUMN created_at SET NOT NULL")

    # create_all names the constraint users_login_key; the migrations and the
    # models call it uq_users_login.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_users_login' AND conrelid = 'users'::regclass
            ) THEN
                IF EXISTS (
                    SELECT 1 FROM pg_constraint
                    WHERE conname = 'users_login_key' AND conrelid = 'users'::regclass
                ) THEN
                    ALTER TABLE users RENAME CONSTRAINT users_login_key TO uq_users_login;
                ELSE
                    ALTER TABLE users ADD CONSTRAINT uq_users_login UNIQUE (login);
                END IF;
            END IF;
        END
        $$
        """
    )

    # --- reading_cycles --------------------------------------------------
    op.execute("UPDATE reading_cycles SET created_at = now() WHERE created_at IS NULL")
    op.execute("ALTER TABLE reading_cycles ALTER COLUMN created_at SET DEFAULT now()")
    op.execute("ALTER TABLE reading_cycles ALTER COLUMN created_at SET NOT NULL")

    # Keep the newest row of every duplicated (session_id, cycle_number). Runs
    # before the tarot_sessions block so the cycle_count backfill counts the
    # rows that actually remain.
    op.execute(
        """
        DELETE FROM reading_cycles AS older
        USING reading_cycles AS newer
        WHERE older.session_id = newer.session_id
          AND older.cycle_number = newer.cycle_number
          AND older.id < newer.id
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_reading_cycles_session_cycle'
                  AND conrelid = 'reading_cycles'::regclass
            ) THEN
                ALTER TABLE reading_cycles
                    ADD CONSTRAINT uq_reading_cycles_session_cycle
                    UNIQUE (session_id, cycle_number);
            END IF;
        END
        $$
        """
    )

    # --- tarot_sessions --------------------------------------------------
    # The app always generates the id itself; the model has no server default.
    op.execute("ALTER TABLE tarot_sessions ALTER COLUMN id DROP DEFAULT")

    # A session without a status was never visible as an active reading, so
    # it must not become one now.
    op.execute("UPDATE tarot_sessions SET status = 'archived' WHERE status IS NULL")
    op.execute("UPDATE tarot_sessions SET created_at = now() WHERE created_at IS NULL")
    op.execute("UPDATE tarot_sessions SET updated_at = created_at WHERE updated_at IS NULL")
    op.execute("UPDATE tarot_sessions SET spread_name = 'one-card' WHERE spread_name IS NULL")
    op.execute(
        """
        UPDATE tarot_sessions
        SET cycle_count = (
            SELECT count(*) FROM reading_cycles
            WHERE reading_cycles.session_id = tarot_sessions.id
        )
        WHERE cycle_count IS NULL
        """
    )

    op.execute("ALTER TABLE tarot_sessions ALTER COLUMN status SET DEFAULT 'active'")
    op.execute("ALTER TABLE tarot_sessions ALTER COLUMN status SET NOT NULL")
    op.execute("ALTER TABLE tarot_sessions ALTER COLUMN cycle_count SET DEFAULT 0")
    op.execute("ALTER TABLE tarot_sessions ALTER COLUMN cycle_count SET NOT NULL")
    op.execute("ALTER TABLE tarot_sessions ALTER COLUMN spread_name SET DEFAULT 'one-card'")
    op.execute("ALTER TABLE tarot_sessions ALTER COLUMN spread_name SET NOT NULL")
    op.execute("ALTER TABLE tarot_sessions ALTER COLUMN updated_at SET DEFAULT now()")
    op.execute("ALTER TABLE tarot_sessions ALTER COLUMN updated_at SET NOT NULL")
    op.execute("ALTER TABLE tarot_sessions ALTER COLUMN created_at SET DEFAULT now()")
    op.execute("ALTER TABLE tarot_sessions ALTER COLUMN created_at SET NOT NULL")

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tarot_sessions_user_status_created "
        "ON tarot_sessions (user_id, status, created_at)"
    )


def downgrade() -> None:
    """Back to what the migrations up to c1d2e3f4a5b6 declare.

    Deliberately NOT reverted, because it would destroy or reject real data
    and the application code of that revision needs it anyway:

    * users.gender / users.birth_location stay (on the create_all lineage they
      predate this migration and hold user data; the c1d2e3f4a5b6-era models
      already read and write them);
    * users.birth_date stays nullable (rows with NULL exist);
    * duplicates removed from reading_cycles are not restored.
    """
    op.execute("ALTER TABLE reading_cycles DROP CONSTRAINT IF EXISTS uq_reading_cycles_session_cycle")
    op.execute("ALTER TABLE reading_cycles ALTER COLUMN created_at DROP NOT NULL")

    op.execute("DROP INDEX IF EXISTS ix_tarot_sessions_user_status_created")
    op.execute("ALTER TABLE tarot_sessions ALTER COLUMN created_at DROP NOT NULL")
    op.execute("ALTER TABLE tarot_sessions ALTER COLUMN updated_at DROP NOT NULL")
    op.execute("ALTER TABLE tarot_sessions ALTER COLUMN spread_name DROP NOT NULL")
    op.execute("ALTER TABLE tarot_sessions ALTER COLUMN status DROP NOT NULL")
    op.execute("ALTER TABLE tarot_sessions ALTER COLUMN id SET DEFAULT gen_random_uuid()")

    op.execute("ALTER TABLE users ALTER COLUMN created_at DROP NOT NULL")
    op.execute("ALTER TABLE users ALTER COLUMN free_requests_left DROP NOT NULL")
