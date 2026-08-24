"""add page_events telemetry table

Revision ID: 0006_page_events
Revises: 0005_active_days
Create Date: 2026-06-28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_page_events"
down_revision: Union[str, None] = "0005_active_days"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "page_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("league_id", sa.String(), nullable=True),
        sa.Column("route", sa.String(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_page_events_user_id", "page_events", ["user_id"])
    op.create_index("ix_page_events_league_id", "page_events", ["league_id"])
    op.create_index("ix_page_events_route", "page_events", ["route"])
    op.create_index("ix_page_events_created_at", "page_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_page_events_created_at", table_name="page_events")
    op.drop_index("ix_page_events_route", table_name="page_events")
    op.drop_index("ix_page_events_league_id", table_name="page_events")
    op.drop_index("ix_page_events_user_id", table_name="page_events")
    op.drop_table("page_events")
