"""Account-scoped Yahoo OAuth and verified league access.

Revision ID: 0008_yahoo_connections
Revises: 0007_side_bets
"""

import sqlalchemy as sa
from alembic import op

revision = "0008_yahoo_connections"
down_revision = "0007_side_bets"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "yahoo_connections",
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("generation", sa.String(36), nullable=False),
        sa.Column("sealed_tokens", sa.String(), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
    )
    op.create_table(
        "yahoo_oauth_states",
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("state_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("sealed_verifier", sa.String(), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=False),
        sa.Column("consumed", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "yahoo_league_grants",
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("league_id", sa.String(), primary_key=True),
        sa.Column("generation", sa.String(36), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=False),
    )


def downgrade():
    op.drop_table("yahoo_league_grants")
    op.drop_table("yahoo_oauth_states")
    op.drop_table("yahoo_connections")
