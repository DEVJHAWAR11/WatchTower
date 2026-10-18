"""Enable RLS on alembic_version so Supabase's security advisor sees every public table locked down.

Revision ID: 0003_alembic_version_rls
Revises: 0002_security_and_seed
"""

from alembic import op

revision = "0003_alembic_version_rls"
down_revision = "0002_security_and_seed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE alembic_version ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
            REVOKE ALL ON alembic_version FROM anon, authenticated;
          END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE alembic_version DISABLE ROW LEVEL SECURITY")
