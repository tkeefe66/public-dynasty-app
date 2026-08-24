"""initial identity tables: users, league_memberships

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("google_sub", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("avatar_url", sa.String(), nullable=True),
        sa.Column("sleeper_user_id", sa.String(), nullable=True),
        sa.Column("sleeper_username", sa.String(), nullable=True),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_google_sub", "users", ["google_sub"], unique=True)
    op.create_index("ix_users_email", "users", ["email"], unique=False)

    op.create_table(
        "league_memberships",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("league_id", sa.String(), nullable=False),
        sa.Column("sleeper_roster_id", sa.Integer(), nullable=True),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "league_id", name="uq_user_league"),
    )
    op.create_index(
        "ix_league_memberships_user_id", "league_memberships", ["user_id"], unique=False
    )
    op.create_index(
        "ix_league_memberships_league_id",
        "league_memberships",
        ["league_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_league_memberships_league_id", table_name="league_memberships")
    op.drop_index("ix_league_memberships_user_id", table_name="league_memberships")
    op.drop_table("league_memberships")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_google_sub", table_name="users")
    op.drop_table("users")
