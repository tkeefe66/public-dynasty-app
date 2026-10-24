"""Durable cloud monitoring and help-only email outbox."""
import sqlalchemy as sa
from alembic import op

revision = '0021_recap_monitor'
down_revision = '0020_refresh_backoff'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('recap_monitor_state',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('scope_digest', sa.String(), nullable=False),
        sa.Column('next_check_at', sa.BigInteger(), nullable=False),
        sa.Column('lease_token', sa.String(), nullable=False),
        sa.Column('lease_until', sa.BigInteger(), nullable=False),
        sa.Column('state_json', sa.String(), nullable=False),
        sa.Column('last_started_at', sa.BigInteger(), nullable=False),
        sa.Column('last_finished_at', sa.BigInteger(), nullable=False),
        sa.Column('heartbeat_at', sa.BigInteger(), nullable=False))
    op.create_table('recap_monitor_alerts',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('scope_digest', sa.String(), nullable=False),
        sa.Column('recipient_digest', sa.String(), nullable=False),
        sa.Column('state', sa.String(), nullable=False),
        sa.Column('payload_json', sa.String(), nullable=False),
        sa.Column('first_attempt_at', sa.BigInteger(), nullable=False),
        sa.Column('next_attempt_at', sa.BigInteger(), nullable=False),
        sa.Column('lease_until', sa.BigInteger(), nullable=False),
        sa.Column('provider_id', sa.String(), nullable=False),
        sa.Column('error', sa.String(), nullable=False))


def downgrade():
    op.drop_table('recap_monitor_alerts')
    op.drop_table('recap_monitor_state')
