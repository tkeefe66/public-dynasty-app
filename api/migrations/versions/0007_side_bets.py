"""add side_bets ledger table

Revision ID: 0007_side_bets
Revises: 0006_page_events
Create Date: 2026-07-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_side_bets"
down_revision: Union[str, None] = "0006_page_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "side_bets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("league_id", sa.String(), nullable=False),
        sa.Column("season", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("side_a_owner_id", sa.String(), nullable=False),
        sa.Column("side_b_owner_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("winner_owner_id", sa.String(), nullable=True),
        sa.Column("made_at", sa.Date(), nullable=False),
        sa.Column("settled_at", sa.Date(), nullable=True),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("settled_by_user_id", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["settled_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_side_bets_league_id", "side_bets", ["league_id"])
    op.create_index("ix_side_bets_side_a_owner_id", "side_bets", ["side_a_owner_id"])
    op.create_index("ix_side_bets_side_b_owner_id", "side_bets", ["side_b_owner_id"])
    op.create_index(
        "ix_side_bets_created_by_user_id", "side_bets", ["created_by_user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_side_bets_created_by_user_id", table_name="side_bets")
    op.drop_index("ix_side_bets_side_b_owner_id", table_name="side_bets")
    op.drop_index("ix_side_bets_side_a_owner_id", table_name="side_bets")
    op.drop_index("ix_side_bets_league_id", table_name="side_bets")
    op.drop_table("side_bets")
