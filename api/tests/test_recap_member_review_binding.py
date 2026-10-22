from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select

from app.services.generation.models import ContentArtifact, ProviderAttempt
from app.services.generation.recap_models import RecapProviderAttempt, RecapQualificationReview
from app.services.generation.store import Held, dump
from app.services.recap_video import qualification as q
from tests.test_recap_qualification import qualified_series


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['none', 'receipt', 'cost', 'recovery', 'missing_binding', 'authority'])
async def test_manual_member_editorial_binding_freezes_receipts_without_phone_qualification(
        maker, tmp_path, monkeypatch, change):
    # Mutation: accept changed receipt/cost/proof after manual review, or require fake writer/phone evidence.
    ident, media_id = await qualified_series(maker, tmp_path, monkeypatch)
    from app.services.recap_video import editorial
    validated = []
    async def validate(db, artifact):
        validated.append(artifact.id)
        if change == 'authority' and len(validated) > 1:
            raise Held('recap_editorial_authority_changed')
    monkeypatch.setattr(editorial, 'require_editorial_artifact', validate)
    async with maker.begin() as db:
        script = await db.get(ContentArtifact, 'script')
        script.provenance = 'editorial_reviewed'
        await db.execute(delete(ProviderAttempt).where(ProviderAttempt.operation_id == script.operation_id))
        await db.execute(delete(RecapQualificationReview))
        binding = await q.member_review_binding(db, ident, media_id)
        assert validated == ['script']
        proof = SimpleNamespace(authorization_kind='manual', reviewer_id='owner', episode_id=ident,
            scope_json=dump(dict(audience='members', media_id=media_id, member_review_binding=binding)))
        attempt = await db.get(RecapProviderAttempt, 'narration-0')
        if change == 'receipt': attempt.receipt_json = '{"changed":true}'
        if change == 'cost': attempt.cost_microusd += 1
        if change == 'recovery': attempt.recovery_receipt_json = '{"changed":true}'
        if change == 'missing_binding': proof.scope_json = dump(dict(audience='members', media_id=media_id))
        if change == 'none':
            assert await q.require_standing_proof(db, proof) == {}
            assert not (await db.scalars(select(RecapQualificationReview))).all()
        else:
            with pytest.raises(Held):
                await q.require_standing_proof(db, proof)


@pytest.mark.asyncio
@pytest.mark.parametrize('adopted', [False, True])
async def test_only_audited_adoption_resolves_invalid_receipt_for_manual_members(
        maker, tmp_path, monkeypatch, adopted):
    # Mutation: any recovery receipt resolves a failure, or manual resolution grants public qualification.
    ident, media_id = await qualified_series(maker, tmp_path, monkeypatch)
    from app.services.recap_video import recovery
    checked = []
    async def resolved(db, attempt):
        checked.append(attempt.id)
        return adopted
    monkeypatch.setattr(recovery, 'adopted_audio_resolves_outcome', resolved)
    async with maker.begin() as db:
        attempt = await db.get(RecapProviderAttempt, 'narration-0')
        attempt.error_code = 'response_invalid'
        attempt.recovery_receipt_json = '{}'
        with pytest.raises(Held, match='qualification_receipts_unreconciled'):
            await q.review_binding(db, ident, media_id)
        if adopted:
            binding = await q.review_binding(db, ident, media_id, manual_members=True)
            assert binding['receipt_evidence'][0][-1] == 'response_invalid'
        else:
            with pytest.raises(Held, match='qualification_receipts_unreconciled'):
                await q.review_binding(db, ident, media_id, manual_members=True)
        assert checked == ['narration-0']
        assert attempt.error_code == 'response_invalid'


@pytest.mark.asyncio
async def test_member_preview_binds_review_evidence_before_approval(maker, tmp_path, monkeypatch):
    # Mutation: compute preview/approval digest without the reviewed receipt binding.
    from tests.test_recap_publication import ready_article
    from app.services.recap_video import publication
    ident = await ready_article(maker, tmp_path, monkeypatch)
    evidence = {'receipt': 'original'}
    async def binding(db, episode_id, media_id):
        return dict(evidence)
    monkeypatch.setattr(q, 'member_review_binding', binding)
    async with maker.begin() as db:
        preview = await publication.preview_publication(db, ident, 0, None, audience='members')
        evidence['receipt'] = 'changed'
        with pytest.raises(Held, match='publication_preview_changed'):
            await publication.record_approval(db, ident, 0, None, audience='members',
                reviewer=SimpleNamespace(id='admin', is_admin=True), reason='Exact member review',
                preview_digest=preview['digest'])
