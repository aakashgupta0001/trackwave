"""Phase 7: uncertainty & confidence columns on predictions.

First Alembic migration in the repository — earlier phases created the schema via
metadata.create_all (the versions directory was empty), so this migration is written
defensively: every statement uses IF NOT EXISTS / idempotent guards so it is safe
against databases whose predictions table already carries these columns.
"""

revision = "0007_uncertainty_confidence"
down_revision = None
branch_labels = None
depends_on = None

from alembic import op  # noqa: E402


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE predictions
            ADD COLUMN IF NOT EXISTS lower_eta TIMESTAMPTZ NULL,
            ADD COLUMN IF NOT EXISTS upper_eta TIMESTAMPTZ NULL,
            ADD COLUMN IF NOT EXISTS interval_level NUMERIC(3, 2) NULL,
            ADD COLUMN IF NOT EXISTS confidence_score INTEGER NULL,
            ADD COLUMN IF NOT EXISTS confidence_level VARCHAR(10) NULL
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE predictions
            DROP COLUMN IF EXISTS confidence_level,
            DROP COLUMN IF EXISTS confidence_score,
            DROP COLUMN IF EXISTS interval_level,
            DROP COLUMN IF EXISTS upper_eta,
            DROP COLUMN IF EXISTS lower_eta
        """
    )
