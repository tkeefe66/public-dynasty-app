"""Retire only unused, exactly proven editorial authority; preserve its history."""
import json

from sqlalchemy import select

from app.services.generation.models import ArtifactHead, ContentArtifact, GenerationAudit, GenerationOperation, ProviderAttempt
from app.services.generation.recap_models import RecapStage, RecapProviderAttempt, RecapPublicationSelection, RecapPublication
from app.services.generation.store import Held, digest, dump, lock_control


async def require_retired_editorial(db, artifact):
    job = await db.get(GenerationOperation, artifact.operation_id)
    if (artifact.provenance != 'editorial_reviewed' or not job or job.kind != 'recap_editorial'
            or job.state != 'cancelled' or job.reason != 'editorial_unused_retired'
            or job.calls != 0 or job.max_calls != 0 or job.artifact_id != artifact.id
            or digest(json.loads(artifact.payload_json)) != artifact.digest
            or (job.subject, job.series_id, job.league_id) != (artifact.subject, artifact.series_id, artifact.league_id)):
        raise Held('recap_script_saved_output_requires_review')
    audits = (await db.scalars(select(GenerationAudit).where(
        GenerationAudit.action == 'recap_editorial_unused_retired', GenerationAudit.target == artifact.id))).all()
    expected = dict(artifact_id=artifact.id, artifact_digest=artifact.digest, operation_id=job.id,
        subject=artifact.subject, revision=artifact.revision)
    if len(audits) != 1 or json.loads(audits[0].after_json) != expected:
        raise Held('recap_script_saved_output_requires_review')
    if await db.scalar(select(ProviderAttempt.id).where(ProviderAttempt.operation_id == job.id).limit(1)):
        raise Held('recap_editorial_retirement_has_requests')


async def retract_unused_editorial(db, *, artifact_id, actor_id, reason):
    from app.services.recap_video.qualification import require_admin_actor
    from app.services.recap_video.editorial import require_editorial_artifact
    from app.services.generation.recap_budget import release_unsubmitted
    await require_admin_actor(db, actor_id)
    await lock_control(db)
    if not reason.strip():
        raise Held('recap_editorial_reason_required')
    artifact = await db.get(ContentArtifact, artifact_id)
    job = await require_editorial_artifact(db, artifact, require_renderable=False)
    episode_id = json.loads(artifact.payload_json)['episode_id']
    if (await db.scalar(select(RecapStage.id).where(RecapStage.episode_id == episode_id, RecapStage.kind != 'preflight').limit(1))
            or await db.scalar(select(RecapProviderAttempt.id).where(RecapProviderAttempt.episode_id == episode_id).limit(1))
            or await db.scalar(select(ProviderAttempt.id).where(ProviderAttempt.operation_id == job.id).limit(1))
            or await db.scalar(select(RecapPublicationSelection.id).where(RecapPublicationSelection.episode_id == episode_id).limit(1))
            or await db.scalar(select(RecapPublication.episode_id).where(RecapPublication.episode_id == episode_id, RecapPublication.script_id != '').limit(1))):
        raise Held('recap_editorial_retirement_media_started')
    head = await db.get(ArtifactHead, artifact.subject)
    await db.delete(head)
    job.state = 'cancelled'
    job.reason = 'editorial_unused_retired'
    await release_unsubmitted(db, job.id, 'editorial_unused_retired')
    db.add(GenerationAudit(actor_id=actor_id, action='recap_editorial_unused_retired', target=artifact.id,
        reason=reason, after_json=dump(dict(artifact_id=artifact.id, artifact_digest=artifact.digest,
            operation_id=job.id, subject=artifact.subject, revision=artifact.revision))))
    await db.flush()
    return dict(artifact_id=artifact.id, operation_id=job.id, retired=True, new_writer_calls=0)
