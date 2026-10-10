"""Additive restricted media leases and provider/account controls."""
from alembic import op
import sqlalchemy as sa

revision = "0014_recap_media_leases"
down_revision = "0013_recap_workflow"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("provider_account_controls",
        sa.Column("provider", sa.String(), primary_key=True, nullable=False),
        sa.Column("account_key", sa.String(), primary_key=True, nullable=False),
        sa.Column("hold", sa.String(), primary_key=False, nullable=False),
        sa.Column("cooldown_until", sa.BigInteger(), primary_key=False, nullable=False),
        sa.Column("max_concurrency", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("revision", sa.Integer(), primary_key=False, nullable=False))
    op.create_table("recap_stages",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("episode_id", sa.String(), primary_key=False, nullable=False),
        sa.Column("revision", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("kind", sa.String(), primary_key=False, nullable=False),
        sa.Column("chunk", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("script_id", sa.String(), primary_key=False, nullable=False),
        sa.Column("operation_id", sa.String(), primary_key=False, nullable=False),
        sa.Column("predecessor_id", sa.String(), primary_key=False, nullable=False),
        sa.Column("input_json", sa.String(), primary_key=False, nullable=False),
        sa.Column("input_digest", sa.String(), primary_key=False, nullable=False),
        sa.Column("policy_digest", sa.String(), primary_key=False, nullable=False),
        sa.Column("state", sa.String(), primary_key=False, nullable=False),
        sa.Column("reason", sa.String(), primary_key=False, nullable=False),
        sa.Column("worker_id", sa.String(), primary_key=False, nullable=False),
        sa.Column("generation", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("epoch", sa.String(), primary_key=False, nullable=False),
        sa.Column("lease_until", sa.BigInteger(), primary_key=False, nullable=False),
        sa.Column("next_attempt_at", sa.BigInteger(), primary_key=False, nullable=False),
        sa.Column("failures", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("result_json", sa.String(), primary_key=False, nullable=False),
        sa.Column("created_at", sa.BigInteger(), primary_key=False, nullable=False),
        sa.UniqueConstraint('episode_id', 'revision', 'kind', 'chunk', name="uq_recap_stage"))
    op.create_index("ix_recap_stages_state", "recap_stages", ['state'])
    op.create_index("ix_recap_stages_episode_id", "recap_stages", ['episode_id'])
    op.create_index("ix_recap_stages_operation_id", "recap_stages", ['operation_id'])
    op.create_table("recap_provider_attempts",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("stage_id", sa.String(), primary_key=False, nullable=False),
        sa.Column("episode_id", sa.String(), primary_key=False, nullable=False),
        sa.Column("series_id", sa.String(), primary_key=False, nullable=False),
        sa.Column("operation_id", sa.String(), primary_key=False, nullable=False),
        sa.Column("provider", sa.String(), primary_key=False, nullable=False),
        sa.Column("account_key", sa.String(), primary_key=False, nullable=False),
        sa.Column("worker_id", sa.String(), primary_key=False, nullable=False),
        sa.Column("generation", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("epoch", sa.String(), primary_key=False, nullable=False),
        sa.Column("request_digest", sa.String(), primary_key=False, nullable=False),
        sa.Column("request_json", sa.String(), primary_key=False, nullable=False),
        sa.Column("pricing_json", sa.String(), primary_key=False, nullable=False),
        sa.Column("authority_digest", sa.String(), primary_key=False, nullable=False),
        sa.Column("state", sa.String(), primary_key=False, nullable=False),
        sa.Column("error_code", sa.String(), primary_key=False, nullable=False),
        sa.Column("receipt_json", sa.String(), primary_key=False, nullable=True),
        sa.Column("cost_microusd", sa.BigInteger(), primary_key=False, nullable=True),
        sa.Column("created_at", sa.BigInteger(), primary_key=False, nullable=False),
        sa.Column("settled_at", sa.BigInteger(), primary_key=False, nullable=False),
        sa.UniqueConstraint('stage_id'))
    op.create_index("ix_recap_provider_attempts_operation_id", "recap_provider_attempts", ['operation_id'])
    op.create_index("ix_recap_provider_attempts_episode_id", "recap_provider_attempts", ['episode_id'])
    op.create_index("ix_recap_provider_attempts_state", "recap_provider_attempts", ['state'])
    op.create_index("ix_recap_provider_attempts_series_id", "recap_provider_attempts", ['series_id'])
    op.create_table("recap_assets",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("stage_id", sa.String(), primary_key=False, nullable=False),
        sa.Column("generation", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("digest", sa.String(), primary_key=False, nullable=False),
        sa.Column("size", sa.BigInteger(), primary_key=False, nullable=False),
        sa.Column("media_type", sa.String(), primary_key=False, nullable=False),
        sa.Column("storage_key", sa.String(), primary_key=False, nullable=False),
        sa.Column("created_at", sa.BigInteger(), primary_key=False, nullable=False),
        sa.UniqueConstraint('storage_key'))
    op.create_index("ix_recap_assets_stage_id", "recap_assets", ['stage_id'])
    op.add_column("provider_attempts", sa.Column("provider", sa.String(), nullable=False, server_default="anthropic"))
    op.add_column("provider_attempts", sa.Column("account_key", sa.String(), nullable=False, server_default="primary"))
    from app.config import get_settings
    alias = get_settings().anthropic_account_alias
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE provider_attempts SET account_key = :alias"), {"alias": alias})
    conn.execute(sa.text("""INSERT INTO provider_account_controls
        (provider, account_key, hold, cooldown_until, max_concurrency, revision)
        SELECT 'anthropic', :alias, provider_hold, cooldown_until, 1, 1
        FROM generation_control WHERE id = 'global' AND (provider_hold != '' OR cooldown_until > 0)"""), {"alias": alias})
    conn.execute(sa.text("UPDATE generation_control SET provider_hold = '', cooldown_until = 0"))


def downgrade():
    raise RuntimeError("Media receipt ledger is additive; downgrade requires explicit archival review")
