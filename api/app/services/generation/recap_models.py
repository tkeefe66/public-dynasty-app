"""Durable league recap spending policy, independent of activation."""
from sqlalchemy import BigInteger, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.services.generation.models import stamp, uid


class RecapBudgetPolicy(Base):
    __tablename__ = "recap_budget_policies"
    series_id: Mapped[str] = mapped_column(String, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    caps_json: Mapped[str] = mapped_column(String)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=stamp)


class RecapBudgetPlan(Base):
    __tablename__ = "recap_budget_plans"
    __table_args__ = (UniqueConstraint("episode_id", "plan_key", name="uq_recap_budget_plan"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    episode_id: Mapped[str] = mapped_column(String, index=True)
    series_id: Mapped[str] = mapped_column(String, index=True)
    plan_key: Mapped[str] = mapped_column(String)
    digest: Mapped[str] = mapped_column(String)
    created_at: Mapped[int] = mapped_column(BigInteger, default=stamp)


class RecapBudgetAllocation(Base):
    __tablename__ = "recap_budget_allocations"
    __table_args__ = (UniqueConstraint("plan_id", "key", name="uq_recap_budget_allocation"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    plan_id: Mapped[str] = mapped_column(String, index=True)
    key: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String)
    operation_id: Mapped[str] = mapped_column(String, index=True)
    attempt_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    month_key: Mapped[str] = mapped_column(String)
    max_microusd: Mapped[int] = mapped_column(BigInteger)
    outstanding_microusd: Mapped[int] = mapped_column(BigInteger)
    actual_microusd: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    rate_json: Mapped[str] = mapped_column(String)
    evidence_json: Mapped[str] = mapped_column(String, default="{}")
    state: Mapped[str] = mapped_column(String, default="reserved")
    created_at: Mapped[int] = mapped_column(BigInteger, default=stamp)
