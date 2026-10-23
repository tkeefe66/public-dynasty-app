"""Persist free refresh cooldown across worker restarts."""
import sqlalchemy as sa
from alembic import op

revision = "0020_refresh_backoff"
down_revision = "0019_recap_retention"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("generation_operations", sa.Column(
        "next_attempt_at", sa.BigInteger(), nullable=False, server_default="0"))
    op.add_column("generation_operations", sa.Column(
        "retry_count", sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    op.drop_column("generation_operations", "retry_count")
    op.drop_column("generation_operations", "next_attempt_at")
