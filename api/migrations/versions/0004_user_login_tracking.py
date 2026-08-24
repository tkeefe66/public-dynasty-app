"""add login tracking to users

Revision ID: 0004_user_login_tracking
Revises: 0003_membership_league_name
Create Date: 2026-06-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_user_login_tracking"
down_revision: Union[str, None] = "0003_membership_league_name"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "login_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "users",
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "login_count")
