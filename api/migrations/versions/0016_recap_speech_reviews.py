"""Reviewed entity spellings, separate from generated Script content."""
from alembic import op
import sqlalchemy as sa

revision = "0016_recap_speech_reviews"
down_revision = "0015_recap_receipt_recovery"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("recap_speech_reviews",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("series_id", sa.String(), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("entity_kind", sa.String(), nullable=False),
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("canonical_name", sa.String(), nullable=False),
        sa.Column("canonical_token", sa.String(), nullable=False),
        sa.Column("reusable", sa.Boolean(), nullable=False),
        sa.Column("aliases_json", sa.String(), nullable=False),
        sa.Column("script_id", sa.String(), nullable=False),
        sa.Column("script_digest", sa.String(), nullable=False),
        sa.Column("script_revision", sa.Integer(), nullable=False),
        sa.Column("reviewer_id", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False))
    op.create_index("ix_recap_speech_reviews_series_id", "recap_speech_reviews", ["series_id"])


def downgrade():
    raise RuntimeError("Reviewed speech provenance requires explicit archival review")
