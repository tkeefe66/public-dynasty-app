"""API maintenance: proposals, transactional reference checks, deferred unlink.

Metadata/receipts never expire here. Backup pin expiry is explicit retirement,
not a wall-clock shortcut: an extant manifest remains a recovery promise.
"""
import asyncio
import json

from sqlalchemy import select
from app.services.generation.recap_models import (
    RecapAsset, RecapBackupPoint, RecapBudgetAllocation, RecapBudgetPlan,
    RecapObjectDeletion, RecapProviderAttempt, RecapPublication,
    RecapPublicationApproval, RecapRecovery, RecapRecoveryRequest, RecapStage,
)
from app.services.generation.store import Held, data, dump, lock_control

DAY = 86400
GRACE = 7 * DAY


def can_remove_failed_take(*, age_days, unresolved, referenced):
    return age_days >= 90 and not unresolved and not referenced


def strings(value):
    """Exact scalar identities in persisted JSON (never substring matching)."""
    if isinstance(value, str):
        return {value}
    if isinstance(value, dict):
        return set().union(*(strings(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(strings(v) for v in value)) if value else set()
    return set()


def json_refs(value):
    return strings(json.loads(value or '{}'))


async def reference_state(db):
    """Load once per decision, under control lock for deletion admission."""
    stages = {s.id:s for s in (await db.scalars(select(RecapStage))).all()}
    refs, protected_stages, unresolved = set(), set(), set()
    for row in (await db.scalars(select(RecapBackupPoint))).all():
        if row.state == 'snapshot':
            return stages, refs, protected_stages, unresolved, True
        if row.state != 'retired':
            refs.update(json.loads(row.objects_json))
    for row in (await db.scalars(select(RecapPublication))).all():
        # Withdrawal/revocation is not removal consent. Preserve selected masters.
        protected_stages.add(row.media_id)
        refs.update(json_refs(row.media_json))
    for row in (await db.scalars(select(RecapPublicationApproval))).all():
        refs.update(json_refs(row.scope_json))
    for row in (await db.scalars(select(RecapRecovery))).all():
        refs.update(json_refs(row.before_json))
        # Free archived evidence and paid ancestors must remain reproducible.
        protected_stages.add(row.stage_id)
    for row in (await db.scalars(select(RecapProviderAttempt))).all():
        refs.update(json_refs(row.request_json))
        if row.cost_microusd is None or row.state in ('dispatching','unknown'):
            unresolved.add(row.stage_id)
        # Explicit history recovery may reference keys before asset registration.
        refs.update(json_refs(row.identity_json))
        if row.cost_microusd is None:
            refs.update(json_refs(row.receipt_json))
            refs.update(json_refs(row.recovery_receipt_json))
    attempts = {r.id:r for r in (await db.scalars(select(RecapProviderAttempt))).all()}
    for row in (await db.scalars(select(RecapRecoveryRequest))).all():
        if row.state in ('pending','running','held'):
            refs.update(json_refs(row.identity_json))
            if row.attempt_id in attempts:
                unresolved.add(attempts[row.attempt_id].stage_id)
    plans = {p.id:p.episode_id for p in (await db.scalars(select(RecapBudgetPlan))).all()}
    uncertain_episodes = {plans.get(a.plan_id) for a in (await db.scalars(select(RecapBudgetAllocation))).all()
        if a.outstanding_microusd or a.actual_microusd is None}
    for stage in stages.values():
        refs.update(json_refs(stage.input_json))
        refs.update(json_refs(stage.evidence_json))
        if stage.state not in ('failed','cancelled','superseded'):
            refs.update(json_refs(stage.result_json))
        if stage.episode_id in uncertain_episodes:
            unresolved.add(stage.id)
    # A new active descendant pins all paid/free ancestor bytes, even when old
    # narration generation is no longer the current execution revision.
    protected_stages.update(refs.intersection(stages))
    protected_stages.update(s.id for s in stages.values()
        if s.state not in ('failed','cancelled','superseded'))
    pending = list(protected_stages)
    while pending:
        stage = stages.get(pending.pop())
        if stage and stage.predecessor_id and stage.predecessor_id not in protected_stages:
            protected_stages.add(stage.predecessor_id)
            pending.append(stage.predecessor_id)
    return stages, refs, protected_stages, unresolved, False


async def retention_candidates(db, now: int) -> list[dict]:
    stages, refs, protected, unresolved, barrier = await reference_state(db)
    if barrier:
        return []
    proposals = []
    for asset in (await db.scalars(select(RecapAsset))).all():
        stage = stages.get(asset.stage_id)
        referenced = asset.id in refs or asset.storage_key in refs or asset.stage_id in protected
        if not stage or referenced or stage.id in unresolved:
            continue
        age = now - asset.created_at
        # JSON is facts/scripts/receipts/QA evidence for edition life.
        if asset.media_type == 'application/json':
            continue
        disposable = asset.media_type == 'image/png' and stage.kind in ('render','media_check')
        failed = stage.state in ('failed','cancelled','superseded')
        if (disposable and age >= GRACE or failed and can_remove_failed_take(
                age_days=age / DAY, unresolved=False, referenced=False)):
            proposals.append({'storage_key':asset.storage_key, 'asset_id':asset.id,
                'created_at':asset.created_at, 'reason':'frame' if disposable else 'failed_take'})
    return proposals


async def claim_deletions(db, proposals, *, now):
    """Caller commits these fences BEFORE calling finish_deletions (storage I/O)."""
    await lock_control(db)
    db.expire_all()
    allowed = {r['storage_key']:r for r in await retention_candidates(db, now)}
    stages, refs, _, _, barrier = await reference_state(db)
    if barrier:
        return []
    registered = {a.storage_key:a for a in (await db.scalars(select(RecapAsset))).all()}
    claimed = []
    for proposal in proposals:
        key = proposal['storage_key']
        if await db.get(RecapObjectDeletion, key):
            continue
        asset = registered.get(key)
        if asset:
            if key not in allowed or proposal.get('asset_id') != asset.id:
                continue
            evidence = data(asset)
            stage = stages[asset.stage_id]
            # Fence old worker and any preview that raced the proposal. Metadata
            # retains result/receipt provenance; missing asset prevents adoption.
            stage.generation += 1
            stage.lease_until = 0
            stage.reason = 'retention_expired'
            await db.delete(asset)
        else:
            if proposal.get('reason') != 'orphan' or now-proposal['created_at'] < GRACE or key in refs:
                continue
            evidence = dict(proposal)
        db.add(RecapObjectDeletion(storage_key=key, asset_json=dump(evidence), claimed_at=now))
        claimed.append(key)
    await db.flush()
    return claimed


async def finish_deletions(maker, store):
    """Retry-safe unlink. Never holds a transaction/control lock during storage."""
    async with maker() as db:
        keys = list((await db.scalars(select(RecapObjectDeletion.storage_key).where(
            RecapObjectDeletion.state == 'pending'))).all())
    for key in keys:
        await asyncio.to_thread(store.delete_unreferenced, key)
        async with maker.begin() as db:
            await lock_control(db)
            row = await db.get(RecapObjectDeletion, key)
            row.state = 'deleted'
    return len(keys)


async def require_registerable(db, key):
    await lock_control(db)
    if await db.get(RecapObjectDeletion, key):
        raise Held('media_object_retired')


async def cleanup(maker, store, now):
    candidates = await asyncio.to_thread(lambda:list(store.older_than(now-GRACE)))
    async with maker.begin() as db:
        proposals = await retention_candidates(db, now)
        proposals.extend({'storage_key':key,'reason':'orphan','created_at':now-GRACE} for key in candidates)
        await claim_deletions(db, proposals, now=now)
    return await finish_deletions(maker, store)
