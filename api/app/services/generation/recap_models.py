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
    __table_args__ = (UniqueConstraint("episode_id", "revision", "execution_revision", "kind", "chunk", name="uq_recap_stage"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    episode_id: Mapped[str] = mapped_column(String, index=True)
    revision: Mapped[int] = mapped_column(Integer)
    execution_revision: Mapped[int] = mapped_column(Integer, default=1)
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


class RecapPublicationControl(Base):
    __tablename__ = "recap_publication_control"
    id: Mapped[str] = mapped_column(String, primary_key=True, default="global")
    epoch: Mapped[str] = mapped_column(String)
    reconciliation_digest: Mapped[str] = mapped_column(String)
    quarantined: Mapped[bool] = mapped_column(Boolean, default=True)


class RecapShareDecision(Base):
    """Edition tombstones and league future permission use separate scope keys."""
    __tablename__ = "recap_share_decisions"
    scope: Mapped[str] = mapped_column(String, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    opted_out: Mapped[bool] = mapped_column(Boolean, default=False)
    token: Mapped[str | None] = mapped_column(String, nullable=True)
    token_digest: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)


class RecapPublication(Base):
    __tablename__ = "recap_publications"
    __table_args__ = (UniqueConstraint("league_id", "season", "week", name="uq_recap_public_edition"),)
    episode_id: Mapped[str] = mapped_column(String, primary_key=True)
    series_id: Mapped[str] = mapped_column(String, index=True)
    league_id: Mapped[str] = mapped_column(String)
    season: Mapped[int] = mapped_column(Integer)
    week: Mapped[int] = mapped_column(Integer)
    article_id: Mapped[str] = mapped_column(String, default="")
    article_revision: Mapped[int] = mapped_column(Integer)
    article_digest: Mapped[str] = mapped_column(String)
    article_json: Mapped[str] = mapped_column(String)
    facts_digest: Mapped[str] = mapped_column(String)
    media_id: Mapped[str | None] = mapped_column(String, nullable=True)
    media_json: Mapped[str] = mapped_column(String, default="{}")
    script_id: Mapped[str] = mapped_column(String, default="")
    approval_id: Mapped[str] = mapped_column(String, default="")
    policy_digest: Mapped[str] = mapped_column(String, default="")
    share_revision: Mapped[int] = mapped_column(Integer)
    authority_revision: Mapped[int] = mapped_column(Integer, default=1)
    projected_revision: Mapped[int] = mapped_column(Integer, default=0)
    epoch: Mapped[str] = mapped_column(String)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    withdrawn: Mapped[bool] = mapped_column(Boolean, default=False)
    hold: Mapped[str] = mapped_column(String, default="")
    published_at: Mapped[int] = mapped_column(BigInteger, default=0)


class RecapPublicationApproval(Base):
    """API-recorded finished-preview review, bound to all current authorities."""
    __tablename__ = "recap_publication_approvals"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    episode_id: Mapped[str] = mapped_column(String, index=True)
    scope_json: Mapped[str] = mapped_column(String)
    reviewer_id: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String)
    created_at: Mapped[int] = mapped_column(BigInteger, default=stamp)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)
    authorization_kind: Mapped[str] = mapped_column(String, default="manual")
    authorization_id: Mapped[str] = mapped_column(String, default="")


class RecapPublicationSelection(Base):
    """Delivered selections survive later unpublished corrections/withdrawal."""
    __tablename__ = "recap_publication_selections"
    __table_args__ = (UniqueConstraint("episode_id", "authority_revision", name="uq_recap_delivered_selection"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    episode_id: Mapped[str] = mapped_column(String)
    series_id: Mapped[str] = mapped_column(String, index=True)
    script_id: Mapped[str] = mapped_column(String)
    authority_revision: Mapped[int] = mapped_column(Integer)
    published_at: Mapped[int] = mapped_column(BigInteger, default=stamp)


class RecapCalibration(Base):
    """Immutable explicit API administrator calibration, never worker metadata."""
    __tablename__ = "recap_calibrations"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    series_id: Mapped[str] = mapped_column(String, index=True)
    season: Mapped[int] = mapped_column(Integer)
    config_json: Mapped[str] = mapped_column(String)
    metadata_json: Mapped[str] = mapped_column(String)
    rate_json: Mapped[str] = mapped_column(String)
    versions_json: Mapped[str] = mapped_column(String)
    evidence_json: Mapped[str] = mapped_column(String)
    actor_id: Mapped[str] = mapped_column(String)
    created_at: Mapped[int] = mapped_column(BigInteger, default=stamp)


class RecapQualificationReview(Base):
    __tablename__ = "recap_qualification_reviews"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    episode_id: Mapped[str] = mapped_column(String, index=True)
    series_id: Mapped[str] = mapped_column(String, index=True)
    season: Mapped[int] = mapped_column(Integer)
    calibration_id: Mapped[str] = mapped_column(String)
    approval_id: Mapped[str] = mapped_column(String)
    binding_json: Mapped[str] = mapped_column(String)
    evidence_json: Mapped[str] = mapped_column(String)
    actor_id: Mapped[str] = mapped_column(String)
    passed: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[int] = mapped_column(BigInteger, default=stamp)


class RecapStandingAuthorization(Base):
    __tablename__ = "recap_standing_authorizations"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    series_id: Mapped[str] = mapped_column(String, index=True)
    season: Mapped[int] = mapped_column(Integer)
    calibration_id: Mapped[str] = mapped_column(String)
    review_ids_json: Mapped[str] = mapped_column(String)
    actor_id: Mapped[str] = mapped_column(String)
    policy: Mapped[str] = mapped_column(String, default="three-reviewed-episodes-v1")
    created_at: Mapped[int] = mapped_column(BigInteger, default=stamp)


class RecapDependency(Base):
    __tablename__ = "recap_dependencies"
    __table_args__ = (UniqueConstraint("episode_id", "prior_episode_id", "observation_id", name="uq_recap_dependency"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    episode_id: Mapped[str] = mapped_column(String, index=True)
    prior_episode_id: Mapped[str] = mapped_column(String, index=True)
    observation_id: Mapped[str] = mapped_column(String)
    facts_digest: Mapped[str] = mapped_column(String)


class RecapRecovery(Base):
    """Append-only old generation evidence and explicitly bounded recovery decisions."""
    __tablename__ = "recap_recoveries"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    episode_id: Mapped[str] = mapped_column(String, index=True)
    stage_id: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    before_json: Mapped[str] = mapped_column(String)
    actor_id: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String)
    created_at: Mapped[int] = mapped_column(BigInteger, default=stamp)


class RecapAttention(Base):
    __tablename__ = "recap_attention"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    episode_id: Mapped[str] = mapped_column(String, index=True)
    state: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String)
    created_at: Mapped[int] = mapped_column(BigInteger, default=stamp)


class RecapRecoveryRequest(Base):
    """One explicit exact-history lookup; expiration requires fresh admin review."""
    __tablename__ = "recap_recovery_requests"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    attempt_id: Mapped[str] = mapped_column(String, index=True)
    worker_id: Mapped[str] = mapped_column(String)
    actor_id: Mapped[str] = mapped_column(String)
    identity_json: Mapped[str] = mapped_column(String)
    request_digest: Mapped[str] = mapped_column(String)
    epoch: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String, default="pending")
    generation: Mapped[int] = mapped_column(Integer, default=1)
    lease_until: Mapped[int] = mapped_column(BigInteger, default=0)
    error: Mapped[str] = mapped_column(String, default="")
    reason: Mapped[str] = mapped_column(String)
    created_at: Mapped[int] = mapped_column(BigInteger, default=stamp)
