import json

import pytest
from sqlalchemy import select

from app.services.generation.models import ContentArtifact, GenerationOperation, ProviderAttempt
from app.services.generation.recap_models import RecapBudgetAllocation
from app.services.generation.store import Held
from app.services.recap_video import editorial
from app.services.recap_video.editorial_envelope import preview_original_envelope_release, reconcile_original_envelope
from tests.test_recap_editorial import setup, preview


async def envelope(db):
    from app.services.recap_video.narration_budget import envelope_allocation
    from app.services.generation.recap_budget import reserve_plan
    from app.services.generation.models import stamp
    old=await db.get(GenerationOperation,'job')
    await reserve_plan(db,json.loads(old.payload_json)['episode_id'],old.series_id,'operation:'+old.id,
        [await envelope_allocation(db,old)],stamp())


@pytest.mark.asyncio
async def test_editorial_acceptance_releases_only_unused_original_envelope(maker,tmp_path,monkeypatch):
    # Mutation: original narration envelope remains reserved beside accepted editorial envelope.
    _,script,review=await setup(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        await envelope(db)
        p=await preview(db,script,review)
        result=await editorial.apply_editorial(db,preview_id=p['preview_id'],preview_digest=p['digest'],actor_id='owner',reason='Approve exact editorial correction')
        original=await db.scalar(select(RecapBudgetAllocation).where(RecapBudgetAllocation.operation_id=='job',RecapBudgetAllocation.key=='narration-envelope'))
        new=await db.scalar(select(RecapBudgetAllocation).where(RecapBudgetAllocation.operation_id==result['operation_id'],RecapBudgetAllocation.key=='narration-envelope'))
        assert original.actual_microusd==0 and original.outstanding_microusd==0
        assert new.actual_microusd is None and new.outstanding_microusd>0
        assert (await db.get(GenerationOperation,'job')).state=='needs_attention'


@pytest.mark.asyncio
@pytest.mark.parametrize('change',['none','unknown','bound','paid'])
async def test_saved_editorial_envelope_reconciliation_is_fenced(maker,tmp_path,monkeypatch,change):
    # Mutation: receipt-only repair releases bound exposure or ignores later unknown receipts.
    _,script,review=await setup(maker,tmp_path,monkeypatch)
    async with maker.begin() as db:
        p=await preview(db,script,review)
        result=await editorial.apply_editorial(db,preview_id=p['preview_id'],preview_digest=p['digest'],actor_id='owner',reason='Approve')
        await envelope(db)  # Reproduce historical stale envelope after accepted editorial output.
        original=await db.scalar(select(RecapBudgetAllocation).where(RecapBudgetAllocation.operation_id=='job',RecapBudgetAllocation.key=='narration-envelope'))
        if change=='unknown': (await db.get(ProviderAttempt,'saved-1')).usage_state='unknown'
        elif change=='bound': original.attempt_id='bound-attempt'
        elif change=='paid': original.actual_microusd=17
        if change!='none':
            with pytest.raises(Held): await preview_original_envelope_release(db,artifact_id=result['artifact_id'],actor_id='owner')
            assert original.actual_microusd==(17 if change=='paid' else None)
            return
        release=await preview_original_envelope_release(db,artifact_id=result['artifact_id'],actor_id='owner')
        assert original.actual_microusd is None
        await reconcile_original_envelope(db,artifact_id=result['artifact_id'],preview_digest=release['digest'],actor_id='owner',reason='Release superseded unused narration reservation')
        assert original.actual_microusd==0 and original.outstanding_microusd==0
