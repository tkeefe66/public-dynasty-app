"""Authoritative publication, scoped review, tombstones and delivered history."""
from alembic import op
import sqlalchemy as sa

revision = "0017_recap_publication"
down_revision = "0016_recap_speech_reviews"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('recap_publication_control',
        sa.Column('id', sa.String(), primary_key=True, nullable=False),
        sa.Column('epoch', sa.String(), nullable=False),
        sa.Column('reconciliation_digest', sa.String(), nullable=False),
        sa.Column('quarantined', sa.Boolean(), nullable=False))
    op.create_table('recap_share_decisions',
        sa.Column('scope', sa.String(), primary_key=True, nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('allowed', sa.Boolean(), nullable=False),
        sa.Column('opted_out', sa.Boolean(), nullable=False),
        sa.Column('token', sa.String(), nullable=True),
        sa.Column('token_digest', sa.String(), nullable=True),
        sa.UniqueConstraint('token_digest'))
    op.create_table('recap_publications',
        sa.Column('episode_id', sa.String(), primary_key=True, nullable=False),
        sa.Column('series_id', sa.String(), nullable=False),
        sa.Column('league_id', sa.String(), nullable=False),
        sa.Column('season', sa.Integer(), nullable=False),
        sa.Column('week', sa.Integer(), nullable=False),
        sa.Column('article_id', sa.String(), nullable=False),
        sa.Column('article_revision', sa.Integer(), nullable=False),
        sa.Column('article_digest', sa.String(), nullable=False),
        sa.Column('article_json', sa.String(), nullable=False),
        sa.Column('facts_digest', sa.String(), nullable=False),
        sa.Column('media_id', sa.String(), nullable=True),
        sa.Column('media_json', sa.String(), nullable=False),
        sa.Column('script_id', sa.String(), nullable=False),
        sa.Column('approval_id', sa.String(), nullable=False),
        sa.Column('policy_digest', sa.String(), nullable=False),
        sa.Column('share_revision', sa.Integer(), nullable=False),
        sa.Column('authority_revision', sa.Integer(), nullable=False),
        sa.Column('projected_revision', sa.Integer(), nullable=False),
        sa.Column('epoch', sa.String(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('withdrawn', sa.Boolean(), nullable=False),
        sa.Column('hold', sa.String(), nullable=False),
        sa.Column('published_at', sa.BigInteger(), nullable=False),
        sa.UniqueConstraint('league_id', 'season', 'week', name='uq_recap_public_edition'))
    op.create_index('ix_recap_publications_series_id', 'recap_publications', ['series_id'])
    op.create_table('recap_publication_approvals',
        sa.Column('id', sa.String(), primary_key=True, nullable=False),
        sa.Column('episode_id', sa.String(), nullable=False),
        sa.Column('scope_json', sa.String(), nullable=False),
        sa.Column('reviewer_id', sa.String(), nullable=False),
        sa.Column('reason', sa.String(), nullable=False),
        sa.Column('created_at', sa.BigInteger(), nullable=False),
        sa.Column('consumed', sa.Boolean(), nullable=False))
    op.create_index('ix_recap_publication_approvals_episode_id', 'recap_publication_approvals', ['episode_id'])
    op.create_table('recap_publication_selections',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('episode_id', sa.String(), nullable=False),
        sa.Column('series_id', sa.String(), nullable=False),
        sa.Column('script_id', sa.String(), nullable=False),
        sa.Column('authority_revision', sa.Integer(), nullable=False),
        sa.Column('published_at', sa.BigInteger(), nullable=False),
        sa.UniqueConstraint('episode_id', 'authority_revision', name='uq_recap_delivered_selection'))
    op.create_index('ix_recap_publication_selections_series_id', 'recap_publication_selections', ['series_id'])


def downgrade():
    raise RuntimeError("Publication and revocation evidence requires explicit archival review")
