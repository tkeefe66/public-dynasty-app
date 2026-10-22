"""Audited, zero-provider editorial correction before canonical media starts."""
import json
from decimal import Decimal

from sqlalchemy import select

from app.services.generation.models import (ArtifactHead, ContentArtifact, GenerationOperation,
    GenerationOutbox, ProviderAttempt)
from app.services.generation.recap_models import (RecapAttention, RecapEpisode, RecapObservation,
    RecapProviderAttempt, RecapStage)
from app.services.generation.store import Held, audit, digest, dump, lock_control
from app.services.recap_video.contracts import _published_article
from app.services.recap_video.publication import edition_row, serving_gate
from app.services.recap_video.qualification import require_admin_actor
from app.services.recap_video.readiness import competitive_digest, source_ready


def corrected_prose(data, source, corrections):
    """Only finite source-backed correction shapes; never arbitrary replacement."""
    text = data['markdown']
    scores = {p['roster_id']: p for p in source['scores'][str(source['week'])]}
    owners = {p['owner_name']: p['roster_id'] for p in source['participants'] if p.get('owner_name')}
    for correction in corrections:
        kind = correction.get('kind')
        if kind == 'scoring_label' and set(correction) == {'kind'}:
            if Decimal(str(source['scoring_settings']['rec'])) != Decimal('1'):
                raise Held('article_scoring_correction_unproved')
            before, after = 'half-PPR', 'full-PPR'
        elif kind == 'remove_season_low' and set(correction) == {'kind', 'owner'}:
            owner = correction['owner']; row = scores[owners[owner]]
            before = f'{owner} Posts His Lowest Score of the Season'
            after = f"{owner} Posts {row['points']}"
        elif kind == 'winner_rank' and set(correction) == {'kind', 'owner'}:
            owner = correction['owner']; row = scores[owners[owner]]
            winners = []
            for candidate in scores.values():
                opponents = [other for other in scores.values() if other['matchup_id'] == candidate['matchup_id']
                    and other['roster_id'] != candidate['roster_id']]
                if candidate['matchup_id'] is None or len(opponents) != 1:
                    raise Held('article_winner_pairing_unproved')
                if Decimal(candidate['points']) > Decimal(opponents[0]['points']):
                    winners.append(candidate)
            if row not in winners or Decimal(row['points']) != min(Decimal(r['points']) for r in winners):
                raise Held('article_winner_rank_unproved')
            before = f"{owner}'s starting roster put up **{row['points']} points** — the second-lowest total among all winners this week."
            after = before.replace('second-lowest', 'lowest')
        elif kind == 'remove_unsupported_yard_example' and set(correction) == {'kind'}:
            if (Decimal(str(source['scoring_settings']['rush_yd'])) != Decimal('0.1')
                    or Decimal(str(source['scoring_settings']['rec_yd'])) != Decimal('0.1')):
                raise Held('article_yard_example_unproved')
            before, after = 'One reception. One extra yard. One overtime extra point. Gone.', 'One reception. One overtime extra point. Gone.'
        else:
            raise Held('article_correction_kind_unsupported')
        if text.count(before) != 1:
            raise Held('article_correction_exact_anchor_required')
        text = text.replace(before, after, 1)
    if text == data['markdown']:
        raise Held('article_correction_empty')
    return text


async def correct_scoring_label(db, episode_id, *, artifact_id, actor_id, cache_dir,
                                corrections=None, reason=None, apply=False, expected_digest=None):
    """Preview/apply a separate revision, retaining original paid provenance.

    Caller owns transaction. Execute on API filesystem. An already-started script
    or media request requires its own recovery review and is deliberately refused.
    """
    if apply:
        await lock_control(db)
    await require_admin_actor(db, actor_id)
    gate = await serving_gate(db)
    episode = await db.get(RecapEpisode, episode_id, populate_existing=True)
    if (not episode or not episode.admitted_at or episode.lifecycle != 'correction'
            or episode.hold != 'recap_editorial_correction_required'):
        raise Held('article_editorial_hold_required')
    if await edition_row(db, episode.league_id, episode.season, episode.week):
        raise Held('article_media_publication_requires_separate_review')
    published = await _published_article(db, episode)
    if published['artifact_id'] != artifact_id:
        raise Held('article_correction_head_changed')
    artifact = await db.get(ContentArtifact, artifact_id, populate_existing=True)
    data = json.loads(artifact.payload_json)
    head = await db.get(ArtifactHead, artifact.subject, populate_existing=True)
    operation = await db.get(GenerationOperation, artifact.operation_id) if artifact.operation_id else None
    if (not operation or operation.state != 'succeeded' or operation.artifact_id != artifact.id
            or operation.feature != 'analyst' or operation.subject != artifact.subject
            or operation.league_id != episode.league_id or operation.series_id != episode.series_id):
        raise Held('article_original_operation_required')
    original_input = json.loads(operation.payload_json)
    original_facts = original_input.get('edition', {}).get('facts') or original_input.get('facts')
    if original_facts != data.get('facts'):
        raise Held('article_original_facts_changed')
    receipts = list((await db.scalars(select(ProviderAttempt).where(ProviderAttempt.operation_id == operation.id))).all())
    if not receipts or len(receipts) != operation.calls or any(r.state != 'received' or r.usage_state != 'known'
            or r.cost_microusd is None or not r.receipt_json or r.error_code for r in receipts):
        raise Held('article_original_receipts_unsettled')
    observation = await db.get(RecapObservation, episode.latest_observation_id)
    source = json.loads(observation.snapshot_json) if observation else {}
    original_source = data.get('facts', {}).get('source_snapshot')
    if (not observation or observation.episode_id != episode_id or digest(source) != observation.snapshot_digest
            or observation.snapshot_digest != episode.source_digest or not source_ready(episode, source)
            or not isinstance(original_source, dict)
            or competitive_digest(original_source) != competitive_digest(source)):
        raise Held('article_original_source_changed')
    stages = list((await db.scalars(select(RecapStage).where(RecapStage.episode_id == episode_id))).all())
    if (any(s.kind != 'preflight' or s.state not in ('held', 'succeeded') or s.lease_until for s in stages)
            or await db.scalar(select(RecapProviderAttempt.id).where(RecapProviderAttempt.episode_id == episode_id).limit(1))):
        raise Held('article_media_started_requires_separate_review')
    jobs = list((await db.scalars(select(GenerationOperation).where(GenerationOperation.league_id == episode.league_id))).all())
    for job in jobs:
        if job.id != operation.id and job.subject == artifact.subject and job.state not in ('succeeded','cancelled','failed','rejected'):
            raise Held('article_new_generation_exists')
        if job.feature == 'recap_video' and job.kind != 'media_preflight' and json.loads(job.payload_json).get('episode_id') == episode_id:
            if job.calls or job.state not in ('cancelled','failed','rejected'):
                raise Held('article_script_started_requires_separate_review')
    corrections = corrections if corrections is not None else [{'kind':'scoring_label'}]
    reason = reason or 'Corrected the scoring label to full PPR: the saved league rules award 1 point per reception. Matchup results are unchanged.'
    from app.services.analyst_store import AnalystEdition
    corrected = AnalystEdition.model_validate({**data, 'markdown':corrected_prose(data, original_source, corrections),
        'revision':artifact.revision + 1, 'original_markdown':None, 'correction_note':reason}).model_dump()
    proof = dict(episode_id=episode_id, artifact_id=artifact.id, artifact_digest=artifact.digest,
        corrected_digest=digest(corrected), observation_id=observation.id, source_digest=observation.snapshot_digest,
        facts_digest=episode.facts_digest, serving_epoch=gate.epoch, corrections=corrections,
        receipts=sorted((r.id,digest([r.receipt_json,r.cost_microusd])) for r in receipts),
        stages=[(s.id,s.generation,s.state,s.input_digest) for s in stages])
    fingerprint = digest(proof)
    report = dict(digest=fingerprint, applied=False, artifact_id=artifact.id,
        correction_revision=corrected['revision'], markdown=corrected['markdown'], correction_note=reason,
        provider_requests=0, added_cost_microusd=0)
    if not apply:
        return report
    if expected_digest != fingerprint:
        raise Held('article_recovery_preview_changed')
    if await db.scalar(select(ContentArtifact.id).where(ContentArtifact.subject == artifact.subject,
            ContentArtifact.revision == corrected['revision'])):
        raise Held('article_recovery_revision_exists')
    facts_record = json.loads(artifact.facts_json)
    original_validation = facts_record.pop('_validation', None)
    facts_record['editorial_recovery'] = {**proof, 'original_validation':original_validation}
    replacement = ContentArtifact(series_id=artifact.series_id, league_id=artifact.league_id, feature='analyst',
        subject=artifact.subject, revision=corrected['revision'], payload_json=dump(corrected), digest=digest(corrected),
        facts_json=dump(facts_record), provenance='reviewed_receipt_only_correction')
    from app.services.generation.publication import project_analyst
    project_analyst(cache_dir,replacement,artifact)
    db.add(replacement)
    await db.flush()
    head.artifact_id, head.revision = replacement.id, replacement.revision
    episode.article_digest = replacement.digest
    episode.lifecycle, episode.hold = 'ready', ''
    db.add(GenerationOutbox(key='artifact:'+replacement.id,kind='artifact',delivered=True,
        payload_json=dump({'artifact_id':replacement.id,'expected_artifact':artifact.id,'receipt_only_recovery_proof':fingerprint})))
    for attention in (await db.scalars(select(RecapAttention).where(RecapAttention.episode_id == episode_id,
            RecapAttention.reason == 'recap_editorial_correction_required'))).all():
        attention.state = 'resolved'
    audit(db,actor_id,'recap_article_receipt_only_correction',episode_id,reason,
        before={'artifact_id':artifact.id,'digest':artifact.digest},
        after={'artifact_id':replacement.id,'digest':replacement.digest,'proof_digest':fingerprint})
    return {**report,'applied':True,'corrected_artifact_id':replacement.id}
