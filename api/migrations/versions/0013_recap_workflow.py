"""Durable recap periods, immutable observations and qualified source inventories."""
from alembic import op
import sqlalchemy as sa

revision = "0013_recap_workflow"
down_revision = "0012_recap_budget_ledger"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("recap_episodes",
        sa.Column("episode_id", sa.String(), primary_key=True),
        sa.Column("series_id", sa.String(), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("period_id", sa.String(), nullable=False),
        sa.Column("league_id", sa.String(), nullable=False),
        sa.Column("week", sa.Integer(), nullable=False),
        sa.Column("round", sa.Integer(), nullable=True),
        sa.Column("nfl_weeks_json", sa.String(), nullable=False),
        sa.Column("lifecycle", sa.String(), nullable=False),
        sa.Column("hold", sa.String(), nullable=False),
        sa.Column("admitted_at", sa.BigInteger(), nullable=False),
        sa.Column("eligible_at", sa.BigInteger(), nullable=False),
        sa.Column("observed_at", sa.BigInteger(), nullable=False),
        sa.Column("stable_since", sa.BigInteger(), nullable=False),
        sa.Column("next_observation_at", sa.BigInteger(), nullable=False),
        sa.Column("facts_digest", sa.String(), nullable=False),
        sa.Column("source_digest", sa.String(), nullable=False),
        sa.Column("article_digest", sa.String(), nullable=False),
        sa.Column("latest_observation_id", sa.String(), nullable=False),
        sa.UniqueConstraint("series_id", "season", "period_id", name="uq_recap_episode_period"))
    for name in ("series_id", "league_id", "next_observation_at"):
        op.create_index(f"ix_recap_episodes_{name}", "recap_episodes", [name])
    op.create_table("recap_observations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("episode_id", sa.String(), nullable=False),
        sa.Column("observed_at", sa.BigInteger(), nullable=False),
        sa.Column("snapshot_json", sa.String(), nullable=False),
        sa.Column("snapshot_digest", sa.String(), nullable=False),
        sa.Column("facts_digest", sa.String(), nullable=False),
        sa.Column("provider_timestamps_json", sa.String(), nullable=False),
        sa.Column("source_pointers_json", sa.String(), nullable=False),
        sa.Column("decision", sa.String(), nullable=False))
    op.create_index("ix_recap_observations_episode_id", "recap_observations", ["episode_id"])
    op.create_table("recap_schedule_inventories",
        sa.Column("version", sa.String(), primary_key=True),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("revision", sa.String(), nullable=False),
        sa.Column("qualified_at", sa.BigInteger(), nullable=False),
        sa.Column("inventory_json", sa.String(), nullable=False))
    op.create_index("ix_recap_schedule_inventories_season", "recap_schedule_inventories", ["season"])


def downgrade():
    op.drop_table("recap_schedule_inventories")
    op.drop_table("recap_observations")
    op.drop_table("recap_episodes")
