"""Durable generation records; JSON text keeps logical backups lossless."""
from __future__ import annotations

import time
import uuid

from sqlalchemy import BigInteger, Boolean, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def uid() -> str:
    return str(uuid.uuid4())


def stamp() -> int:
    return int(time.time())


class GenerationControl(Base):
    __tablename__ = "generation_control"
    id: Mapped[str] = mapped_column(String, primary_key=True, default="global")
    epoch: Mapped[str] = mapped_column(String, default="")
    hold: Mapped[str] = mapped_column(String, default="activation_required")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    provider_hold: Mapped[str] = mapped_column(String, default="")
    cooldown_until: Mapped[int] = mapped_column(BigInteger, default=0)
    breakers_json: Mapped[str] = mapped_column(String, default="{}")


class GenerationPolicy(Base):
    __tablename__ = "generation_policies"
    scope: Mapped[str] = mapped_column(String, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    value_json: Mapped[str] = mapped_column(String, default="{}")


class LeagueSeries(Base):
    __tablename__ = "league_series"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String, default="")
    lifecycle: Mapped[str] = mapped_column(String, default="pending_verification")
    profile: Mapped[str] = mapped_column(String, default="")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    activated_at: Mapped[int] = mapped_column(BigInteger, default=0)
    activation_week: Mapped[int] = mapped_column(Integer, default=0)
    hold: Mapped[str] = mapped_column(String, default="activation_required")
    created_at: Mapped[int] = mapped_column(BigInteger, default=stamp)


class LeagueSeason(Base):
    __tablename__ = "league_seasons"
    __table_args__ = (UniqueConstraint("provider", "provider_key", name="uq_generation_season"),)
    league_id: Mapped[str] = mapped_column(String, primary_key=True)
    provider: Mapped[str] = mapped_column(String)
    provider_key: Mapped[str] = mapped_column(String)
    series_id: Mapped[str] = mapped_column(String, index=True)
    season: Mapped[int] = mapped_column(Integer)
    capabilities_json: Mapped[str] = mapped_column(String, default="{}")
    evidence_json: Mapped[str] = mapped_column(String, default="{}")
    verified_at: Mapped[int] = mapped_column(BigInteger, default=0)
    latest_week: Mapped[int] = mapped_column(Integer, default=0)


class GenerationCandidate(Base):
    __tablename__ = "generation_candidates"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    series_id: Mapped[str] = mapped_column(String, index=True)
    league_id: Mapped[str] = mapped_column(String, index=True)
    feature: Mapped[str] = mapped_column(String)
    subject: Mapped[str] = mapped_column(String, index=True)
    event: Mapped[str] = mapped_column(String)
    payload_json: Mapped[str] = mapped_column(String)
    digest: Mapped[str] = mapped_column(String)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    observed_at: Mapped[int] = mapped_column(BigInteger, default=stamp)
    eligible_at: Mapped[int] = mapped_column(BigInteger, default=0)
    hold: Mapped[str] = mapped_column(String, default="")


class GenerationOperation(Base):
    """One bounded authorization and its recoverable execution state."""
    __tablename__ = "generation_operations"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String)
    league_id: Mapped[str] = mapped_column(String, index=True)
    series_id: Mapped[str] = mapped_column(String, default="", index=True)
    feature: Mapped[str] = mapped_column(String, default="")
    subject: Mapped[str] = mapped_column(String, default="", index=True)
    authorization_key: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    active_key: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    idempotency_key: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    request_digest: Mapped[str] = mapped_column(String, default="")
    candidate_key: Mapped[str] = mapped_column(String, default="")
    payload_json: Mapped[str] = mapped_column(String, default="{}")
    policy_json: Mapped[str] = mapped_column(String, default="{}")
    actor_id: Mapped[str] = mapped_column(String, default="")
    actor_kind: Mapped[str] = mapped_column(String, default="member")
    connection_generation: Mapped[str] = mapped_column(String, default="")
    state: Mapped[str] = mapped_column(String, default="queued", index=True)
    reason: Mapped[str] = mapped_column(String, default="")
    progress_json: Mapped[str] = mapped_column(String, default="{}")
    worker_id: Mapped[str] = mapped_column(String, default="")
    generation: Mapped[int] = mapped_column(Integer, default=0)
    epoch: Mapped[str] = mapped_column(String, default="")
    lease_until: Mapped[int] = mapped_column(BigInteger, default=0)
    calls: Mapped[int] = mapped_column(Integer, default=0)
    max_calls: Mapped[int] = mapped_column(Integer, default=0)
    expected_artifact: Mapped[str] = mapped_column(String, default="")
    artifact_id: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[int] = mapped_column(BigInteger, default=stamp)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=stamp)


class ProviderAttempt(Base):
    """Physical request plus immutable receipt = one durable stage checkpoint."""
    __tablename__ = "provider_attempts"
    __table_args__ = (UniqueConstraint("operation_id", "stage", name="uq_generation_stage"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    operation_id: Mapped[str] = mapped_column(String, index=True)
    stage: Mapped[int] = mapped_column(Integer)
    generation: Mapped[int] = mapped_column(Integer)
    request_digest: Mapped[str] = mapped_column(String)
    request_json: Mapped[str] = mapped_column(String)
    model: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String, default="dispatching", index=True)
    usage_state: Mapped[str] = mapped_column(String, default="unknown")
    receipt_json: Mapped[str | None] = mapped_column(String, nullable=True)
    usage_json: Mapped[str] = mapped_column(String, default="{}")
    pricing_json: Mapped[str] = mapped_column(String, default="{}")
    cost_microusd: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    provider_request_id: Mapped[str] = mapped_column(String, default="")
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[int] = mapped_column(BigInteger, default=stamp)
    settled_at: Mapped[int] = mapped_column(BigInteger, default=0)


class ContentArtifact(Base):
    __tablename__ = "content_artifacts"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    operation_id: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    series_id: Mapped[str] = mapped_column(String, index=True)
    league_id: Mapped[str] = mapped_column(String, index=True)
    feature: Mapped[str] = mapped_column(String)
    subject: Mapped[str] = mapped_column(String, index=True)
    digest: Mapped[str] = mapped_column(String)
    payload_json: Mapped[str] = mapped_column(String)
    facts_json: Mapped[str] = mapped_column(String, default="{}")
    provenance: Mapped[str] = mapped_column(String)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[int] = mapped_column(BigInteger, default=stamp)
    __table_args__ = (UniqueConstraint("subject", "revision", name="uq_artifact_revision"),)


class ArtifactHead(Base):
    __tablename__ = "artifact_heads"
    subject: Mapped[str] = mapped_column(String, primary_key=True)
    artifact_id: Mapped[str] = mapped_column(String)
    revision: Mapped[int] = mapped_column(Integer)
    hold: Mapped[str] = mapped_column(String, default="")


class GenerationOutbox(Base):
    __tablename__ = "generation_outbox"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    key: Mapped[str] = mapped_column(String, unique=True)
    kind: Mapped[str] = mapped_column(String)
    payload_json: Mapped[str] = mapped_column(String)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[int] = mapped_column(BigInteger, default=stamp)


class GenerationAudit(Base):
    __tablename__ = "generation_audit"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    actor_id: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    target: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String)
    before_json: Mapped[str] = mapped_column(String, default="{}")
    after_json: Mapped[str] = mapped_column(String, default="{}")
    created_at: Mapped[int] = mapped_column(BigInteger, default=stamp)
