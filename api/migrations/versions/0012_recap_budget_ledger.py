"""Add immutable plans and attempt-linked financial obligations."""
import sqlalchemy as sa
from alembic import op

revision = "0012_recap_budget_ledger"
down_revision = "0011_recap_budget"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("recap_budget_plans",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("episode_id", sa.String(), nullable=False),
        sa.Column("series_id", sa.String(), nullable=False),
        sa.Column("plan_key", sa.String(), nullable=False),
        sa.Column("digest", sa.String(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("episode_id", "plan_key", name="uq_recap_budget_plan"))
    for name in ("episode_id", "series_id"):
        op.create_index(f"ix_recap_budget_plans_{name}", "recap_budget_plans", [name])
    op.create_table("recap_budget_allocations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("plan_id", sa.String(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("operation_id", sa.String(), nullable=False),
        sa.Column("attempt_id", sa.String(), unique=True, nullable=True),
        sa.Column("month_key", sa.String(), nullable=False),
        sa.Column("max_microusd", sa.BigInteger(), nullable=False),
        sa.Column("outstanding_microusd", sa.BigInteger(), nullable=False),
        sa.Column("actual_microusd", sa.BigInteger(), nullable=True),
        sa.Column("rate_json", sa.String(), nullable=False),
        sa.Column("evidence_json", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.UniqueConstraint("plan_id", "key", name="uq_recap_budget_allocation"))
    for name in ("plan_id", "operation_id"):
        op.create_index(f"ix_recap_budget_allocations_{name}", "recap_budget_allocations", [name])


def downgrade():
    op.drop_table("recap_budget_allocations")
    op.drop_table("recap_budget_plans")
