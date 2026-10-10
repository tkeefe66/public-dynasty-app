"""Durable league recap spending policy, independent of activation."""
from sqlalchemy import BigInteger, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.services.generation.models import stamp


class RecapBudgetPolicy(Base):
    __tablename__ = "recap_budget_policies"
    series_id: Mapped[str] = mapped_column(String, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    caps_json: Mapped[str] = mapped_column(String)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=stamp)
