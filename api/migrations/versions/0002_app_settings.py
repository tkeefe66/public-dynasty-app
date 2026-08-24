"""app_settings key/value table (owner-editable budget, etc.)

Revision ID: 0002_app_settings
Revises: 0001_initial
Create Date: 2026-06-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_app_settings"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
