"""Receipt-only release of superseded, never-dispatched narration exposure."""
import json

from sqlalchemy import select

from app.services.generation.models import ContentArtifact, GenerationOperation
from app.services.generation.recap_models import RecapBudgetAllocation, RecapProviderAttempt, RecapStage
from app.services.generation.store import Held, Conflict, audit, data, digest, lock_control
from app.services.recap_video.qualification import require_admin_actor


async def preview_original_envelope_release(db,*,artifact_id,actor_id):
    await require_admin_actor(db,actor_id)
    await lock_control(db)
    from app.services.recap_video.editorial import require_editorial_artifact, _receipts
    artifact=await db.get(ContentArtifact,artifact_id)
    # Accounting proof does not require a currently unexpired voice preflight.
    # All immutable editorial, factual, receipt, actor and policy checks remain.
    await require_editorial_artifact(db,artifact,require_preflight=False)
    old=await db.get(GenerationOperation,json.loads(artifact.payload_json)['original_operation_id'])
    if (not old or old.kind!='generation' or old.feature!='recap_video'
            or old.state not in ('held','needs_attention') or old.calls!=old.max_calls or old.max_calls<=0 or old.artifact_id
            or await db.scalar(select(ContentArtifact.id).where(ContentArtifact.operation_id==old.id).limit(1))
            or await db.scalar(select(RecapStage.id).where(RecapStage.operation_id==old.id,RecapStage.kind!='preflight').limit(1))
            or await db.scalar(select(RecapProviderAttempt.id).where(RecapProviderAttempt.operation_id==old.id).limit(1))):
        raise Held('editorial_original_envelope_not_unused')
    _,receipts=await _receipts(db,old)
    allocations=(await db.scalars(select(RecapBudgetAllocation).where(RecapBudgetAllocation.operation_id==old.id,
        RecapBudgetAllocation.key=='narration-envelope').order_by(RecapBudgetAllocation.id))).all()
    if any(a.attempt_id is not None or (a.actual_microusd is not None and a.actual_microusd!=0) for a in allocations):
        raise Held('editorial_original_envelope_has_exposure')
    snapshot=dict(artifact_id=artifact.id,artifact_digest=artifact.digest,original_operation_id=old.id,
        original_generation=old.generation,original_state=old.state,receipt_digest=receipts,
        allocations=[data(a) for a in allocations],release_microusd=sum(a.outstanding_microusd for a in allocations),new_provider_calls=0)
    return {**snapshot,'digest':digest(snapshot)}


async def reconcile_original_envelope(db,*,artifact_id,preview_digest,actor_id,reason):
    if not reason.strip(): raise Held('editorial_envelope_reason_required')
    snapshot=await preview_original_envelope_release(db,artifact_id=artifact_id,actor_id=actor_id)
    if snapshot['digest']!=preview_digest:
        raise Conflict('Original narration reservation changed. Preview reconciliation again.')
    from app.services.generation.recap_budget import settle_allocation
    for item in snapshot['allocations']:
        if item['actual_microusd'] is None:
            await settle_allocation(db,item['id'],0,dict(non_submission='accepted_editorial_superseded_original',
                artifact_id=artifact_id,original_operation_id=snapshot['original_operation_id']))
    audit(db,actor_id,'recap_editorial_original_envelope_released',snapshot['original_operation_id'],reason,
        after={k:snapshot[k] for k in ('artifact_id','artifact_digest','release_microusd','receipt_digest')})
    return dict(released_microusd=snapshot['release_microusd'],new_provider_calls=0)
