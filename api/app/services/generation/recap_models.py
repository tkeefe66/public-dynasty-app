"""Durable league recap spending policy, independent of activation."""
from sqlalchemy import BigInteger, Boolean, Integer, String, UniqueConstraint
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


class RecapEpisode(Base):
    __tablename__ = "recap_episodes"
    __table_args__ = (UniqueConstraint("series_id", "season", "period_id", name="uq_recap_episode_period"),)
    episode_id: Mapped[str] = mapped_column(String, primary_key=True)
    series_id: Mapped[str] = mapped_column(String, index=True)
    season: Mapped[int] = mapped_column(Integer)
    period_id: Mapped[str] = mapped_column(String)
    league_id: Mapped[str] = mapped_column(String, index=True)
    week: Mapped[int] = mapped_column(Integer)
    round: Mapped[int | None] = mapped_column(Integer, nullable=True)
    nfl_weeks_json: Mapped[str] = mapped_column(String)
    lifecycle: Mapped[str] = mapped_column(String, default="observing")
    hold: Mapped[str] = mapped_column(String, default="")
    admitted_at: Mapped[int] = mapped_column(BigInteger, default=0)
    eligible_at: Mapped[int] = mapped_column(BigInteger, default=0)
    observed_at: Mapped[int] = mapped_column(BigInteger, default=0)
    stable_since: Mapped[int] = mapped_column(BigInteger, default=0)
    next_observation_at: Mapped[int] = mapped_column(BigInteger, default=0, index=True)
    facts_digest: Mapped[str] = mapped_column(String, default="")
    source_digest: Mapped[str] = mapped_column(String, default="")
    article_digest: Mapped[str] = mapped_column(String, default="")
    latest_observation_id: Mapped[str] = mapped_column(String, default="")


class RecapObservation(Base):
    __tablename__ = "recap_observations"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    episode_id: Mapped[str] = mapped_column(String, index=True)
    observed_at: Mapped[int] = mapped_column(BigInteger)
    snapshot_json: Mapped[str] = mapped_column(String)
    snapshot_digest: Mapped[str] = mapped_column(String)
    facts_digest: Mapped[str] = mapped_column(String)
    provider_timestamps_json: Mapped[str] = mapped_column(String, default="{}")
    source_pointers_json: Mapped[str] = mapped_column(String, default="{}")
    decision: Mapped[str] = mapped_column(String)


class RecapScheduleInventory(Base):
    __tablename__ = "recap_schedule_inventories"
    version: Mapped[str] = mapped_column(String, primary_key=True)
    season: Mapped[int] = mapped_column(Integer, index=True)
    revision: Mapped[str] = mapped_column(String)
    qualified_at: Mapped[int] = mapped_column(BigInteger)
    inventory_json: Mapped[str] = mapped_column(String)


class ProviderAccountControl(Base):
    __tablename__ = "provider_account_controls"
    provider: Mapped[str] = mapped_column(String, primary_key=True)
    account_key: Mapped[str] = mapped_column(String, primary_key=True)
    hold: Mapped[str] = mapped_column(String, default="")
    cooldown_until: Mapped[int] = mapped_column(BigInteger, default=0)
    max_concurrency: Mapped[int] = mapped_column(Integer, default=1)
    revision: Mapped[int] = mapped_column(Integer, default=1)


class RecapStage(Base):
    """API-created subordinate checkpoint, never an independent scheduler job."""
    __tablename__ = "recap_stages"
    evidence_json: Mapped[str] = mapped_column(String, default="{}")
    __table_args__ = (UniqueConstraint("episode_id", "revision", "kind", "chunk", name="uq_recap_stage"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    episode_id: Mapped[str] = mapped_column(String, index=True)
    revision: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String)
    chunk: Mapped[int] = mapped_column(Integer, default=0)
    script_id: Mapped[str] = mapped_column(String)
    operation_id: Mapped[str] = mapped_column(String, index=True)
    predecessor_id: Mapped[str] = mapped_column(String, default="")
    input_json: Mapped[str] = mapped_column(String)
    input_digest: Mapped[str] = mapped_column(String)
    policy_digest: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String, default="queued", index=True)
    reason: Mapped[str] = mapped_column(String, default="")
    worker_id: Mapped[str] = mapped_column(String, default="")
    generation: Mapped[int] = mapped_column(Integer, default=0)
    epoch: Mapped[str] = mapped_column(String, default="")
    lease_until: Mapped[int] = mapped_column(BigInteger, default=0)
    next_attempt_at: Mapped[int] = mapped_column(BigInteger, default=0)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    result_json: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[int] = mapped_column(BigInteger, default=stamp)


class RecapProviderAttempt(Base):
    """One physical send authority; UUID identity preserves numeric prose ledger."""
    __tablename__ = "recap_provider_attempts"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    stage_id: Mapped[str] = mapped_column(String, unique=True)
    episode_id: Mapped[str] = mapped_column(String, index=True)
    series_id: Mapped[str] = mapped_column(String, index=True)
    operation_id: Mapped[str] = mapped_column(String, index=True)
    provider: Mapped[str] = mapped_column(String)
    account_key: Mapped[str] = mapped_column(String)
    worker_id: Mapped[str] = mapped_column(String)
    generation: Mapped[int] = mapped_column(Integer)
    epoch: Mapped[str] = mapped_column(String)
    request_digest: Mapped[str] = mapped_column(String)
    request_json: Mapped[str] = mapped_column(String)
    pricing_json: Mapped[str] = mapped_column(String)
    authority_digest: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String, default="dispatching", index=True)
    error_code: Mapped[str] = mapped_column(String, default="")
    receipt_json: Mapped[str | None] = mapped_column(String, nullable=True)
    identity_json: Mapped[str] = mapped_column(String, default="[]")
    recovery_receipt_json: Mapped[str | None] = mapped_column(String, nullable=True)
    recovery_settled_at: Mapped[int] = mapped_column(BigInteger, default=0)
    cost_microusd: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, default=stamp)
    settled_at: Mapped[int] = mapped_column(BigInteger, default=0)


class RecapAsset(Base):
    __tablename__ = "recap_assets"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    stage_id: Mapped[str] = mapped_column(String, index=True)
    generation: Mapped[int] = mapped_column(Integer)
    digest: Mapped[str] = mapped_column(String)
    size: Mapped[int] = mapped_column(BigInteger)
    media_type: Mapped[str] = mapped_column(String)
    storage_key: Mapped[str] = mapped_column(String, unique=True)
    created_at: Mapped[int] = mapped_column(BigInteger, default=stamp)


class RecapSpeechReview(Base):
    """Immutable human-reviewed spelling of one source entity; never LLM output."""
    __tablename__ = "recap_speech_reviews"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    series_id: Mapped[str] = mapped_column(String, index=True)
    season: Mapped[int] = mapped_column(Integer)
    entity_kind: Mapped[str] = mapped_column(String)
    entity_id: Mapped[str] = mapped_column(String)
    canonical_name: Mapped[str] = mapped_column(String)
    canonical_token: Mapped[str] = mapped_column(String)
    reusable: Mapped[bool] = mapped_column(Boolean, default=False)
    aliases_json: Mapped[str] = mapped_column(String)
    script_id: Mapped[str] = mapped_column(String)
    script_digest: Mapped[str] = mapped_column(String)
    script_revision: Mapped[int] = mapped_column(Integer)
    reviewer_id: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String)
    created_at: Mapped[int] = mapped_column(BigInteger, default=stamp)
