"""Add editable recap ceilings without activating generation or modifying receipts."""
import sqlalchemy as sa
from alembic import op

revision = "0011_recap_budget"
down_revision = "0010_generation_submissions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("recap_budget_policies",
        sa.Column("series_id", sa.String(), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("caps_json", sa.String(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False))


def downgrade():
    op.drop_table("recap_budget_policies")
