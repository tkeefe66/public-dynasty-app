"""rename user login tracking to active-days engagement

Revision ID: 0005_active_days
Revises: 0004_user_login_tracking
Create Date: 2026-06-29

The 0004 columns shipped with no meaningful data (forward-only, and every
session was still long-lived), so a straight rename is safe — we switch the
metric from "OAuth sign-ins" to "distinct active days".
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0005_active_days"
down_revision: Union[str, None] = "0004_user_login_tracking"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.alter_column("login_count", new_column_name="active_days")
        batch.alter_column("last_login_at", new_column_name="last_active_at")


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.alter_column("active_days", new_column_name="login_count")
        batch.alter_column("last_active_at", new_column_name="last_login_at")
