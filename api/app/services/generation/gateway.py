"""Persist admission before HTTP and receipts before parsing; never resend unknown work."""
from __future__ import annotations

import asyncio
import json
import logging

from sqlalchemy import func, select

from app.services.generation.accounting import price_usage, pricing, validate_request_shape
from app.services.generation.recap_budget import admit_provider_allocation, settle_attempt
from app.services.generation.commands import UNRESOLVED, require_actor, require_owner
from app.services.generation.models import (
    GenerationOperation,
    GenerationOutbox,
    LeagueSeason,
    ProviderAttempt,
    stamp,
)
from app.services.generation.policy import paid_capabilities, supports_feature
from app.services.generation.store import (
    Held,
    audit,
    digest,
    dump,
    lock_control,
    resolve_policy,
)
from app.services.generation.transport import Receipt

log = logging.getLogger(__name__)


class Gateway:
    def __init__(self, maker, transport, *, epoch: str):
        self.maker = maker
        self.transport = transport
        self.epoch = epoch

    async def invoke(self, operation_id: str, generation: int, stage: int, request: dict) -> dict:
        request_hash = digest(request)
        async with self.maker.begin() as db:
            control = await lock_control(db)
            job = await require_owner(db, operation_id, generation)
            previous = await db.scalar(select(ProviderAttempt).where(
                ProviderAttempt.operation_id == job.id, ProviderAttempt.stage == stage))
            if previous:
                if previous.request_digest != request_hash:
                    raise Held("checkpoint_request_changed")
                if previous.state != "received" or previous.usage_state != "known":
                    raise Held(previous.error_code or "provider_outcome_unknown")
                return self._parse_receipt(previous.receipt_json)
            config = await resolve_policy(db, job.series_id)
            if config["blocked_by"]:
                raise Held(config["blocked_by"][0])
            if not self.epoch or control.epoch != self.epoch or job.epoch != self.epoch:
                raise Held("restore_quarantine")
            if control.cooldown_until > stamp():
                raise Held("provider_cooldown")
            from app.config import get_settings
            if get_settings().generation_emergency_pause:
                raise Held("emergency_pause")
            await require_actor(db, job)
            if job.feature == "recap_video":
                from app.services.recap_video.contracts import require_script_inputs
                await require_script_inputs(db, job.series_id, job.league_id, json.loads(job.payload_json))
            if job.feature == "analyst":
                from app.services.recap_video.readiness import require_readiness
                await require_readiness(db, job.series_id, json.loads(job.payload_json), league_id=job.league_id)
            season = await db.get(LeagueSeason, job.league_id)
            if not season or not season.verified_at or not paid_capabilities(json.loads(season.capabilities_json)):
                raise Held("capability_unknown")
            if not supports_feature(json.loads(season.capabilities_json), season.provider, job.feature):
                raise Held("feature_unsupported")
            if job.actor_kind == "scheduler":
                from app.services.generation.planner import automatic_eligibility
                reason = await automatic_eligibility(db, season, job.feature, json.loads(job.payload_json), stamp())
                if reason:
                    raise Held(reason)
            if job.feature not in config["policy"]["features"]:
                raise Held("feature_unregistered")
            feature = config["policy"]["features"][job.feature]
            saved = json.loads(job.policy_json)["policy"]["features"][job.feature]
            if feature["paused"] or feature["mode"] == "disabled":
                raise Held("feature_paused")
            if job.actor_kind == "scheduler" and feature["mode"] != "automatic":
                raise Held("manual_only")
            if json.loads(control.breakers_json).get(job.feature, {}).get("open"):
                raise Held("feature_breaker_open")
            if stage != job.calls + 1 or job.calls >= min(job.max_calls, feature["max_calls"]):
                raise Held("attempt_allowance_exhausted")
            allowed_model = saved["review_model"] if job.feature in ("analyst", "recap_video") and stage > 1 else saved["model"]
            current_model = feature["review_model"] if job.feature in ("analyst", "recap_video") and stage > 1 else feature["model"]
            if request.get("model") != allowed_model or allowed_model != current_model:
                raise Held("request_model_changed")
            if (type(request.get("max_tokens")) is not int or request["max_tokens"] < 1
                    or request["max_tokens"] > min(feature["max_tokens"], saved["max_tokens"])
                    or len(dump(request)) > min(feature["max_prompt_chars"], saved["max_prompt_chars"])):
                raise Held("request_limit_exceeded")
            validate_request_shape(request)
            snapshot = pricing(allowed_model)
            if hasattr(self.transport, "check_ready"):
                self.transport.check_ready()
            pending = await db.scalar(select(func.count()).select_from(ProviderAttempt).where(
                ProviderAttempt.state.in_(UNRESOLVED)))
            if pending >= config["policy"]["max_concurrency"]:
                raise Held("concurrency_busy")
            series_pending = await db.scalar(select(func.count()).select_from(ProviderAttempt).join(
                GenerationOperation, GenerationOperation.id == ProviderAttempt.operation_id).where(
                    GenerationOperation.series_id == job.series_id,
                    ProviderAttempt.state.in_(UNRESOLVED)))
            if series_pending:
                raise Held("series_concurrency_busy")
            allocation = await admit_provider_allocation(db, job, stage, request, saved, feature, stamp())
            # Settle from the admitted immutable rates, including later stages.
            snapshot = json.loads(allocation.rate_json)
            attempt = ProviderAttempt(operation_id=job.id, stage=stage, generation=generation,
                request_digest=request_hash, request_json=dump(request), model=allowed_model,
                pricing_json=dump(snapshot))
            db.add(attempt)
            job.calls += 1
            await db.flush()
            attempt_id = attempt.id
            allocation.attempt_id = attempt.id
        log.info("provider admitted operation=%s attempt=%s stage=%s", operation_id, attempt_id, stage)
        # No cancellation, restart or exception path repeats this submission.
        try:
            receipt = await self.transport.send(request)
        except (Exception, asyncio.CancelledError) as exc:
            try:
                async with self.maker.begin() as db:
                    await lock_control(db)
                    row = await db.get(ProviderAttempt, attempt_id)
                    row.state = "unknown"
                    row.error_code = "provider_outcome_unknown"
                    await settle_attempt(db, row, {"outcome": "unknown", "attempt_id": attempt_id})
            except Exception:
                log.exception("provider attempt remains unresolved after persistence failure attempt=%s", attempt_id)
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise Held("provider_outcome_unknown") from None
        try:
            await self.record_receipt(attempt_id, receipt)
        except Held:
            raise
        except Exception as exc:
            log.exception("receipt persistence failed; attempt cannot be resent attempt=%s", attempt_id)
            raise Held("receipt_persistence_failed") from exc
        async with self.maker.begin() as db:
            await lock_control(db)
            await require_owner(db, operation_id, generation)
            row = await db.get(ProviderAttempt, attempt_id)
            if row.error_code:
                raise Held(row.error_code)
            return self._parse_receipt(row.receipt_json)

    @staticmethod
    def _parse_receipt(raw: str) -> dict:
        try:
            return json.loads(json.loads(raw)["body"])
        except (TypeError, ValueError, KeyError):
            raise Held("response_invalid") from None

    async def record_receipt(self, attempt_id: str, receipt: Receipt):
        """A late response settles accounting regardless of worker ownership."""
        # Save raw body first, in a separate durable transaction from decoding.
        async with self.maker.begin() as db:
            await lock_control(db)
            row = await db.get(ProviderAttempt, attempt_id)
            raw = dump({"status": receipt.status, "body": receipt.body, "headers": receipt.headers})
            if row.receipt_json:
                if row.receipt_json != raw:
                    raise Held("receipt_conflict")
            else:
                row.receipt_json = raw
                row.provider_request_id = receipt.headers.get("request-id", "")
                row.status_code = receipt.status
        async with self.maker.begin() as db:
            control = await lock_control(db)
            row = await db.get(ProviderAttempt, attempt_id)
            if row.settled_at:
                return
            before = {"state": row.state, "error_code": row.error_code, "usage_state": row.usage_state}
            try:
                body = json.loads(receipt.body)
                usage_state, usage, amount = price_usage(body, json.loads(row.pricing_json))
            except (ValueError, TypeError, AttributeError):
                usage_state, usage, amount = "unknown", {}, None
            row.state = "received"
            row.usage_state = usage_state
            row.usage_json = dump(usage)
            row.cost_microusd = amount
            row.settled_at = stamp()
            row.error_code = ""
            if receipt.status >= 400:
                row.error_code = "provider_rejected" if receipt.status < 500 else "provider_outcome_unknown"
                row.state = "rejected" if receipt.status < 500 else "unknown"
                if receipt.status in (401, 403):
                    control.provider_hold = "provider_auth_failed"
                if receipt.status == 429:
                    try:
                        delay = max(60, min(86400, int(receipt.headers.get("retry-after", "60"))))
                    except ValueError:
                        delay = 60
                    control.cooldown_until = stamp() + delay
            elif usage_state != "known":
                row.error_code = "response_invalid" if usage_state == "unknown" else "pricing_unknown"
                control.provider_hold = "accounting_attention"
            audit(db, "provider", "attempt_settled", attempt_id, "Saved receipt settled provider outcome",
                before, {"state": row.state, "error_code": row.error_code,
                    "usage_state": row.usage_state, "cost_microusd": amount})
            if amount is not None:
                db.add(GenerationOutbox(key="usage:" + attempt_id, kind="telemetry",
                    payload_json=dump({"attempt_id": attempt_id, "operation_id": row.operation_id,
                        "model": row.model, "usage": usage, "cost_microusd": amount})))
            await settle_attempt(db, row, {"attempt_id": attempt_id, "receipt_digest": digest(row.receipt_json),
                                           "usage_state": usage_state, "status": receipt.status})
            if control.provider_hold == "reservation_exceeded":
                row.error_code = "reservation_exceeded"
            log.info("provider receipt attempt=%s status=%s usage=%s", attempt_id, receipt.status, usage_state)

    async def reconcile_receipts(self):
        """Complete local accounting after a crash between receipt and parsing."""
        async with self.maker() as db:
            rows = list((await db.scalars(select(ProviderAttempt).where(
                ProviderAttempt.receipt_json.is_not(None), ProviderAttempt.settled_at == 0
            ).limit(100))).all())
            saved = [(row.id, json.loads(row.receipt_json)) for row in rows]
        for attempt_id, raw in saved:
            await self.record_receipt(attempt_id, Receipt(raw["status"], raw["body"], raw["headers"]))
