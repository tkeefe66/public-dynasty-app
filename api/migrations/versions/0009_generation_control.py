"""Durable generation controls and artifacts. Additive; execution starts held."""
import sqlalchemy as sa
from alembic import op

revision = "0009_generation_control"
down_revision = "0008_yahoo_connections"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('generation_control',
        sa.Column('id', sa.String(), primary_key=True, nullable=False),
        sa.Column('epoch', sa.String(), nullable=False),
        sa.Column('hold', sa.String(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('provider_hold', sa.String(), nullable=False),
        sa.Column('cooldown_until', sa.BigInteger(), nullable=False),
        sa.Column('breakers_json', sa.String(), nullable=False),
    )
    op.create_table('generation_policies',
        sa.Column('scope', sa.String(), primary_key=True, nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('value_json', sa.String(), nullable=False),
    )
    op.create_table('league_series',
        sa.Column('id', sa.String(), primary_key=True, nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('lifecycle', sa.String(), nullable=False),
        sa.Column('profile', sa.String(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('activated_at', sa.BigInteger(), nullable=False),
        sa.Column('activation_week', sa.Integer(), nullable=False),
        sa.Column('hold', sa.String(), nullable=False),
        sa.Column('created_at', sa.BigInteger(), nullable=False),
    )
    op.create_table('league_seasons',
        sa.Column('league_id', sa.String(), primary_key=True, nullable=False),
        sa.Column('provider', sa.String(), nullable=False),
        sa.Column('provider_key', sa.String(), nullable=False),
        sa.Column('series_id', sa.String(), nullable=False),
        sa.Column('season', sa.Integer(), nullable=False),
        sa.Column('capabilities_json', sa.String(), nullable=False),
        sa.Column('evidence_json', sa.String(), nullable=False),
        sa.Column('verified_at', sa.BigInteger(), nullable=False),
        sa.Column('latest_week', sa.Integer(), nullable=False),
        sa.UniqueConstraint('provider', 'provider_key', name='uq_generation_season'),
    )
    op.create_index('ix_league_seasons_series_id', 'league_seasons', ['series_id'], unique=False)
    op.create_table('generation_candidates',
        sa.Column('key', sa.String(), primary_key=True, nullable=False),
        sa.Column('series_id', sa.String(), nullable=False),
        sa.Column('league_id', sa.String(), nullable=False),
        sa.Column('feature', sa.String(), nullable=False),
        sa.Column('subject', sa.String(), nullable=False),
        sa.Column('event', sa.String(), nullable=False),
        sa.Column('payload_json', sa.String(), nullable=False),
        sa.Column('digest', sa.String(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('observed_at', sa.BigInteger(), nullable=False),
        sa.Column('eligible_at', sa.BigInteger(), nullable=False),
        sa.Column('hold', sa.String(), nullable=False),
    )
    op.create_index('ix_generation_candidates_league_id', 'generation_candidates', ['league_id'], unique=False)
    op.create_index('ix_generation_candidates_series_id', 'generation_candidates', ['series_id'], unique=False)
    op.create_index('ix_generation_candidates_subject', 'generation_candidates', ['subject'], unique=False)
    op.create_table('generation_operations',
        sa.Column('id', sa.String(), primary_key=True, nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('league_id', sa.String(), nullable=False),
        sa.Column('series_id', sa.String(), nullable=False),
        sa.Column('feature', sa.String(), nullable=False),
        sa.Column('subject', sa.String(), nullable=False),
        sa.Column('authorization_key', sa.String(), nullable=True),
        sa.Column('active_key', sa.String(), nullable=True),
        sa.Column('idempotency_key', sa.String(), nullable=True),
        sa.Column('request_digest', sa.String(), nullable=False),
        sa.Column('candidate_key', sa.String(), nullable=False),
        sa.Column('payload_json', sa.String(), nullable=False),
        sa.Column('policy_json', sa.String(), nullable=False),
        sa.Column('actor_id', sa.String(), nullable=False),
        sa.Column('actor_kind', sa.String(), nullable=False),
        sa.Column('connection_generation', sa.String(), nullable=False),
        sa.Column('state', sa.String(), nullable=False),
        sa.Column('reason', sa.String(), nullable=False),
        sa.Column('progress_json', sa.String(), nullable=False),
        sa.Column('worker_id', sa.String(), nullable=False),
        sa.Column('generation', sa.Integer(), nullable=False),
        sa.Column('epoch', sa.String(), nullable=False),
        sa.Column('lease_until', sa.BigInteger(), nullable=False),
        sa.Column('calls', sa.Integer(), nullable=False),
        sa.Column('max_calls', sa.Integer(), nullable=False),
        sa.Column('expected_artifact', sa.String(), nullable=False),
        sa.Column('artifact_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.BigInteger(), nullable=False),
        sa.Column('updated_at', sa.BigInteger(), nullable=False),
        sa.UniqueConstraint('active_key'),
        sa.UniqueConstraint('authorization_key'),
        sa.UniqueConstraint('idempotency_key'),
    )
    op.create_index('ix_generation_operations_league_id', 'generation_operations', ['league_id'], unique=False)
    op.create_index('ix_generation_operations_series_id', 'generation_operations', ['series_id'], unique=False)
    op.create_index('ix_generation_operations_state', 'generation_operations', ['state'], unique=False)
    op.create_index('ix_generation_operations_subject', 'generation_operations', ['subject'], unique=False)
    op.create_table('provider_attempts',
        sa.Column('id', sa.String(), primary_key=True, nullable=False),
        sa.Column('operation_id', sa.String(), nullable=False),
        sa.Column('stage', sa.Integer(), nullable=False),
        sa.Column('generation', sa.Integer(), nullable=False),
        sa.Column('request_digest', sa.String(), nullable=False),
        sa.Column('request_json', sa.String(), nullable=False),
        sa.Column('model', sa.String(), nullable=False),
        sa.Column('state', sa.String(), nullable=False),
        sa.Column('usage_state', sa.String(), nullable=False),
        sa.Column('receipt_json', sa.String(), nullable=True),
        sa.Column('usage_json', sa.String(), nullable=False),
        sa.Column('pricing_json', sa.String(), nullable=False),
        sa.Column('cost_microusd', sa.BigInteger(), nullable=True),
        sa.Column('provider_request_id', sa.String(), nullable=False),
        sa.Column('status_code', sa.Integer(), nullable=True),
        sa.Column('error_code', sa.String(), nullable=False),
        sa.Column('created_at', sa.BigInteger(), nullable=False),
        sa.Column('settled_at', sa.BigInteger(), nullable=False),
        sa.UniqueConstraint('operation_id', 'stage', name='uq_generation_stage'),
    )
    op.create_index('ix_provider_attempts_operation_id', 'provider_attempts', ['operation_id'], unique=False)
    op.create_index('ix_provider_attempts_state', 'provider_attempts', ['state'], unique=False)
    op.create_table('content_artifacts',
        sa.Column('id', sa.String(), primary_key=True, nullable=False),
        sa.Column('operation_id', sa.String(), nullable=True),
        sa.Column('series_id', sa.String(), nullable=False),
        sa.Column('league_id', sa.String(), nullable=False),
        sa.Column('feature', sa.String(), nullable=False),
        sa.Column('subject', sa.String(), nullable=False),
        sa.Column('digest', sa.String(), nullable=False),
        sa.Column('payload_json', sa.String(), nullable=False),
        sa.Column('facts_json', sa.String(), nullable=False),
        sa.Column('provenance', sa.String(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.BigInteger(), nullable=False),
        sa.UniqueConstraint('operation_id'),
        sa.UniqueConstraint('subject', 'revision', name='uq_artifact_revision'),
    )
    op.create_index('ix_content_artifacts_league_id', 'content_artifacts', ['league_id'], unique=False)
    op.create_index('ix_content_artifacts_series_id', 'content_artifacts', ['series_id'], unique=False)
    op.create_index('ix_content_artifacts_subject', 'content_artifacts', ['subject'], unique=False)
    op.create_table('artifact_heads',
        sa.Column('subject', sa.String(), primary_key=True, nullable=False),
        sa.Column('artifact_id', sa.String(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('hold', sa.String(), nullable=False),
    )
    op.create_table('generation_outbox',
        sa.Column('id', sa.String(), primary_key=True, nullable=False),
        sa.Column('key', sa.String(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('payload_json', sa.String(), nullable=False),
        sa.Column('delivered', sa.Boolean(), nullable=False),
        sa.Column('error', sa.String(), nullable=False),
        sa.Column('created_at', sa.BigInteger(), nullable=False),
        sa.UniqueConstraint('key'),
    )
    op.create_table('generation_audit',
        sa.Column('id', sa.String(), primary_key=True, nullable=False),
        sa.Column('actor_id', sa.String(), nullable=False),
        sa.Column('action', sa.String(), nullable=False),
        sa.Column('target', sa.String(), nullable=False),
        sa.Column('reason', sa.String(), nullable=False),
        sa.Column('before_json', sa.String(), nullable=False),
        sa.Column('after_json', sa.String(), nullable=False),
        sa.Column('created_at', sa.BigInteger(), nullable=False),
    )
    op.execute("INSERT INTO generation_control (id, epoch, hold, revision, provider_hold, cooldown_until, breakers_json) VALUES ('global', '', 'activation_required', 1, '', 0, '{}')")


def downgrade():
    raise RuntimeError("Generation records contain paid receipts; use a forward recovery migration.")
