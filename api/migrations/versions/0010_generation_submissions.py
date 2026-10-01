"""Bind every idempotency key, including a request joining another operation."""
import sqlalchemy as sa
from alembic import op

revision = "0010_generation_submissions"
down_revision = "0009_generation_control"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("generation_submissions",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("request_digest", sa.String(), nullable=False),
        sa.Column("operation_id", sa.String(), nullable=False))


def downgrade():
    raise RuntimeError("Submission history prevents replay; use a forward recovery migration.")
