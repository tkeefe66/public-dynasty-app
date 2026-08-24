"""add league_name to league_memberships

Revision ID: 0003_membership_league_name
Revises: 0002_app_settings
Create Date: 2026-06-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_membership_league_name"
down_revision: Union[str, None] = "0002_app_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "league_memberships",
        sa.Column("league_name", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("league_memberships", "league_name")
