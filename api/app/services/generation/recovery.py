"""Offline restore gate. Deployment evidence never comes from restored rows."""
import hashlib
import json
from sqlalchemy import delete, func, select

from app.db.base import Base
from app.services.generation.models import (
    GenerationControl,
    GenerationOperation,
    ProviderAttempt,
)
from app.services.generation.store import Held, audit, data, digest, dump, lock_control
from app.config import get_settings


def bootstrap_control(row):
    return (row.id == "global" and row.epoch == "" and row.hold == "activation_required"
        and row.revision == 1 and not row.provider_hold and not row.cooldown_until
        and row.breakers_json == "{}")


async def quarantine(db):
    control = await lock_control(db)
    control.hold = "restore_quarantine"
    control.revision += 1
    jobs = (await db.scalars(select(GenerationOperation).where(
        GenerationOperation.state.in_(("queued", "running", "held", "needs_attention"))))).all()
    for job in jobs:
        job.generation += 1
        job.lease_until = 0
        job.state, job.reason = "held", "restore_reapproval_required"
    for attempt in (await db.scalars(select(ProviderAttempt).where(
            ProviderAttempt.state == "dispatching"))).all():
        attempt.state = "unknown"
    from app.services.generation.recap_models import RecapStage, RecapProviderAttempt
    for stage in (await db.scalars(select(RecapStage).where(RecapStage.state != "succeeded"))).all():
        stage.generation += 1
        stage.lease_until = 0
        stage.state, stage.reason = "held", "restore_reapproval_required"
    for attempt in (await db.scalars(select(RecapProviderAttempt).where(
            RecapProviderAttempt.state == "dispatching"))).all():
        attempt.state = "unknown"
    from app.services.generation.recap_models import RecapPublicationControl, RecapRecoveryRequest
    serving = await db.get(RecapPublicationControl, 'global')
    if serving:
        serving.quarantined = True
        serving.reconciliation_digest = ''
    for request in (await db.scalars(select(RecapRecoveryRequest))).all():
        request.generation += 1
        request.lease_until = 0
        if request.state in ('pending','running'):
            request.state, request.error = 'held','restore_reapproval_required'
    audit(db, "restore", "restore_quarantined", "global",
        "Restore cannot prove which post-snapshot requests executed; rotate epoch and reconcile before activation",
        after={"old_epoch": control.epoch, "held_jobs": len(jobs)})


async def restore_database(db, blob):
    """Accept only an empty migrated DB (including its pristine bootstrap row)."""
    from app.services.backup_service import load_database
    for table in Base.metadata.sorted_tables:
        count = await db.scalar(select(func.count()).select_from(table))
        if not count:
            continue
        row = await db.get(GenerationControl, "global") if table.name == "generation_control" else None
        if count != 1 or not row or not bootstrap_control(row):
            raise ValueError(f"Restore target is not empty: {table.name}")
        await db.execute(delete(GenerationControl))
    counts = await load_database(db, blob)
    await quarantine(db)
    return counts


def external_restore_gate():
    """Public health proof describes this responding instance only, never DB."""
    config = get_settings()
    epoch = config.recap_restore_epoch
    quarantined = bool(epoch and config.recap_publication_mode == 'quarantine'
        and config.generation_emergency_pause and config.recap_serving_epoch == epoch
        and config.generation_execution_epoch == epoch)
    return {'quarantined':quarantined,
        'epoch_sha256':hashlib.sha256(epoch.encode()).hexdigest() if epoch else ''}


def require_external_quarantine(manifest=None):
    if not external_restore_gate()['quarantined']:
        raise Held('Configure external serving quarantine, emergency pause and matching fresh restore/execution/serving epochs first')
    old = (manifest or {}).get('authority', {})
    if get_settings().recap_restore_epoch in old.get('publication_epochs', [])+old.get('execution_epochs', []):
        raise Held('fresh_restore_epoch_required')


async def financial_digest(db):
    """All revisions, prose/media attempts and obligations; never latest-take only."""
    from app.services.generation.recap_models import (RecapProviderAttempt, RecapBudgetAllocation,
        RecapBudgetPlan, RecapBudgetPolicy, ProviderAccountControl)
    from app.services.generation.models import GenerationPolicy
    tables = (ProviderAttempt, RecapProviderAttempt, RecapBudgetAllocation, RecapBudgetPlan,
        RecapBudgetPolicy, GenerationPolicy, ProviderAccountControl)
    # Quarantine changes dispatching to unknown but not the financial identity.
    inventory = {}
    for model in tables:
        rows=[]
        for row in (await db.scalars(select(model))).all():
            item=data(row)
            if item.get('state') == 'dispatching':
                item['state']='unknown'
            rows.append(item)
        inventory[model.__tablename__]=sorted(rows,key=lambda r:dump(r))
    return digest(inventory)


async def export_restore_authority(db):
    """Offline export from CURRENT source while all workers/serving quarantined.

    Operator binds digest in deployment config independently of backup contents.
    """
    from app.services.generation.recap_models import RecapShareDecision,RecapPublication
    require_external_quarantine()
    await lock_control(db)
    return {'share_decisions':[data(r) for r in (await db.scalars(
        select(RecapShareDecision).order_by(RecapShareDecision.scope))).all()],
        'publications':[data(r) for r in (await db.scalars(select(RecapPublication).order_by(RecapPublication.episode_id))).all()],
        'financial_digest':await financial_digest(db)}


PUBLICATION_BINDING_FIELDS=('episode_id','series_id','league_id','season','week','article_id',
    'article_revision','article_digest','article_json','facts_digest','media_id','media_json',
    'script_id','approval_id','policy_digest','published_at')


async def reconcile_restore(db, manifest: dict, objects: dict) -> dict:
    """objects is independently measured SHA256/size, never trusted S3 metadata.

    Missing current evidence disables old tokens/future permission and retains
    execution quarantine. A changed financial ledger needs newer recovery data;
    an operator approval alone cannot erase missing spend or uncertain sends.
    """
    from app.services.generation.recap_models import (RecapAsset, RecapShareDecision,
        RecapPublicationControl, RecapRestoreReport, RecapBackupPoint, RecapPublication)
    require_external_quarantine(manifest)
    config = get_settings()
    await lock_control(db)
    expected={a.storage_key:{'sha256':a.digest,'size':a.size} for a in (await db.scalars(select(RecapAsset))).all()}
    object_errors=sorted(k for k,v in expected.items() if manifest.get('media_objects',{}).get(k) != v or objects.get(k) != v)
    point=await db.get(RecapBackupPoint,manifest.get('run_id',''))
    if point and not object_errors:
        # This dump captured its own barrier; its final manifest proves upload
        # completed. Other interrupted points still require offline maintenance.
        point.state='complete'
        point.objects_json=dump(expected)
        point.authority_json=dump(manifest.get('authority',{}))
    current=manifest.get('current_authority')
    trusted = bool(isinstance(current,dict) and config.recap_restore_evidence_digest
        and digest(current) == config.recap_restore_evidence_digest)
    decisions = {r['scope']:r for r in current.get('share_decisions',[])} if trusted else {}
    for row in (await db.scalars(select(RecapShareDecision))).all():
        fresh=decisions.pop(row.scope,None)
        if fresh and fresh['revision'] >= row.revision:
            for field in ('revision','allowed','opted_out','token','token_digest'):
                setattr(row,field,fresh[field])
        else:
            # Keep existing opt-out tombstone; never turn missing evidence into consent.
            row.allowed=False
            row.token=row.token_digest=None
            row.revision += 1
    for fresh in decisions.values():
        db.add(RecapShareDecision(**fresh))
    current_publications={row['episode_id']:row for row in current.get('publications',[])} if trusted else {}
    held_publications=[]
    for row in (await db.scalars(select(RecapPublication))).all():
        fresh=current_publications.get(row.episode_id)
        if (not fresh or fresh['authority_revision'] < row.authority_revision
                or any(fresh.get(field) != getattr(row,field) for field in PUBLICATION_BINDING_FIELDS)):
            row.enabled=False
            row.hold='restore_current_publication_changed'
            held_publications.append(row.episode_id)
        else:
            for field in ('enabled','withdrawn','hold','share_revision','authority_revision','projected_revision'):
                setattr(row,field,fresh[field])
    finance_ok=trusted and current.get('financial_digest') == await financial_digest(db)
    report={'epoch':config.recap_restore_epoch,'reconciled':bool(trusted and finance_ok and not object_errors),
        'object_errors':object_errors,'current_authority_verified':trusted,'financial_ledger_matches':bool(finance_ok),
        'held_publications':held_publications,
        'evidence_digest':config.recap_restore_evidence_digest,'objects_digest':digest(expected),
        'financial_digest':await financial_digest(db)}
    row=await db.get(RecapRestoreReport,config.recap_restore_epoch)
    if row:
        row.digest,row.report_json=digest(report),dump(report)
    else:
        db.add(RecapRestoreReport(epoch=config.recap_restore_epoch,digest=digest(report),report_json=dump(report)))
    serving=await db.get(RecapPublicationControl,'global')
    if not serving:
        serving=RecapPublicationControl(id='global',epoch=config.recap_restore_epoch,reconciliation_digest='')
        db.add(serving)
    serving.quarantined=True
    audit(db,'offline-operator','restore_reconciled','global','Hashes/current authority/budgets checked; explicit reopening still required',after=report)
    return report


async def require_restore_report(db):
    from app.services.generation.recap_models import RecapRestoreReport
    config=get_settings()
    row=await db.get(RecapRestoreReport,config.recap_restore_epoch,populate_existing=True)
    report=json.loads(row.report_json) if row else {}
    if (not config.recap_restore_epoch or not row or row.digest != digest(report) or not report.get('reconciled')
            or report.get('evidence_digest') != config.recap_restore_evidence_digest
            or config.recap_serving_epoch != config.recap_restore_epoch
            or config.generation_execution_epoch != config.recap_restore_epoch):
        raise Held('restore_reconciliation_required')
    return row


async def reopen_restore(db, *, expected_digest, actor_id):
    """Explicit offline action while deployment is STILL quarantined."""
    from app.services.generation.recap_models import RecapPublicationControl,RecapPublication
    require_external_quarantine()
    await lock_control(db)
    report=await require_restore_report(db)
    if not actor_id or expected_digest != report.digest:
        raise Held('restore_report_review_required')
    serving=await db.get(RecapPublicationControl,'global')
    serving.epoch=report.epoch
    serving.reconciliation_digest=report.digest
    serving.quarantined=False
    control=await lock_control(db)
    control.hold='restore_reconciled'
    control.revision += 1
    for row in (await db.scalars(select(RecapPublication))).all():
        row.epoch=report.epoch
    audit(db,actor_id,'restore_serving_reopened','global','Explicit verified restore report approval')
    # Execution remains held; normal admin activation must use this report and
    # fresh epoch. Standing proofs keep ORIGINAL JSON and require requalification.
    return report.digest
