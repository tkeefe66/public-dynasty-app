from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    google_sub: Mapped[str] = mapped_column(String, unique=True, index=True)
    email: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String, nullable=True)
    # Soft Sleeper link (personalization only — never used for authz). Phase 3.
    sleeper_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    sleeper_username: Mapped[str | None] = mapped_column(String, nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Engagement: count of distinct UTC calendar days the user was active (made
    # any authenticated request). Stamped in get_current_user, gated to one bump
    # per day via last_active_at. Forward-only: pre-existing users start at 0.
    active_days: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    last_active_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, server_default=func.now()
    )

    memberships: Mapped[list[LeagueMembership]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class LeagueMembership(Base):
    __tablename__ = "league_memberships"
    __table_args__ = (UniqueConstraint("user_id", "league_id", name="uq_user_league"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # Opaque Sleeper league id, NOT a FK — the engine owns league state on the
    # volume. This is the seam between the DB world and the file-cache world.
    league_id: Mapped[str] = mapped_column(String, index=True)
    # Display name captured at import time so the UI can show the league name
    # immediately, before the (separate) analysis cache is warm.
    league_name: Mapped[str | None] = mapped_column(String, nullable=True)
    sleeper_roster_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="memberships")


class AppSetting(Base):
    """Owner-editable app settings (key/value), e.g. the LLM monthly budget.
    Overrides the env default when present, so the owner can change it from the
    admin UI without a redeploy."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, server_default=func.now()
    )


class PageEvent(Base):
    """One pageview (route change) by an authenticated user. First-party product
    telemetry: who's active, which sections/leagues get used. `route` is the
    normalized template (low cardinality, for aggregation); `path` is the raw
    pathname (for the per-user drill-down). Query strings are never stored."""

    __tablename__ = "page_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    league_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    route: Mapped[str] = mapped_column(String, index=True)
    path: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now(), index=True
    )


class SideBet(Base):
    """One manually recorded side bet between two league owners (1-vs-1,
    winner takes the amount). Manual must-survive-forever money records live
    in Postgres, never the rebuildable chain cache. Sides are Sleeper owner
    user_ids (the app-wide owner key); league_id is the opaque Sleeper league
    id, not a FK. Void replaces delete — rows are never destroyed. Audit FKs
    are SET NULL so the ledger survives user-account deletion."""

    __tablename__ = "side_bets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    league_id: Mapped[str] = mapped_column(String, index=True)
    season: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String)
    # Integer cents — no float money.
    amount_cents: Mapped[int] = mapped_column(Integer)
    side_a_owner_id: Mapped[str] = mapped_column(String, index=True)
    side_b_owner_id: Mapped[str] = mapped_column(String, index=True)
    # open | settled | push | void — invariants enforced in the service layer.
    status: Mapped[str] = mapped_column(String, default="open", nullable=False)
    winner_owner_id: Mapped[str | None] = mapped_column(String, nullable=True)
    made_at: Mapped[date] = mapped_column(Date)
    settled_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    settled_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, server_default=func.now()
    )
