"""Retain early identity and separate immutable recovery evidence."""
from alembic import op
import sqlalchemy as sa

revision = "0015_recap_receipt_recovery"
down_revision = "0014_recap_media_leases"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("recap_provider_attempts", sa.Column("identity_json", sa.String(), nullable=False, server_default="[]"))
    op.add_column("recap_provider_attempts", sa.Column("recovery_receipt_json", sa.String(), nullable=True))
    op.add_column("recap_provider_attempts", sa.Column("recovery_settled_at", sa.BigInteger(), nullable=False, server_default="0"))
    op.add_column("recap_stages", sa.Column("evidence_json", sa.String(), nullable=False, server_default="{}"))


def downgrade():
    raise RuntimeError("Receipt evidence is additive and cannot be discarded")
